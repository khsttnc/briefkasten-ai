"""Post-processing step that turns raw AI-provider signal output into the
Document Intelligence fields added in the schema migration.

This is the boundary between "LLM produced *something*" and "the
deterministic engines decide the final classification" (deadline_engine.py,
priority_engine.py). Because the LLM prompt work (adding these signal keys
to raw_response) lands in a later step, and because an AI-provider call can
itself fail, `derive_intelligence_fields` is written to accept a missing,
empty, or malformed raw_response and still return a complete, safe result -
it must never raise into the analyze pipeline that calls it.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Any, Dict, Optional

from .deadline_engine import resolve_deadline
from .priority_engine import PriorityInput, classify_priority

# Keys the LLM prompt is expected to populate inside raw_response.
# classified_document_type is deliberately NOT the existing "document_type"
# key - that one is DocumentAIAnalysis's free-form LLM label and must stay
# untouched; this is the separate, deterministic-taxonomy-facing value the
# priority engine reads.
#
# Public (no leading underscore) on purpose: a provider's prompt-building
# code (see providers/ollama_provider.py) imports these instead of
# re-typing the literal strings, so a rename here can't silently drift out
# of sync with what the LLM is actually asked to produce - a key-name typo
# in only one of the two places would otherwise still pass every unit test
# here while always producing the safe low/unknown fallback in real use.
SENDER_CATEGORY_KEY = "sender_category"
SENDER_INSTITUTION_KEY = "sender_institution"
CLASSIFIED_DOCUMENT_TYPE_KEY = "classified_document_type"
DEADLINE_RAW_TEXT_KEY = "deadline_raw_text"
DOCUMENT_DATE_KEY = "document_date"
# The date something IN the document itself takes effect (a Kündigung's
# employment end date, a contract change's effective date) - informational
# only, never an action deadline. Deliberately a separate key from
# deadline_raw_text: a real Kündigung had its own end date incorrectly at
# risk of being read as "the deadline", when the actual actionable deadline
# was an unrelated statutory reporting duty triggered BY the termination
# (see EFFECTIVE_DATE_KEY's prompt instructions in ollama_provider.py).
EFFECTIVE_DATE_KEY = "effective_date"
REQUIRES_ACTION_KEY = "requires_action"
PAYMENT_REQUESTED_KEY = "payment_requested"
OBJECTION_RIGHT_KEY = "objection_right_mentioned"
ACTION_SUMMARY_KEY = "action_summary"
# True when the source text contains more than one distinct deadline/
# response-period phrase (e.g. a payment deadline and a separate
# Widerspruch/appeal deadline). deadline_raw_text is still expected to be
# the single phrase with the heavier legal consequence in that case (see
# the Ollama prompt's ordering rule), but resolve_deadline() uses this flag
# to downgrade the result to unknown_needs_review regardless - which
# phrase is genuinely "the" deadline is inherently ambiguous when more
# than one is present, even if the chosen phrase itself parses cleanly.
MULTIPLE_DEADLINES_DETECTED_KEY = "multiple_deadlines_detected"

SIGNAL_KEYS = (
    SENDER_CATEGORY_KEY,
    SENDER_INSTITUTION_KEY,
    CLASSIFIED_DOCUMENT_TYPE_KEY,
    DEADLINE_RAW_TEXT_KEY,
    DOCUMENT_DATE_KEY,
    EFFECTIVE_DATE_KEY,
    REQUIRES_ACTION_KEY,
    PAYMENT_REQUESTED_KEY,
    OBJECTION_RIGHT_KEY,
    ACTION_SUMMARY_KEY,
    MULTIPLE_DEADLINES_DETECTED_KEY,
)

# The single language every LLM-generated free-text field (summary,
# turkish_explanation, action_summary) must be written in, regardless of
# the source document's own language. Centralized here instead of
# hardcoded per provider prompt string (see providers/ollama_provider.py
# and providers/claude_provider.py, which both import this) so that real
# multi-language support later - letting a user pick Arabic/Russian/
# English/etc - is a matter of parameterizing this one value instead of
# hunting down every prompt across providers. Not wired to a user
# preference yet; see TODO.md.
OUTPUT_LANGUAGE_NAME = "Turkish"

# Canned, non-LLM-authored action_summary for when multiple_deadlines_detected
# is true - overrides whatever the LLM wrote in that case. Asking the LLM to
# author this fixed-meaning sentence "in {OUTPUT_LANGUAGE_NAME}" was
# unreliable in real production use (nemotron produced literal, identical
# German text here despite the instruction), and the message never varies
# per document anyway - a deterministic string removes the LLM-compliance
# risk entirely instead of hoping it listens next time. Keyed by
# OUTPUT_LANGUAGE_NAME so it moves in lockstep with the rest of the output-
# language configuration; falls back to the Turkish text for a language not
# yet in this dict (only Turkish is supported today, see TODO.md).
_MULTIPLE_DEADLINES_ACTION_SUMMARY_BY_LANGUAGE = {
    "Turkish": (
        "Belgede birden fazla süre/tarih tespit edildi; lütfen tüm tarihleri "
        "dikkatlice kontrol edin."
    ),
}


# Raw "language" values actually observed coming back from the LLM for the
# same kind of German document, across providers/models/re-analyses:
# "German", "Deutsch", "de". The app only ever processes German documents
# (see CLAUDE.md), so this field is never really in doubt - only its
# spelling is inconsistent. Normalized to a single Turkish display label so
# the UI doesn't flicker between spellings depending on which provider/model
# happened to answer.
_GERMAN_LANGUAGE_LABELS = {"german", "deutsch", "de", "deu", "germany"}
DISPLAY_LANGUAGE_GERMAN = "Almanca"


def normalize_language_label(value: Optional[str]) -> Optional[str]:
    """Maps a raw LLM-reported document language to its Turkish display label.

    Whatever the LLM returns for a recognized German synonym (any casing)
    becomes "Almanca". An unrecognized value is passed through unchanged
    rather than guessed at - this only fixes known inconsistency, it does
    not invent a translation for a language never seen in practice.
    """
    if not isinstance(value, str) or not value.strip():
        return value
    if value.strip().lower() in _GERMAN_LANGUAGE_LABELS:
        return DISPLAY_LANGUAGE_GERMAN
    return value


def _multiple_deadlines_action_summary() -> str:
    return _MULTIPLE_DEADLINES_ACTION_SUMMARY_BY_LANGUAGE.get(
        OUTPUT_LANGUAGE_NAME,
        _MULTIPLE_DEADLINES_ACTION_SUMMARY_BY_LANGUAGE["Turkish"],
    )


# Appended (not a replacement) whenever
# document_processing.detect_possible_multiple_documents flagged the source
# text before analysis - distinct from the multiple-deadlines override
# above, which is the LLM's own within-one-document judgment. This one
# fires from the deterministic pre-check regardless of what the LLM
# concluded, so the reader gets a concrete warning even on a model that
# ignored the prompt's multi-document hint entirely (see
# providers/ollama_provider.py's possible_multiple_documents parameter).
_MULTIPLE_DOCUMENTS_ACTION_SUMMARY_BY_LANGUAGE = {
    "Turkish": (
        "Not: Bu belgede birden fazla ayrı belge/işlem olabilir (örn. "
        "birkaç farklı ekstre veya mektup); lütfen her birini ayrı ayrı "
        "kontrol edin."
    ),
}


def _multiple_documents_action_summary() -> str:
    return _MULTIPLE_DOCUMENTS_ACTION_SUMMARY_BY_LANGUAGE.get(
        OUTPUT_LANGUAGE_NAME,
        _MULTIPLE_DOCUMENTS_ACTION_SUMMARY_BY_LANGUAGE["Turkish"],
    )


# Appended (not a replacement, unlike the multiple-deadlines override above)
# to action_summary whenever the source text was too long to send to the AI
# provider in full (see document_processing.MAX_ANALYSIS_TEXT_CHARS) - the
# omitted middle could contain a deadline the LLM never even saw, so the
# reader is told to check manually regardless of what was extracted.
_TRUNCATION_ACTION_SUMMARY_NOTE_BY_LANGUAGE = {
    "Turkish": (
        "Not: Bu belge çok uzun olduğu için sadece bir kısmı analiz edildi; "
        "atlanan bölümde başka bir süre/tarih olabilir, lütfen belgeyi elle "
        "de kontrol edin."
    ),
}


def _truncation_action_summary_note() -> str:
    return _TRUNCATION_ACTION_SUMMARY_NOTE_BY_LANGUAGE.get(
        OUTPUT_LANGUAGE_NAME,
        _TRUNCATION_ACTION_SUMMARY_NOTE_BY_LANGUAGE["Turkish"],
    )


def _safe_str(value: Any) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _safe_bool(value: Any) -> bool:
    return value is True


def _safe_document_date(value: Any) -> Optional[date]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _safe_defaults() -> Dict[str, Any]:
    # Hardcoded, not derived by calling resolve_deadline/classify_priority:
    # this is the fallback for when those very functions are the thing that
    # broke, so it must not depend on them working.
    return {
        "sender_category": None,
        "sender_institution": None,
        "document_type": None,
        "priority_level": "low",
        "priority_reasoning": "Keine erschwerenden Signale erkannt -> Score 0 -> 'low'",
        "deadline_raw_text": None,
        "deadline_type": "none",
        "deadline_estimated_date": None,
        "deadline_certainty": "exact",
        "requires_action": False,
        "action_summary": None,
        "effective_date": None,
    }


def derive_intelligence_fields(
    raw_response: Optional[Dict[str, Any]],
    *,
    text_truncated: bool = False,
    possible_multiple_documents: bool = False,
) -> Dict[str, Any]:
    """Returns a dict of Document column values, ready to assign via setattr.

    Always returns a complete, safe result: a missing AI analysis
    (raw_response is None/empty/not a dict), or signal keys of the wrong
    type, degrade to deadline_type='none'/'exact' and an unfloored 'low'
    priority_level - never an exception, so a failed or incomplete LLM
    analysis can never take the analyze pipeline down with it.

    text_truncated: True when the source text exceeded
    document_processing.MAX_ANALYSIS_TEXT_CHARS and was cut before being
    sent to the AI provider (see document_processing._truncate_for_analysis).
    A deadline could be sitting in the omitted middle that the LLM never
    saw - same fail-closed spirit as an unparseable deadline phrase, this
    caps deadline_certainty at "estimated" (never "exact") and appends a
    review note to action_summary, regardless of what the LLM returned.

    possible_multiple_documents: True when
    document_processing.detect_possible_multiple_documents flagged the
    source text before it was ever sent to the AI provider. Appends a
    warning note to action_summary unconditionally - independent of
    whatever the LLM itself concluded about multiple_deadlines_detected -
    so the reader is told even if the model ignored the prompt's hint.
    """
    try:
        payload = raw_response if isinstance(raw_response, dict) else {}

        sender_category = _safe_str(payload.get(SENDER_CATEGORY_KEY))
        sender_institution = _safe_str(payload.get(SENDER_INSTITUTION_KEY))
        classified_document_type = _safe_str(payload.get(CLASSIFIED_DOCUMENT_TYPE_KEY))
        deadline_raw_text = _safe_str(payload.get(DEADLINE_RAW_TEXT_KEY))
        document_date = _safe_document_date(payload.get(DOCUMENT_DATE_KEY))
        effective_date = _safe_document_date(payload.get(EFFECTIVE_DATE_KEY))
        requires_action = _safe_bool(payload.get(REQUIRES_ACTION_KEY))
        payment_requested = _safe_bool(payload.get(PAYMENT_REQUESTED_KEY))
        objection_right_mentioned = _safe_bool(payload.get(OBJECTION_RIGHT_KEY))
        action_summary = _safe_str(payload.get(ACTION_SUMMARY_KEY))
        multiple_deadlines_detected = _safe_bool(payload.get(MULTIPLE_DEADLINES_DETECTED_KEY))
        if multiple_deadlines_detected:
            # Deterministic override, not the LLM's own action_summary - see
            # _multiple_deadlines_action_summary()'s docstring for why.
            action_summary = _multiple_deadlines_action_summary()

        deadline = resolve_deadline(
            deadline_raw_text,
            document_date,
            multiple_deadlines_detected=multiple_deadlines_detected,
        )
        if text_truncated and deadline.deadline_certainty == "exact":
            deadline = replace(deadline, deadline_certainty="estimated")
        if possible_multiple_documents:
            note = _multiple_documents_action_summary()
            action_summary = f"{action_summary} {note}" if action_summary else note
        if text_truncated:
            note = _truncation_action_summary_note()
            action_summary = f"{action_summary} {note}" if action_summary else note

        priority = classify_priority(
            PriorityInput(
                sender_category=sender_category,
                document_type=classified_document_type,
                deadline_type=deadline.deadline_type,
                deadline_certainty=deadline.deadline_certainty,
                payment_requested=payment_requested,
                objection_right_mentioned=objection_right_mentioned,
            )
        )

        return {
            "sender_category": sender_category,
            "sender_institution": sender_institution,
            "document_type": classified_document_type,
            "priority_level": priority.priority_level,
            "priority_reasoning": priority.priority_reasoning,
            "deadline_raw_text": deadline.deadline_raw_text,
            "deadline_type": deadline.deadline_type,
            "deadline_estimated_date": deadline.deadline_estimated_date,
            "deadline_certainty": deadline.deadline_certainty,
            "requires_action": requires_action,
            "action_summary": action_summary,
            "effective_date": effective_date,
        }
    except Exception:
        # Belt-and-braces on top of the engines' own fail-closed behavior:
        # whatever went wrong (unexpected raw_response shape, a future
        # engine change, ...), fall back to the same safe defaults the
        # engines produce for empty input rather than propagate.
        return _safe_defaults()
