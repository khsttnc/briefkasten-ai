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
#
# Re-measured 2026-08-25 after adding the explicit "at most 15 entities" /
# "at most 5 sentences" (turkish_explanation) / "at most 2 sentences"
# (summary) prompt caps: a fresh real test call against the live API, same
# 500,000-character document shape, used only 438 completion tokens with
# finish_reason "stop" (not cut off) - lower than the original 570-585
# measurement, as expected from bounding the two free-text fields. 4000
# still leaves roughly 9x headroom over this measurement, so the value did
# not need to move; only the margin got safer.
DEFAULT_MAX_TOKENS = 4000
# Measured, not guessed, against the live API (2026-08-26, 13 real calls
# total against the same fixed multi-signal document - a Jobcenter
# Änderungsbescheid with a 14-day document-submission deadline and a
# separate 1-month Widerspruch deadline - see the scratchpad measurement
# script referenced in TODO.md): at the previous DEFAULT_TEMPERATURE=0.2
# with no top_p set, 5 repeated calls against the identical prompt produced
# 5 different turkish_explanation values (avg pairwise similarity 0.28) and
# even a dropped classified_document_type (null on one call,
# "Änderungsbescheid" on the other four) - the exact "same document,
# different answer each time" behavior reported in production.
# temperature=0, top_p=0.1 fixed the SHORT categorical field
# (classified_document_type: 5/5 identical across 8 further calls at these
# settings) but did NOT fix the LONG free-text fields (summary/
# turkish_explanation/action_summary): still 5/5 unique wordings, avg
# similarity 0.22 - no better than before. Adding a fixed `seed` on top
# (tested separately, 3 more calls) made no further difference either
# (still 3/3 unique, avg similarity 0.18). Conclusion: this API/model
# combination does not give deterministic long-form generation regardless
# of temperature/top_p/seed - likely inherent to the serving stack
# (nemotron-3-nano-30b-a3b is a mixture-of-experts model; MoE routing and
# batched-inference floating-point non-associativity are common causes of
# server-side non-determinism even at temperature=0). Kept temperature=0/
# top_p=0.1 anyway since they measurably help the structured fields the
# deterministic engines (deadline_engine/priority_engine) actually act on,
# with no observed downside (JSON parse success stayed 13/13 across every
# setting tested - the ~20% JSON-failure rate noted in TODO.md was not
# reproduced in this sample, which is too small to conclude it improved).
# The free-text consistency problem itself remains open - see TODO.md.
DEFAULT_TEMPERATURE = 0.0
DEFAULT_TOP_P = 0.1
DEFAULT_REQUEST_TIMEOUT_SECONDS = 120
# A frequency_penalty (tried as a mitigation, mirroring Ollama's
# DEFAULT_REPEAT_PENALTY) was evaluated against the repetition-loop failure
# below and made it worse in real testing: instead of repeating a sentence,
# the model started inventing fake "system requirements" as JSON comments to
# avoid repeating tokens, which broke JSON validity even more often (3/3 vs
# 1/3 failures in a small manual sample). Deliberately not applied.

# nvidia/nemotron-3-nano-30b-a3b (the previous default model - see
# config.DEFAULT_NVIDIA_MODEL) is a reasoning-capable model: left at its
# default, it spends its entire completion budget on a chain-of-thought
# (returned as a separate reasoning_content field, or - if that budget runs
# out mid-thought - duplicated verbatim into content instead of the JSON
# answer, which is what a real end-to-end test against this model hit before
# this flag was added). Document Intelligence extraction is a deterministic
# formatting task, not a reasoning task, so thinking is disabled outright
# rather than sized around it.
#
# Nemotron-specific: this is a NIM chat-template toggle, not a general
# OpenAI-compatible parameter - initially applied unconditionally to every
# model on the (false) assumption it would also work for the current
# default, openai/gpt-oss-120b. It doesn't: gpt-oss models use OpenAI's
# own "Harmony" response format and the separate `reasoning_effort`
# parameter (see REASONING_EFFORT_KWARGS below) - `chat_template_kwargs`
# is silently ignored for them (confirmed: NVIDIA's own docs/forum posts
# for gpt-oss-120b only document `reasoning_effort`; a real test call
# sending this kwarg to gpt-oss-120b returned 200 OK with no observable
# effect on output length or structure). Kept nemotron-only rather than
# removed outright, in case NVIDIA_MODEL is ever set back to it.
DISABLE_THINKING_KWARGS = {"chat_template_kwargs": {"thinking": False}}

# gpt-oss models (the current default) expose reasoning depth via this
# OpenAI-standard parameter instead - "minimal" is not accepted for this
# model (real test: HTTP 400), so "low" is the lowest working value.
# Document Intelligence extraction doesn't need deep reasoning, and lower
# effort measurably reduces reasoning token spend: a real test call with
# no reasoning_effort set (the previous, accidental default) produced
# 4747 characters of reasoning_content before ever reaching the JSON
# answer; the same prompt at reasoning_effort=low produced only 1790.
# Response content stayed clean, valid JSON in every real call made
# against this model during this investigation (17 calls total, 0
# failures, 0 stray Harmony control tokens - e.g. <|return|>, <|channel|> -
# observed in content) - community reports (NVIDIA forums) describe such
# leakage as a real, unresolved issue for this model on this API, just
# not reproduced in this sample. message.get("reasoning_content") is never
# read below regardless, so even a very long reasoning trace can't affect
# what this provider acts on - only a leak INTO the content field itself
# would matter, which is what was tested for and not observed.
REASONING_EFFORT_KWARGS = {"reasoning_effort": "low"}


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


# Measured, not guessed, against the live API (2026-08-27, 4 real calls
# against the same 15,000-character multi-signal document): nemotron
# intermittently locks into a token-repetition loop and burns the entire
# max_tokens budget on it - 2 of 4 calls repeated a single word (e.g.
# "artig") 1983 times consecutively, always paired with
# finish_reason == "length". The other 2 calls succeeded normally with a
# longest consecutive-repeat run of 1 - i.e. real answers never come close
# to this threshold, so 10 is a wide, false-positive-free margin rather
# than a value needing per-document tuning. Retried once on detection (see
# NvidiaProvider._send_request) rather than failing immediately, since the
# failure was observed to be transient (the very next call on the same
# input succeeded).
REPETITION_LOOP_MIN_RUN = 10


def _has_repetition_loop(text: str, min_run: int = REPETITION_LOOP_MIN_RUN) -> bool:
    words = text.split()
    run = 1
    for previous, current in zip(words, words[1:]):
        if current == previous:
            run += 1
            if run >= min_run:
                return True
        else:
            run = 1
    return False


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
        outcome = self._call_api(prompt)
        if isinstance(outcome, AIAnalysisResult):
            return outcome

        finish_reason, raw_text, parsed_response = outcome
        if finish_reason == "length" or _has_repetition_loop(raw_text):
            # Transient failure (see REPETITION_LOOP_MIN_RUN's comment): the
            # same request was observed to succeed on a very next call
            # against the same input, so one retry is attempted before
            # surfacing an error to the user.
            outcome = self._call_api(prompt)
            if isinstance(outcome, AIAnalysisResult):
                return outcome
            finish_reason, raw_text, parsed_response = outcome
            if finish_reason == "length" or _has_repetition_loop(raw_text):
                return AIAnalysisResult(
                    error_message=(
                        "NVIDIA response was cut off before completing (hit the "
                        "token limit, possibly stuck in a repetition loop) even "
                        "after one retry - the analysis is incomplete and was "
                        "not used."
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

    def _call_api(
        self, prompt: str
    ) -> "AIAnalysisResult | tuple[Optional[str], str, Dict[str, Any]]":
        """One HTTP round-trip. Returns a terminal AIAnalysisResult for a
        network/HTTP/envelope-level failure (never retried), or
        (finish_reason, raw_text, parsed_response) for a completed HTTP
        response whose content is still subject to the caller's
        length/repetition-loop retry decision.
        """
        payload: Dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": DEFAULT_MAX_TOKENS,
            "temperature": DEFAULT_TEMPERATURE,
            "top_p": DEFAULT_TOP_P,
        }
        # Model-specific reasoning-control parameter - the two model
        # families use different, non-interchangeable mechanisms (see the
        # comments on DISABLE_THINKING_KWARGS/REASONING_EFFORT_KWARGS
        # above), so only the one that actually matches self._model is
        # sent rather than both unconditionally.
        if "nemotron" in self._model:
            payload.update(DISABLE_THINKING_KWARGS)
        elif "gpt-oss" in self._model:
            payload.update(REASONING_EFFORT_KWARGS)

        request_body = json.dumps(payload).encode("utf-8")

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

        return finish_reason, raw_text, parsed_response
