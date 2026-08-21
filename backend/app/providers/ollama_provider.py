from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from ..ai_service import AIAnalysisResult, BaseAIProvider
from ..config import DEFAULT_OLLAMA_BASE_URL, OLLAMA_BASE_URL_ENV, OLLAMA_MODEL_ENV
from ..document_intelligence import (
    ACTION_SUMMARY_KEY,
    CLASSIFIED_DOCUMENT_TYPE_KEY,
    DEADLINE_RAW_TEXT_KEY,
    DOCUMENT_DATE_KEY,
    MULTIPLE_DEADLINES_DETECTED_KEY,
    OBJECTION_RIGHT_KEY,
    PAYMENT_REQUESTED_KEY,
    REQUIRES_ACTION_KEY,
    SENDER_CATEGORY_KEY,
    SENDER_INSTITUTION_KEY,
    SIGNAL_KEYS,
)

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

# 30s (the previous value) was observed in real testing to be too short for
# an 8B model (qwen3:8b) generating against the expanded Document
# Intelligence prompt on typical local hardware - the request was still
# mid-response when the socket timed out. 120s comfortably covers that
# while still failing fast on a genuinely unreachable/hung Ollama instance.
DEFAULT_REQUEST_TIMEOUT_SECONDS = 120


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

    signal_keys_list = ", ".join(SIGNAL_KEYS)
    return (
        "You are an AI assistant analyzing a German official or corporate document. "
        "Return a valid JSON object with the following keys: document_type, language, summary, "
        f"turkish_explanation, important_dates, extracted_entities, {signal_keys_list}. "
        "Use exactly these JSON key names, spelled exactly as given - a downstream deterministic "
        "system reads them by exact name and silently falls back to a low-confidence default for "
        "any key it does not find. "
        "important_dates must be a JSON array of strings. "
        "extracted_entities must be a JSON array of objects, each with a \"type\" and a \"value\" "
        "key. Extract every one of the following that is explicitly present in the text: policy "
        "or contract number, license plate, customer name, insurance company, ADAC membership "
        "number, address, and any other clearly identifiable named entity or reference number. "
        "Only include a value that literally appears in the text - never guess, infer, or "
        "invent one that is missing, and never use a descriptive term as an entity's value. "
        "For any numeric or code value (policy_or_contract_number, adac_membership_number, "
        "eVB_number, license_plate, and similar), copy every digit and character exactly as "
        "written in the text - never add, drop, reorder, correct, or normalize a single digit. "
        "If the exact value cannot be copied character-for-character from the text, omit that "
        "entity entirely. "
        "Do NOT create an eVB_number entity unless the text contains an actual number or code "
        "explicitly labeled as eVB (e.g. \"eVB-Nummer: 12345678\"). The words \"eVB\", "
        "\"Versicherungsbestätigung\", or \"Versicherungsbestätigungsnummer\" alone are not "
        "numbers - if no such number is present, omit eVB_number entirely. "
        "The value of turkish_explanation MUST be written in the TURKISH language, regardless of "
        "the document's own language. It must explain in Turkish what the document means, its "
        "important consequences (for example contracts being cancelled, confirmations being "
        "withdrawn, or new documents being required), and what the reader should do next. "
        "When the text uses these German insurance terms, use exactly this Turkish meaning: "
        "Kfz-Haftpflichtversicherung = zorunlu trafik sigortası, always. The word \"kasko\" "
        "must NEVER appear in turkish_explanation unless the source text literally contains "
        "Teilkasko (= kısmi kasko), Vollkasko (= tam kasko), or Kaskoversicherung (= kasko "
        "sigortası) - if none of those three words are in the text, do not write \"kasko\" "
        "anywhere, not even to say the contract is unrelated to kasko. If unsure which "
        "insurance product is meant, default to \"zorunlu trafik sigortası\". Widerruf = "
        "cayma/geri çekme; Versicherungsbestätigung / eVB = sigorta teyidi / elektronik "
        "sigorta teyidi. "
        f"{SENDER_CATEGORY_KEY} must be exactly one of these five words: Gericht, Behörde, "
        "Inkasso, Unternehmen, Privat - based on who sent the document (a court; a public "
        "authority such as Jobcenter, Finanzamt, or Ordnungsamt; a debt collection agency; a "
        "private company; or a private individual). Use null if unclear. "
        f"{SENDER_INSTITUTION_KEY} is the specific sender's name as written in the text (for "
        "example \"Jobcenter Berlin Mitte\"), or null if it cannot be identified. "
        f"{CLASSIFIED_DOCUMENT_TYPE_KEY} must be exactly one of: Mahnbescheid, Anhörung, "
        "Änderungsbescheid, Steuerbescheid, Bescheid, Mahnung, Rechnung, Information - or null if "
        "none clearly applies. Mahnbescheid is a formal, court-issued payment order (gerichtliches "
        "Mahnverfahren); Mahnung is only an informal payment reminder with no court involved - "
        "these are two different values, never use one when the text supports the other. Anhörung "
        "is a hearing notice giving the reader a chance to respond before a decision is finalized. "
        f"{DEADLINE_RAW_TEXT_KEY} is the exact phrase from the text stating a deadline or response "
        "period (for example \"bis zum 15.09.2026\" or \"innerhalb von 14 Tagen\"), copied "
        "verbatim - never invent, paraphrase, or compute one. Use null if no deadline is mentioned. "
        "If the text contains more than one distinct deadline/response-period phrase (for example "
        "a payment deadline AND a separate objection/appeal deadline), you MUST set "
        f"{MULTIPLE_DEADLINES_DETECTED_KEY} to true, and {DEADLINE_RAW_TEXT_KEY} must still be "
        "exactly one verbatim phrase, chosen by this fixed priority order: an objection/appeal "
        "deadline (Widerspruch, Einspruch, Rechtsbehelf) always outranks a payment deadline, which "
        "always outranks any other kind of deadline. If only one deadline/response-period phrase "
        f"is present, {MULTIPLE_DEADLINES_DETECTED_KEY} must be false. When "
        f"{MULTIPLE_DEADLINES_DETECTED_KEY} is true, {ACTION_SUMMARY_KEY} must explicitly say (in "
        "Turkish) that more than one deadline was found in the document and the reader should "
        "check it carefully themselves. "
        f"{DOCUMENT_DATE_KEY} is the date printed on the document itself (near a label such as "
        "\"Datum\" or \"Bescheid vom\"), formatted YYYY-MM-DD, only if that exact date is present "
        "in the text - never guess, compute, or use today's date. Use null if no such date is "
        "found. "
        f"{REQUIRES_ACTION_KEY}, {PAYMENT_REQUESTED_KEY}, {OBJECTION_RIGHT_KEY}, and "
        f"{MULTIPLE_DEADLINES_DETECTED_KEY} must each be the JSON boolean true or false, never a "
        f"string: {REQUIRES_ACTION_KEY} is true only if the reader must do something (respond, "
        f"pay, submit documents, appeal); {PAYMENT_REQUESTED_KEY} is true only if the text demands "
        f"a payment; {OBJECTION_RIGHT_KEY} is true only if the text mentions a right to object or "
        f"appeal (Widerspruch, Einspruch, Rechtsbehelf); {MULTIPLE_DEADLINES_DETECTED_KEY} is as "
        "defined above. "
        f"{ACTION_SUMMARY_KEY} is a short summary, at most about 20 words, IN TURKISH, of what the "
        f"reader needs to do. Use null if {REQUIRES_ACTION_KEY} is false. "
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
            with urllib.request.urlopen(
                request, timeout=DEFAULT_REQUEST_TIMEOUT_SECONDS
            ) as response:
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
        except TimeoutError as exc:
            # A timeout that occurs mid-response (e.g. inside
            # response.read()/getresponse(), after the connection itself
            # succeeded) surfaces as a bare TimeoutError here, not
            # urllib.error.URLError - observed in real testing with
            # qwen3:8b. Must be handled the same way as the network errors
            # above: a clean AIAnalysisResult, never an exception that
            # propagates out of the AI provider and crashes the caller.
            return AIAnalysisResult(
                error_message=f"Ollama request timed out: {exc}",
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
