"""Deterministic deadline resolution.

The LLM only extracts the raw deadline phrase from a document (e.g. "bis
zum 15.09.2026", "innerhalb von 14 Tagen") - it never gets to invent or
compute a final date. This module turns that raw phrase into a
deadline_type/deadline_certainty/deadline_estimated_date triple using fixed
rules only. Same "fail closed" spirit as entity_validation.py: if a date
cannot be derived with confidence, we say so (unknown_needs_review) instead
of guessing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, Set, Tuple

# --- Zustellfiktion (deemed-delivery) ---------------------------------
# A written German administrative decision (Verwaltungsakt) sent by post is
# legally deemed delivered a fixed number of days after it was handed to
# the postal service, regardless of when it actually arrived. Since
# 2025-01-01 this is 4 days (VwVfG §41(2), SGB X §37(2), AO §122(2)); before
# that the rule was 3 days. A relative deadline ("innerhalb von 14 Tagen")
# runs from this deemed-delivery date, not from the date printed on the
# document itself.
_ZUSTELLFIKTION_CHANGE_DATE = date(2025, 1, 1)
_ZUSTELLFIKTION_DAYS_OLD = 3
_ZUSTELLFIKTION_DAYS_NEW = 4


def _zustellfiktion_days(document_date: date) -> int:
    if document_date < _ZUSTELLFIKTION_CHANGE_DATE:
        return _ZUSTELLFIKTION_DAYS_OLD
    return _ZUSTELLFIKTION_DAYS_NEW


def _add_months(start: date, months: int) -> date:
    total_month_index = start.month - 1 + months
    year = start.year + total_month_index // 12
    month = total_month_index % 12 + 1
    # Clamp the day for month-end overflow (e.g. 31 Jan + 1 month -> 28/29 Feb).
    day = start.day
    while True:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1


DeadlineType = str  # "absolute" | "relative" | "none"
DeadlineCertainty = str  # "exact" | "estimated" | "unknown_needs_review"


@dataclass
class DeadlineResult:
    deadline_raw_text: Optional[str]
    deadline_type: DeadlineType
    deadline_certainty: DeadlineCertainty
    deadline_estimated_date: Optional[date]


# "bis [zum/spätestens ...] 15.09.2026" or "15. September 2026"
_ABSOLUTE_NUMERIC_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")

_GERMAN_MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4, "mai": 5,
    "juni": 6, "juli": 7, "august": 8, "september": 9, "oktober": 10,
    "november": 11, "dezember": 12,
}
_ABSOLUTE_WRITTEN_RE = re.compile(
    r"\b(\d{1,2})\.?\s*(" + "|".join(_GERMAN_MONTHS) + r")\s*(\d{4})\b",
    re.IGNORECASE,
)

# "innerhalb von 14 Tagen", "binnen 2 Wochen", "innerhalb eines Monats"
_UNIT_TO_TIMEDELTA_DAYS = {
    "tag": 1, "tage": 1, "tagen": 1,
    "woche": 7, "wochen": 7,
}
_MONTH_UNITS = {"monat", "monate", "monaten", "monats"}

_SPELLED_ONE = {"ein", "eine", "einem", "einen", "einer", "eines"}

# Small cardinal numbers 2-10 don't inflect for case in German (unlike
# "ein"), so one spelling each is enough. Added for phrasings like
# "spätestens drei Tage nach ..." (a real statutory-deadline clause, e.g.
# the SGB III Arbeitsagentur reporting duty after a Kündigung) that spell
# the number out instead of using a digit.
_SPELLED_TWO_TO_TEN = {
    "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "sechs": 6,
    "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,
}

_SPELLED_AMOUNT_WORDS = set(_SPELLED_ONE) | set(_SPELLED_TWO_TO_TEN)

# "innerhalb (von) 14 Tagen" / "binnen 2 Wochen" trigger a deadline counted
# from delivery; "spätestens ... Tage/Wochen/Monate(n) nach ..." is the same
# kind of relative deadline phrased the other way round (a hard cutoff
# stated as "no later than N days after X") - both compute identically once
# the amount/unit are extracted, so they share one pattern. The word(s)
# after the amount+unit (e.g. "nach Zugang dieser Kündigung") are not
# captured; they don't affect the computed date and deadline_raw_text (the
# LLM-copied verbatim phrase) keeps them for human readability.
_RELATIVE_RE = re.compile(
    r"\b(?:innerhalb(?:\s+von)?|binnen|spätestens)\s+"
    r"(?P<amount>\d{1,3}|" + "|".join(_SPELLED_AMOUNT_WORDS) + r")\s+"
    r"(?P<unit>tag|tage|tagen|woche|wochen|monat|monate|monaten|monats)\b",
    re.IGNORECASE,
)

_SPELLED_AMOUNT_VALUES = {word: 1 for word in _SPELLED_ONE}
_SPELLED_AMOUNT_VALUES.update(_SPELLED_TWO_TO_TEN)


def _resolve_amount(amount_raw: str) -> int:
    amount_raw = amount_raw.lower()
    if amount_raw in _SPELLED_AMOUNT_VALUES:
        return _SPELLED_AMOUNT_VALUES[amount_raw]
    return int(amount_raw)


def parse_absolute_date(text: str) -> Optional[date]:
    """First absolute date found in text (DD.MM.YYYY or written German
    form), or None. Public so entity_validation.py can extract the date a
    deadline_raw_text phrase claims, to verify it against the source
    document independently of deadline resolution itself."""
    match = _ABSOLUTE_NUMERIC_RE.search(text)
    if match:
        day, month, year = (int(g) for g in match.groups())
        try:
            return date(year, month, day)
        except ValueError:
            return None

    match = _ABSOLUTE_WRITTEN_RE.search(text)
    if match:
        day = int(match.group(1))
        month = _GERMAN_MONTHS[match.group(2).lower()]
        year = int(match.group(3))
        try:
            return date(year, month, day)
        except ValueError:
            return None

    return None


def find_all_dates_in_text(text: str) -> Set[date]:
    """Every absolute calendar date (DD.MM.YYYY or written German form)
    found anywhere in text, as a set of date objects. Not used by deadline
    resolution itself (which only looks at deadline_raw_text) - this exists
    for entity_validation.py to check whether an LLM-extracted date
    actually appears in the source document, regardless of where in the
    text it appears or how it's formatted."""
    found: Set[date] = set()

    for match in _ABSOLUTE_NUMERIC_RE.finditer(text):
        day, month, year = (int(g) for g in match.groups())
        try:
            found.add(date(year, month, day))
        except ValueError:
            continue

    for match in _ABSOLUTE_WRITTEN_RE.finditer(text):
        day = int(match.group(1))
        month = _GERMAN_MONTHS[match.group(2).lower()]
        year = int(match.group(3))
        try:
            found.add(date(year, month, day))
        except ValueError:
            continue

    return found


def relative_period_amount_and_unit_family(
    text: str,
) -> Optional[Tuple[Set[str], Set[str]]]:
    """Given a possible relative-duration phrase (e.g. a deadline_raw_text
    value), returns (amount_alternatives, unit_alternatives) - every
    textual form that would mean "the same amount" (digit and spelled-out,
    for numbers 1-10) and "the same unit family" (every inflection of
    day/week, or of month) - or None if text doesn't match a
    relative-duration pattern at all.

    Public so entity_validation.py can verify the amount+unit a relative
    deadline_raw_text claims actually occurs somewhere in the source
    document, independent of deadline resolution itself - real incident:
    a hallucinated "innerhalb von 14 Tagen" with no basis anywhere in the
    source drove resolve_deadline() to compute a fabricated exact date via
    otherwise-correct Zustellfiktion math, because nothing checked whether
    that phrase was genuine before computing from it.
    """
    match = _RELATIVE_RE.search(text)
    if match is None:
        return None

    amount_raw = match.group("amount")
    unit = match.group("unit").lower()

    amount_alternatives = {amount_raw.lower()}
    try:
        resolved = _resolve_amount(amount_raw)
        amount_alternatives.add(str(resolved))
        for word, value in _SPELLED_AMOUNT_VALUES.items():
            if value == resolved:
                amount_alternatives.add(word)
    except ValueError:
        pass

    if unit in _MONTH_UNITS:
        unit_alternatives = set(_MONTH_UNITS)
    else:
        unit_days = _UNIT_TO_TIMEDELTA_DAYS[unit]
        unit_alternatives = {u for u, days in _UNIT_TO_TIMEDELTA_DAYS.items() if days == unit_days}

    return amount_alternatives, unit_alternatives


def _parse_relative_duration_days(text: str) -> Optional[int]:
    """Returns the duration in days, or None if no relative-duration phrase
    was found. Month units are resolved against a `document_date` by the
    caller, not here, since a fixed day-count for "a month" would be wrong."""
    match = _RELATIVE_RE.search(text)
    if not match:
        return None

    amount = _resolve_amount(match.group("amount"))
    unit = match.group("unit").lower()

    if unit in _MONTH_UNITS:
        return None  # signal "months" case to the caller separately
    return amount * _UNIT_TO_TIMEDELTA_DAYS[unit]


def _parse_relative_duration_months(text: str) -> Optional[int]:
    match = _RELATIVE_RE.search(text)
    if not match:
        return None
    unit = match.group("unit").lower()
    if unit not in _MONTH_UNITS:
        return None
    return _resolve_amount(match.group("amount"))


def resolve_deadline(
    deadline_raw_text: Optional[str],
    document_date: Optional[date] = None,
    *,
    multiple_deadlines_detected: bool = False,
) -> DeadlineResult:
    """Turn an LLM-extracted raw deadline phrase into a deterministic
    deadline_type/deadline_certainty/deadline_estimated_date triple.

    Never invents an exact date: a relative duration without a known
    document_date, or text that mentions a deadline but doesn't match a
    recognized pattern, is reported as unknown_needs_review rather than
    guessed.

    multiple_deadlines_detected is a signal from the LLM that the source
    text contains more than one distinct deadline/response-period phrase
    (e.g. a payment deadline and a separate Widerspruch/appeal deadline).
    deadline_raw_text is expected to already be the single phrase the
    caller picked (by policy: the one with the heavier legal consequence -
    see the Ollama prompt), but which one is genuinely "the" deadline is
    then ambiguous even if that phrase itself parses cleanly - so any
    would-be exact/estimated result is downgraded to
    unknown_needs_review/no date instead, the same fail-closed treatment
    as an unparseable phrase.
    """
    result = _resolve_single_deadline(deadline_raw_text, document_date)
    if multiple_deadlines_detected and result.deadline_certainty != "unknown_needs_review":
        return DeadlineResult(
            deadline_raw_text=result.deadline_raw_text,
            deadline_type=result.deadline_type,
            deadline_certainty="unknown_needs_review",
            deadline_estimated_date=None,
        )
    return result


def _resolve_single_deadline(
    deadline_raw_text: Optional[str],
    document_date: Optional[date],
) -> DeadlineResult:
    text = (deadline_raw_text or "").strip()

    if not text:
        return DeadlineResult(
            deadline_raw_text=deadline_raw_text,
            deadline_type="none",
            deadline_certainty="exact",
            deadline_estimated_date=None,
        )

    absolute_date = parse_absolute_date(text)
    if absolute_date is not None:
        return DeadlineResult(
            deadline_raw_text=deadline_raw_text,
            deadline_type="absolute",
            deadline_certainty="exact",
            deadline_estimated_date=absolute_date,
        )

    relative_days = _parse_relative_duration_days(text)
    relative_months = _parse_relative_duration_months(text)

    if relative_days is not None or relative_months is not None:
        if document_date is None:
            # We know a relative deadline exists but cannot compute it
            # without the document's issue date - fail closed rather than
            # guess a date.
            return DeadlineResult(
                deadline_raw_text=deadline_raw_text,
                deadline_type="relative",
                deadline_certainty="unknown_needs_review",
                deadline_estimated_date=None,
            )

        deemed_delivery = document_date + timedelta(days=_zustellfiktion_days(document_date))
        if relative_days is not None:
            estimated_date = deemed_delivery + timedelta(days=relative_days)
        else:
            estimated_date = _add_months(deemed_delivery, relative_months)

        return DeadlineResult(
            deadline_raw_text=deadline_raw_text,
            deadline_type="relative",
            deadline_certainty="estimated",
            deadline_estimated_date=estimated_date,
        )

    # Non-empty text that matches neither a known absolute nor relative
    # pattern - a deadline may well be mentioned, but we cannot parse it
    # confidently. Flag for human review instead of dropping or guessing.
    return DeadlineResult(
        deadline_raw_text=deadline_raw_text,
        deadline_type="none",
        deadline_certainty="unknown_needs_review",
        deadline_estimated_date=None,
    )
