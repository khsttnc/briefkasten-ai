from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from ..ai_service import AIAnalysisResult, BaseAIProvider
from ..config import DEFAULT_OLLAMA_BASE_URL, OLLAMA_BASE_URL_ENV, OLLAMA_MODEL_ENV

# Ollama's native /api/generate endpoint does not recognize a top-level
# "max_tokens" field (that's the OpenAI-compatible endpoint's parameter
# name) - it is silently ignored, leaving generation length uncapped. The
# real cap is "options.num_predict". Kept at the same value previously
# intended for max_tokens.
DEFAULT_NUM_PREDICT = 1200

# Ollama's runtime context window defaults to 2048 tokens regardless of a
# model's advertised maximum (llama3.2:3b supports far more, but Ollama
# doesn't use that automatically). The prompt here is a fixed instruction
# preamble (well under 300 tokens) plus a single document's OCR text, which
# for typical scanned letters/notices runs to a few hundred tokens. 4096
# comfortably covers prompt + document + the num_predict output budget above
# without requiring an unnecessarily large context on constrained hardware.
DEFAULT_NUM_CTX = 4096

# Small instruction-tuned models are prone to repetition loops and drifting
# off the requested JSON schema/language at Ollama's default temperature
# (0.8). Structured-extraction tasks like this one don't need creative
# sampling, so a low temperature makes output more deterministic and
# schema-compliant.
DEFAULT_TEMPERATURE = 0.2

# Ollama's default repeat_penalty (1.1) was not enough to reliably stop
# llama3.2:3b from getting stuck verbatim-repeating the same sentence inside
# turkish_explanation until it ran out its whole num_predict budget mid
# string - the direct cause of the "unable to parse" JSON failures seen in
# real testing. Across ~30 real runs against the actual uploaded document
# (batches of 6 at several repeat_penalty/temperature combinations),
# 1.1-1.15 consistently produced the most malformed JSON (roughly half or
# more of runs), while 1.25-1.3 was consistently the best of what was
# tried (roughly a third or fewer malformed) - not a full fix, but the
# best tradeoff found. Known tradeoff, also confirmed in real testing:
# forcing the model off a repeated phrase this way sometimes makes it
# drift into garbled/non-Turkish script for turkish_explanation instead of
# a fluent paraphrase - a llama3.2:3b Turkish-fluency limitation that no
# repeat_penalty/temperature combination tried here eliminated.
DEFAULT_REPEAT_PENALTY = 1.3


def _load_json_safe(text: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _parse_ollama_streaming_response(text: str) -> Optional[str]:
    lines = [line for line in text.splitlines() if line.strip()]
    response_chunks: List[str] = []
    for line in lines:
        parsed_line = _load_json_safe(line)
        if isinstance(parsed_line, dict) and "response" in parsed_line:
            response_chunks.append(str(parsed_line["response"]))

    if response_chunks:
        combined = "".join(response_chunks)
        if combined.strip():
            return combined

    return None


def _build_ollama_prompt(text: str, task: Optional[str] = None) -> str:
    if task == "classification":
        return (
            "You are an AI assistant analyzing a German official or corporate document. "
            "Return a valid JSON object with the keys: document_type and language. "
            "Do not include any additional text or explanation. "
            "If you are not sure, use null. "
            f"Text:\n{text}\n"
        )

    if task == "extraction":
        return (
            "You are an AI assistant analyzing a German official or corporate document. "
            "Return a valid JSON object with the keys: important_dates and extracted_entities. "
            "important_dates must be a JSON array of strings. "
            "extracted_entities must be a JSON array of objects containing name and type where available. "
            "If none are found, return empty lists. "
            "Do not include any additional text or explanation. "
            f"Text:\n{text}\n"
        )

    if task == "explanation":
        return (
            "You are an AI assistant analyzing a German official or corporate document. "
            "Return a valid JSON object with the keys: summary and turkish_explanation. "
            "The value of turkish_explanation MUST be written in the TURKISH language. "
            "It must explain in Turkish what the document means, its important consequences, "
            "and what the reader should do next. "
            "Do not include any additional text or explanation. "
            "If a value is uncertain, use null. "
            f"Text:\n{text}\n"
        )

    return (
        "You are an AI assistant analyzing a German official or corporate document. "
        "Return a valid JSON object with the following keys: document_type, language, summary, "
        "turkish_explanation, important_dates, extracted_entities. "
        "important_dates must be a JSON array of strings. "
        "extracted_entities must be a JSON array of objects. "
        "The value of turkish_explanation MUST be written in the TURKISH language, regardless of "
        "the document's own language. It must explain in Turkish what the document means, its "
        "important consequences (for example contracts being cancelled, confirmations being "
        "withdrawn, or new documents being required), and what the reader should do next. "
        "Do not include any additional text or explanation. "
        f"Text:\n{text}\n"
    )


class OllamaProvider(BaseAIProvider):
    def __init__(self) -> None:
        self.base_url = os.getenv(OLLAMA_BASE_URL_ENV, DEFAULT_OLLAMA_BASE_URL)
        self._model = os.getenv(OLLAMA_MODEL_ENV)
        if not self._model:
            raise RuntimeError(
                "Ollama provider is not configured because OLLAMA_MODEL is missing."
            )

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model

    def _send_request(self, prompt: str) -> AIAnalysisResult:
        request_body = json.dumps(
            {
                "model": self._model,
                "prompt": prompt,
                # Non-streaming: a single complete JSON response instead of
                # NDJSON chunks, so the result is either fully there or not.
                "stream": False,
                # Ollama-native structured output: constrains decoding to
                # valid JSON, which is the single biggest lever against the
                # malformed/truncated JSON observed from llama3.2:3b.
                "format": "json",
                "options": {
                    "num_predict": DEFAULT_NUM_PREDICT,
                    "num_ctx": DEFAULT_NUM_CTX,
                    "temperature": DEFAULT_TEMPERATURE,
                    "repeat_penalty": DEFAULT_REPEAT_PENALTY,
                },
            }
        ).encode("utf-8")

        url = f"{self.base_url.rstrip('/')}/api/generate"
        request = urllib.request.Request(
            url,
            data=request_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                response_text = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return AIAnalysisResult(
                error_message=f"Ollama HTTP error: {exc.code}",
                raw_response={"error": str(exc)},
            )
        except urllib.error.URLError as exc:
            return AIAnalysisResult(
                error_message=f"Ollama connection error: {exc.reason}",
                raw_response={"error": str(exc)},
            )

        parsed_response = _load_json_safe(response_text)
        if not isinstance(parsed_response, dict):
            # Ollama may emit streaming JSON lines, so attempt to reconstruct the final response.
            reconstructed = _parse_ollama_streaming_response(response_text)
            if reconstructed is None:
                return AIAnalysisResult(
                    error_message="Unable to parse Ollama response as valid JSON.",
                    raw_response={"raw_text": response_text},
                )
            parsed_response = _load_json_safe(reconstructed)
            if not isinstance(parsed_response, dict):
                return AIAnalysisResult(
                    error_message="Unable to parse Ollama response as valid JSON.",
                    raw_response={"raw_text": reconstructed},
                )

        raw_text = ""
        results = parsed_response.get("results")
        if isinstance(results, list) and results:
            first_result = results[0]
            if isinstance(first_result, dict):
                raw_text = first_result.get("text", "") or ""

        if not raw_text and isinstance(parsed_response.get("response"), str):
            raw_text = parsed_response.get("response")

        if not raw_text:
            raw_text = json.dumps(parsed_response)

        parsed = _load_json_safe(raw_text)
        if parsed is None:
            return AIAnalysisResult(
                error_message="Unable to parse Ollama result text as valid JSON.",
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

    def analyze_document(self, text: str) -> AIAnalysisResult:
        prompt = _build_ollama_prompt(text)
        return self._send_request(prompt)

    def analyze_document_with_task(self, text: str, task: str) -> AIAnalysisResult:
        prompt = _build_ollama_prompt(text, task)
        return self._send_request(prompt)
