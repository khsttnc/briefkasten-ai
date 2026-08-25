"""Deterministic priority classification.

The LLM only supplies structured signals (sender_category, document_type,
whether a payment is demanded, whether an objection/appeal right is
mentioned); it never assigns the final priority_level itself. Scoring and
the "Anhörung/Mahnbescheid is always at least high" floor rule live here,
in code, so the same inputs always produce the same output.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

PriorityLevel = str  # "critical" | "high" | "normal" | "low"

# Public: severity order, lowest first. services.py (the /documents and
# /documents/summary endpoints) imports this to rank documents and to
# enumerate the valid ?priority= filter values, instead of duplicating the
# level list or its ordering.
LEVEL_ORDER = ["low", "normal", "high", "critical"]

# document_type values that are always important regardless of the LLM's
# own confidence/score: a hearing notice (Anhörung) has a statutory
# response deadline before an adverse decision is finalized, and a
# Mahnbescheid is a formal court order that can escalate to enforcement
# (Vollstreckungsbescheid) if ignored. NOT the same as a Mahnung (an
# informal, non-court payment reminder) - do not conflate the two.
_ALWAYS_AT_LEAST_HIGH = {"Anhörung", "Mahnbescheid"}

# Coarse sender weight: courts/authorities/collection agencies carry more
# legal consequence than a private sender or an ordinary company.
_SENDER_CATEGORY_POINTS = {
    "Gericht": 3,
    "Behörde": 2,
    "Inkasso": 2,
    "Unternehmen": 1,
    "Privat": 0,
}

_DOCUMENT_TYPE_POINTS = {
    "Mahnbescheid": 3,
    "Anhörung": 3,
    "Änderungsbescheid": 2,
    "Steuerbescheid": 2,
    "Bescheid": 2,
    # Same weight class as Bescheid: a termination (employment, tenancy,
    # contract) is a consequential formal notice, but - unlike Anhörung/
    # Mahnbescheid - not inherently time-critical on its own (a landlord's
    # Kündigung carries none of the urgency an employment Kündigung's SGB
    # III reporting duty does), so it is not floored to "high" here; a real
    # deadline extracted alongside it already pushes the score up on its
    # own merit.
    "Kündigung": 2,
    "Mahnung": 1,
    "Rechnung": 1,
    "Information": 0,
}

_PAYMENT_REQUESTED_POINTS = 1
_OBJECTION_RIGHT_POINTS = 1
_DEADLINE_TYPE_POINTS = {"absolute": 2, "relative": 1, "none": 0}
_UNRESOLVED_DEADLINE_POINTS = 1  # deadline exists but certainty is unknown

_CRITICAL_THRESHOLD = 7
_HIGH_THRESHOLD = 4
_NORMAL_THRESHOLD = 2


@dataclass
class PriorityInput:
    sender_category: Optional[str] = None
    document_type: Optional[str] = None
    deadline_type: Optional[str] = None  # "absolute" | "relative" | "none" | None
    deadline_certainty: Optional[str] = None  # "exact" | "estimated" | "unknown_needs_review" | None
    payment_requested: bool = False
    objection_right_mentioned: bool = False


@dataclass
class PriorityResult:
    priority_level: PriorityLevel
    priority_reasoning: str


def _level_from_score(score: int) -> PriorityLevel:
    if score >= _CRITICAL_THRESHOLD:
        return "critical"
    if score >= _HIGH_THRESHOLD:
        return "high"
    if score >= _NORMAL_THRESHOLD:
        return "normal"
    return "low"


def _max_level(a: PriorityLevel, b: PriorityLevel) -> PriorityLevel:
    return a if LEVEL_ORDER.index(a) >= LEVEL_ORDER.index(b) else b


def classify_priority(data: PriorityInput) -> PriorityResult:
    score = 0
    reasons: list[str] = []

    sender_points = _SENDER_CATEGORY_POINTS.get(data.sender_category or "", 0)
    if sender_points:
        score += sender_points
        reasons.append(f"Absender-Kategorie '{data.sender_category}' (+{sender_points})")

    doc_points = _DOCUMENT_TYPE_POINTS.get(data.document_type or "", 0)
    if doc_points:
        score += doc_points
        reasons.append(f"Dokumenttyp '{data.document_type}' (+{doc_points})")

    if data.payment_requested:
        score += _PAYMENT_REQUESTED_POINTS
        reasons.append(f"Zahlungsaufforderung (+{_PAYMENT_REQUESTED_POINTS})")

    if data.objection_right_mentioned:
        score += _OBJECTION_RIGHT_POINTS
        reasons.append(f"Widerspruchs-/Einspruchsrecht erwähnt (+{_OBJECTION_RIGHT_POINTS})")

    deadline_type = data.deadline_type or "none"
    deadline_points = _DEADLINE_TYPE_POINTS.get(deadline_type, 0)
    if deadline_points:
        score += deadline_points
        reasons.append(f"Frist vom Typ '{deadline_type}' (+{deadline_points})")

    if deadline_type != "none" and data.deadline_certainty == "unknown_needs_review":
        score += _UNRESOLVED_DEADLINE_POINTS
        reasons.append(
            f"Frist erkannt, aber Datum ungeklärt - zur Sicherheit hochgestuft "
            f"(+{_UNRESOLVED_DEADLINE_POINTS})"
        )

    level = _level_from_score(score)

    if data.document_type in _ALWAYS_AT_LEAST_HIGH:
        floored = _max_level(level, "high")
        if floored != level:
            reasons.append(
                f"Mindestpriorität 'high' fuer Dokumenttyp '{data.document_type}' erzwungen"
            )
        level = floored

    reasoning = (
        "; ".join(reasons) if reasons else "Keine erschwerenden Signale erkannt"
    )
    reasoning = f"{reasoning} -> Score {score} -> '{level}'"

    return PriorityResult(priority_level=level, priority_reasoning=reasoning)
