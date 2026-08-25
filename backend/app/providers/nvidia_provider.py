from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from ..ai_service import AIAnalysisResult, BaseAIProvider
from ..config import (
    DEFAULT_NVIDIA_BASE_URL,
    DEFAULT_NVIDIA_MODEL,
    NVIDIA_API_KEY_ENV,
    NVIDIA_BASE_URL_ENV,
    NVIDIA_MODEL_ENV,
    env_or_default,
)
# Reused, not retyped: the Document Intelligence signal-key prompt is
# provider-agnostic text built from document_intelligence.SIGNAL_KEYS. Step 4
# already established (for Ollama) that retyping this prompt per-provider is
# exactly how the prompt and derive_intelligence_fields() drift out of sync.
from .ollama_provider import _build_ollama_prompt as _build_nvidia_prompt

# Measured, not guessed: a real test call against the live API with a
# realistic, information-dense 500,000-character document (the new
# MAX_ANALYSIS_TEXT_CHARS ceiling in document_processing.py - see that
# file's comment for the full context-limit investigation) used only
# ~570-585 completion tokens for the complete JSON response. 4000 keeps
# roughly 7x headroom over that measurement. The previous value (2000) was
# not clearly safe: a real test at 2,000,000 input characters (since
# reduced to well below the new ceiling) drove completion_tokens to
# exactly 2000 - i.e. the response was cut off by the cap, not because it
# was actually finished. See the finish_reason == "length" check in
# _send_request below, which now treats that condition as a hard failure
# instead of silently trying to parse a truncated JSON response.
DEFAULT_MAX_TOKENS = 4000
DEFAULT_TEMPERATURE = 0.2
DEFAULT_REQUEST_TIMEOUT_SECONDS = 120
# A frequency_penalty (tried as a mitigation, mirroring Ollama's
# DEFAULT_REPEAT_PENALTY) was evaluated against the repetition-loop failure
# below and made it worse in real testing: instead of repeating a sentence,
# the model started inventing fake "system requirements" as JSON comments to
# avoid repeating tokens, which broke JSON validity even more often (3/3 vs
# 1/3 failures in a small manual sample). Deliberately not applied.

# nvidia/nemotron-3-nano-30b-a3b is a reasoning-capable model: left at its
# default, it spends its entire completion budget on a chain-of-thought
# (returned as a separate reasoning_content field, or - if that budget runs
# out mid-thought - duplicated verbatim into content instead of the JSON
# answer, which is what a real end-to-end test against this model hit before
# this flag was added). Document Intelligence extraction is a deterministic
# formatting task, not a reasoning task, so thinking is disabled outright
# rather than sized around it.
DISABLE_THINKING_KWARGS = {"chat_template_kwargs": {"thinking": False}}


def _load_json_safe(text: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _strip_reasoning_blocks(text: str) -> str:
    # Reasoning-capable NIM models (e.g. Nemotron) can emit a <think>...</think>
    # chain-of-thought block ahead of the actual JSON answer even when not
    # explicitly requested. Strip it so JSON parsing sees only the answer.
    if "<think>" not in text:
        return text
    _, _, after = text.partition("</think>")
    return after if "</think>" in text else text


class NvidiaProvider(BaseAIProvider):
    def __init__(self) -> None:
        api_key = os.getenv(NVIDIA_API_KEY_ENV)
        if not api_key:
            raise RuntimeError(
                "NVIDIA provider is not configured because NVIDIA_API_KEY is missing."
            )

        self._api_key = api_key
        self._model = env_or_default(NVIDIA_MODEL_ENV, DEFAULT_NVIDIA_MODEL)
        self._base_url = env_or_default(NVIDIA_BASE_URL_ENV, DEFAULT_NVIDIA_BASE_URL)

    @property
    def provider_name(self) -> str:
        return "nvidia"

    @property
    def model_name(self) -> str:
        return self._model

    def analyze_document(self, text: str) -> AIAnalysisResult:
        prompt = _build_nvidia_prompt(text)
        return self._send_request(prompt)

    def analyze_document_with_task(self, text: str, task: str) -> AIAnalysisResult:
        prompt = _build_nvidia_prompt(text, task)
        return self._send_request(prompt)

    def _send_request(self, prompt: str) -> AIAnalysisResult:
        request_body = json.dumps(
            {
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": DEFAULT_MAX_TOKENS,
                "temperature": DEFAULT_TEMPERATURE,
                **DISABLE_THINKING_KWARGS,
            }
        ).encode("utf-8")

        url = f"{self._base_url.rstrip('/')}/chat/completions"
        request = urllib.request.Request(
            url,
            data=request_body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request, timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS
            ) as response:
                response_text = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                return AIAnalysisResult(
                    error_message="NVIDIA API authentication failed. Please check the server configuration.",
                    raw_response={"error": str(exc)},
                )
            if exc.code == 429:
                return AIAnalysisResult(
                    error_message="NVIDIA API rate limit exceeded. Please try again later.",
                    raw_response={"error": str(exc)},
                )
            return AIAnalysisResult(
                error_message=f"NVIDIA API returned an error (status {exc.code}).",
                raw_response={"error": str(exc)},
            )
        except urllib.error.URLError as exc:
            return AIAnalysisResult(
                error_message=f"Unable to connect to the NVIDIA API: {exc.reason}",
                raw_response={"error": str(exc)},
            )
        except TimeoutError as exc:
            return AIAnalysisResult(
                error_message=f"NVIDIA API request timed out: {exc}",
                raw_response={"error": str(exc)},
            )

        parsed_response = _load_json_safe(response_text)
        if not isinstance(parsed_response, dict):
            return AIAnalysisResult(
                error_message="Unable to parse NVIDIA response as valid JSON.",
                raw_response={"raw_text": response_text},
            )

        raw_text = ""
        finish_reason = None
        choices = parsed_response.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                finish_reason = first_choice.get("finish_reason")
                message = first_choice.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        raw_text = content

        # Fail closed on a response cut off by the token limit: an
        # incomplete JSON object may fail to parse (already handled below)
        # but could also, by coincidence, close its braces/strings exactly
        # where generation was cut and parse as valid-but-incomplete JSON -
        # silently accepting that would mean acting on content the model
        # never actually finished producing. Checked before any attempt to
        # use raw_text, regardless of whether it happens to parse.
        if finish_reason == "length":
            return AIAnalysisResult(
                error_message=(
                    "NVIDIA response was cut off before completing (hit the "
                    "token limit) - the analysis is incomplete and was not used."
                ),
                raw_response=parsed_response,
            )

        if not raw_text:
            return AIAnalysisResult(
                error_message="NVIDIA response did not contain any content.",
                raw_response=parsed_response,
            )

        raw_text = _strip_reasoning_blocks(raw_text)

        parsed = _load_json_safe(raw_text)
        if parsed is None:
            return AIAnalysisResult(
                error_message="Unable to parse NVIDIA response as valid JSON.",
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
