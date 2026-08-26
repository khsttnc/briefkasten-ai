import json
import os
from typing import Any, Dict, List, Optional

from anthropic import (
    Anthropic,
    APIConnectionError,
    APIError,
    APIStatusError,
    AuthenticationError,
    RateLimitError,
)

from ..ai_service import AIAnalysisResult, BaseAIProvider
from ..config import (
    ANTHROPIC_API_KEY_ENV,
    ANTHROPIC_MODEL_ENV,
    DEFAULT_ANTHROPIC_MODEL,
    env_or_default,
)
# Reused, not retyped: the Document Intelligence signal-key prompt is
# provider-agnostic text built from document_intelligence.SIGNAL_KEYS (see
# nvidia_provider.py, which does the same). Claude's own prompt previously
# asked only for document_type/language/summary/turkish_explanation/
# important_dates/extracted_entities - none of sender_category,
# classified_document_type, deadline_raw_text, document_date,
# effective_date, payment_requested, objection_right_mentioned,
# action_summary, or multiple_deadlines_detected, meaning
# deadline_engine/priority_engine and entity_validation.validate_intelligence_signals
# never received any real data to act on for Claude - the provider
# config.py defaults to (DEFAULT_AI_PROVIDER = "claude"). Confirmed root
# cause of a real production misclassification (see the entity_validation
# module docstring / TODO history for the incident): a credit-card
# debt-insurance application form was labeled "Rechnung" and given a
# fabricated payment narrative, entirely inside the unconstrained
# document_type/turkish_explanation fields the old prompt allowed.
from .ollama_provider import _build_ollama_prompt as _build_claude_prompt

# ESTIMATE, not measured against the live Claude API (no ANTHROPIC_API_KEY
# was available in backend/.env at the time this was written to make a real
# call - see nvidia_provider.py's DEFAULT_MAX_TOKENS comment for how a real
# measurement is normally done and documented here). Set to match
# nvidia_provider.DEFAULT_MAX_TOKENS as the closest available reference
# point: NVIDIA's real measured completion length for this exact shared
# prompt (_build_ollama_prompt) was ~438-585 tokens on a realistic
# 500,000-character document, and 4000 was chosen there for ~7x headroom.
# Anthropic's tokenizer differs from NVIDIA's, so this number could be off
# in either direction - re-measure against a real Claude call once an API
# key is available, rather than trusting this estimate indefinitely.
DEFAULT_MAX_TOKENS = 4000


def _load_json_safe(text: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    stripped = text.strip()

    # Some models wrap the JSON in a markdown code fence despite being told
    # not to add extra text - strip it and retry before giving up.
    if stripped.startswith("```"):
        fenced = stripped
        first_newline = fenced.find("\n")
        if first_newline != -1:
            fenced = fenced[first_newline + 1 :]
        fenced = fenced.strip()
        if fenced.endswith("```"):
            fenced = fenced[: -3].strip()
        try:
            return json.loads(fenced)
        except json.JSONDecodeError:
            pass

    # Last resort: slice from the first "{" to the last "}" so stray leading
    # or trailing commentary around an otherwise well-formed JSON object
    # (e.g. "Here is the JSON:\n{...}\nLet me know if...") doesn't sink an
    # otherwise-valid response. Only trims outside the outermost braces -
    # never touches anything between them.
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None

    return None


class ClaudeProvider(BaseAIProvider):
    def __init__(self) -> None:
        api_key = os.getenv(ANTHROPIC_API_KEY_ENV)
        if not api_key:
            raise RuntimeError(
                "Claude provider is not configured because ANTHROPIC_API_KEY is missing."
            )

        self.client = Anthropic(api_key=api_key)
        self._model = env_or_default(ANTHROPIC_MODEL_ENV, DEFAULT_ANTHROPIC_MODEL)

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def model_name(self) -> str:
        return self._model

    def analyze_document(self, text: str) -> AIAnalysisResult:
        return self._send_request(_build_claude_prompt(text))

    def analyze_document_with_task(self, text: str, task: str) -> AIAnalysisResult:
        return self._send_request(_build_claude_prompt(text, task))

    def _send_request(self, prompt: str) -> AIAnalysisResult:
        try:
            response = self.client.messages.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=DEFAULT_MAX_TOKENS,
            )
        # RateLimitError and AuthenticationError are subclasses of APIStatusError,
        # so they must be caught before the general APIStatusError branch.
        except RateLimitError as exc:
            return AIAnalysisResult(
                error_message="Claude API rate limit exceeded. Please try again later.",
                raw_response={"error": str(exc)},
            )
        except AuthenticationError as exc:
            return AIAnalysisResult(
                error_message="Claude API authentication failed. Please check the server configuration.",
                raw_response={"error": str(exc)},
            )
        except APIConnectionError as exc:
            return AIAnalysisResult(
                error_message="Unable to connect to the Claude API. Please try again later.",
                raw_response={"error": str(exc)},
            )
        except APIStatusError as exc:
            return AIAnalysisResult(
                error_message=f"Claude API returned an error (status {exc.status_code}).",
                raw_response={"error": str(exc)},
            )
        except APIError as exc:
            return AIAnalysisResult(
                error_message="Claude API request failed.",
                raw_response={"error": str(exc)},
            )

        raw_text = ""
        content = getattr(response, "content", None)
        if isinstance(content, list):
            parts: List[str] = []
            for block in content:
                if isinstance(block, dict):
                    part = block.get("text")
                else:
                    part = getattr(block, "text", None)
                if isinstance(part, str):
                    parts.append(part)
            raw_text = "".join(parts)

        if not raw_text:
            raw_text = getattr(response, "completion", "")

        if not isinstance(raw_text, str):
            raw_text = str(raw_text)

        parsed = _load_json_safe(raw_text)
        if parsed is None:
            return AIAnalysisResult(
                error_message="Unable to parse Claude response as valid JSON.",
                raw_response={"raw_text": raw_text},
            )

        return AIAnalysisResult(
            document_type=parsed.get("document_type"),
            language=parsed.get("language"),
            summary=parsed.get("summary"),
            turkish_explanation=parsed.get("turkish_explanation"),
            important_dates=parsed.get("important_dates"),
            extracted_entities=parsed.get("extracted_entities"),
            raw_response=parsed,
        )
