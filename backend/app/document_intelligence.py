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
    REQUIRES_ACTION_KEY,
    PAYMENT_REQUESTED_KEY,
    OBJECTION_RIGHT_KEY,
    ACTION_SUMMARY_KEY,
    MULTIPLE_DEADLINES_DETECTED_KEY,
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
    }


def derive_intelligence_fields(raw_response: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Returns a dict of Document column values, ready to assign via setattr.

    Always returns a complete, safe result: a missing AI analysis
    (raw_response is None/empty/not a dict), or signal keys of the wrong
    type, degrade to deadline_type='none'/'exact' and an unfloored 'low'
    priority_level - never an exception, so a failed or incomplete LLM
    analysis can never take the analyze pipeline down with it.
    """
    try:
        payload = raw_response if isinstance(raw_response, dict) else {}

        sender_category = _safe_str(payload.get(SENDER_CATEGORY_KEY))
        sender_institution = _safe_str(payload.get(SENDER_INSTITUTION_KEY))
        classified_document_type = _safe_str(payload.get(CLASSIFIED_DOCUMENT_TYPE_KEY))
        deadline_raw_text = _safe_str(payload.get(DEADLINE_RAW_TEXT_KEY))
        document_date = _safe_document_date(payload.get(DOCUMENT_DATE_KEY))
        requires_action = _safe_bool(payload.get(REQUIRES_ACTION_KEY))
        payment_requested = _safe_bool(payload.get(PAYMENT_REQUESTED_KEY))
        objection_right_mentioned = _safe_bool(payload.get(OBJECTION_RIGHT_KEY))
        action_summary = _safe_str(payload.get(ACTION_SUMMARY_KEY))
        multiple_deadlines_detected = _safe_bool(payload.get(MULTIPLE_DEADLINES_DETECTED_KEY))

        deadline = resolve_deadline(
            deadline_raw_text,
            document_date,
            multiple_deadlines_detected=multiple_deadlines_detected,
        )
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
        }
    except Exception:
        # Belt-and-braces on top of the engines' own fail-closed behavior:
        # whatever went wrong (unexpected raw_response shape, a future
        # engine change, ...), fall back to the same safe defaults the
        # engines produce for empty input rather than propagate.
        return _safe_defaults()
