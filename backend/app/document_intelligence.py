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

# Keys the LLM prompt is expected to populate inside raw_response (wired up
# in a later step). classified_document_type is deliberately NOT the
# existing "document_type" key - that one is DocumentAIAnalysis's free-form
# LLM label and must stay untouched; this is the separate, deterministic-
# taxonomy-facing value the priority engine reads.
_SENDER_CATEGORY_KEY = "sender_category"
_SENDER_INSTITUTION_KEY = "sender_institution"
_CLASSIFIED_DOCUMENT_TYPE_KEY = "classified_document_type"
_DEADLINE_RAW_TEXT_KEY = "deadline_raw_text"
_DOCUMENT_DATE_KEY = "document_date"
_REQUIRES_ACTION_KEY = "requires_action"
_PAYMENT_REQUESTED_KEY = "payment_requested"
_OBJECTION_RIGHT_KEY = "objection_right_mentioned"
_ACTION_SUMMARY_KEY = "action_summary"


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

        sender_category = _safe_str(payload.get(_SENDER_CATEGORY_KEY))
        sender_institution = _safe_str(payload.get(_SENDER_INSTITUTION_KEY))
        classified_document_type = _safe_str(payload.get(_CLASSIFIED_DOCUMENT_TYPE_KEY))
        deadline_raw_text = _safe_str(payload.get(_DEADLINE_RAW_TEXT_KEY))
        document_date = _safe_document_date(payload.get(_DOCUMENT_DATE_KEY))
        requires_action = _safe_bool(payload.get(_REQUIRES_ACTION_KEY))
        payment_requested = _safe_bool(payload.get(_PAYMENT_REQUESTED_KEY))
        objection_right_mentioned = _safe_bool(payload.get(_OBJECTION_RIGHT_KEY))
        action_summary = _safe_str(payload.get(_ACTION_SUMMARY_KEY))

        deadline = resolve_deadline(deadline_raw_text, document_date)
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
