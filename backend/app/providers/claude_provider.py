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
from ..config import ANTHROPIC_API_KEY_ENV, ANTHROPIC_MODEL_ENV, DEFAULT_ANTHROPIC_MODEL


def _load_json_safe(text: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _build_claude_prompt(text: str) -> str:
    return (
        "You are an AI assistant tasked with analyzing German official or corporate documents. "
        "Return a JSON object with the following keys: document_type, language, summary, "
        "turkish_explanation, important_dates, extracted_entities. "
        "The response must be valid JSON only, without extra commentary. "
        "Do not hallucinate. If a detail is uncertain, state that clearly in the output. "
        "Analyze the document and provide the output in Turkish for the explanation fields. "
        "Important entities should include people, companies, reference numbers, file numbers, amounts, and other relevant identifiers. "
        "Document type should describe what the document is (invoice, letter, contract, notice, application, etc.). "
        "If the input text contains German content, base the language detection on the document itself. "
        "Text:\n" + text + "\n\n"
    )


class ClaudeProvider(BaseAIProvider):
    def __init__(self) -> None:
        api_key = os.getenv(ANTHROPIC_API_KEY_ENV)
        if not api_key:
            raise RuntimeError(
                "Claude provider is not configured because ANTHROPIC_API_KEY is missing."
            )

        self.client = Anthropic(api_key=api_key)
        self._model = os.getenv(ANTHROPIC_MODEL_ENV, DEFAULT_ANTHROPIC_MODEL)

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def model_name(self) -> str:
        return self._model

    def analyze_document(self, text: str) -> AIAnalysisResult:
        prompt = _build_claude_prompt(text)
        try:
            response = self.client.messages.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1200,
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

    def analyze_document_with_task(self, text: str, task: str) -> AIAnalysisResult:
        return self.analyze_document(text)
