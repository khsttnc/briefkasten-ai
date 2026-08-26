from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional, Set, Tuple

from .deadline_engine import find_all_dates_in_text, parse_absolute_date
from .document_intelligence import (
    ACTION_SUMMARY_KEY,
    DEADLINE_RAW_TEXT_KEY,
    DOCUMENT_DATE_KEY,
    EFFECTIVE_DATE_KEY,
    OUTPUT_LANGUAGE_NAME,
    PAYMENT_REQUESTED_KEY,
)

# Hard backend cap on the number of entities returned, independent of
# whatever the prompt asked the LLM for - a document with many distinct
# repeated reference numbers (e.g. a per-section policy number that varies
# across a long insurance document) was observed in real testing to make
# the LLM enumerate every single one, ballooning completion length to
# ~6000 tokens for one document. Never trust the LLM to self-limit;
# enforce it here regardless of what the prompt says.
MAX_EXTRACTED_ENTITIES = 15

# If a single entity type has more than this many distinct validated
# values, listing every one is less useful to the reader than a single
# summarizing count - see _collapse_and_cap_entities.
MAX_ENTITIES_PER_TYPE_BEFORE_SUMMARIZING = 5

_REPEATED_ENTITY_SUMMARY_BY_LANGUAGE = {
    "Turkish": "{count} adet bulundu",
}


def _repeated_entity_summary(count: int) -> str:
    template = _REPEATED_ENTITY_SUMMARY_BY_LANGUAGE.get(
        OUTPUT_LANGUAGE_NAME, _REPEATED_ENTITY_SUMMARY_BY_LANGUAGE["Turkish"]
    )
    return template.format(count=count)


def _collapse_and_cap_entities(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deterministic, LLM-independent enforcement of MAX_EXTRACTED_ENTITIES.

    A type with many repeated values (e.g. 140 distinct policy numbers from
    a long multi-section document) collapses into one entry noting the
    count, which is more useful to the reader than an unbounded list and
    also keeps the AI-provider response bounded regardless of document size.
    """
    by_type: Dict[str, List[Dict[str, Any]]] = {}
    for entity in entities:
        type_key = entity.get("type") if isinstance(entity.get("type"), str) else "other"
        by_type.setdefault(type_key, []).append(entity)

    needs_collapsing = any(
        len(items) > MAX_ENTITIES_PER_TYPE_BEFORE_SUMMARIZING for items in by_type.values()
    )
    if not needs_collapsing and len(entities) <= MAX_EXTRACTED_ENTITIES:
        # Common case: nothing to collapse or truncate - return the
        # original list untouched (exact order/objects), rather than
        # reconstructing it via the type-grouping below, which would
        # silently reorder entities of the same type that were interleaved
        # with other types in the source list.
        return entities

    collapsed: List[Dict[str, Any]] = []
    for entity_type, items in by_type.items():
        if len(items) > MAX_ENTITIES_PER_TYPE_BEFORE_SUMMARIZING:
            collapsed.append({"type": entity_type, "value": _repeated_entity_summary(len(items))})
        else:
            collapsed.extend(items)

    # Per-type collapsing may still leave more distinct types than the
    # overall cap allows (many different single-occurrence types) -
    # truncate deterministically rather than let the list keep growing.
    return collapsed[:MAX_EXTRACTED_ENTITIES]


# Entities whose value must appear character-for-character in the source
# text. No normalization is applied - a single dropped, added, reordered, or
# separator-inserted digit fails verification and the entity is dropped.
_STRICT_EXACT_TYPES = {
    "adac_membership_number",
    "policy_or_contract_number",
    "evb_number",
}

# Entities that may legitimately be formatted differently than the source
# (e.g. a license plate rendered with or without the conventional
# district-hyphen-letters space). Only separator characters are forgiven;
# the underlying letter/digit sequence must still match exactly.
_FORMAT_TOLERANT_TYPES = {
    "license_plate",
}

_NON_ALNUM_RE = re.compile(r"[^A-Za-z0-9]")


def _normalize_alnum(value: str) -> str:
    return _NON_ALNUM_RE.sub("", value).upper()


def _is_verifiable_value(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _is_date_type(type_key: Optional[str]) -> bool:
    # Substring match, not an exact set: the current extraction prompt never
    # asks for a "date"-typed entity (dates live in document_date,
    # effective_date, deadline_raw_text, and important_dates instead - see
    # validate_intelligence_signals/validate_important_dates below), but if
    # a future prompt change ever adds one (e.g. "date", "important_date",
    # "deadline_date"), it must not silently bypass verification the way
    # any other out-of-scope type currently does.
    return isinstance(type_key, str) and "date" in type_key


def validate_extracted_entities(
    entities: Optional[List[Dict[str, Any]]],
    source_text: Optional[str],
) -> List[Dict[str, Any]]:
    """Deterministic safety net for code/number/date entities extracted by an
    AI provider.

    The goal is not to make the model more accurate - it is to guarantee that
    a wrong code/number/date value never reaches the database or the user. An
    entity whose value cannot be verified against the source text is dropped
    rather than surfaced; a missing entity is safer than a wrong one.
    """
    if not entities:
        return []

    text = source_text or ""
    normalized_text = _normalize_alnum(text)
    source_dates = find_all_dates_in_text(text)

    validated: List[Dict[str, Any]] = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue

        entity_type = entity.get("type")
        type_key = entity_type.strip().lower() if isinstance(entity_type, str) else None
        value = entity.get("value")

        if type_key in _STRICT_EXACT_TYPES:
            if not _is_verifiable_value(value) or value not in text:
                continue
        elif type_key in _FORMAT_TOLERANT_TYPES:
            if not _is_verifiable_value(value):
                continue
            normalized_value = _normalize_alnum(value)
            if not normalized_value or normalized_value not in normalized_text:
                continue
        elif _is_date_type(type_key):
            if not _is_verifiable_value(value):
                continue
            parsed = parse_absolute_date(value)
            if parsed is None or parsed not in source_dates:
                continue

        validated.append(entity)

    return _collapse_and_cap_entities(validated)


def validate_important_dates(
    important_dates: Optional[List[Any]],
    source_text: Optional[str],
) -> List[str]:
    """Same fail-closed verification as validate_extracted_entities, applied
    to the separate important_dates free-string list (see ai_service.py) -
    this is a distinct field from extracted_entities and was previously
    never checked against the source text at all.

    A string that contains no parseable absolute date (e.g. free-form text
    without a date in it) is kept as-is - there is nothing to verify. A
    string containing a date not found anywhere in the source is dropped
    entirely, the same as a fabricated code/number entity.
    """
    if not important_dates:
        return []

    text = source_text or ""
    source_dates = find_all_dates_in_text(text)

    validated: List[str] = []
    for entry in important_dates:
        if not isinstance(entry, str) or not entry.strip():
            continue
        entry_dates = find_all_dates_in_text(entry)
        if entry_dates and not entry_dates.issubset(source_dates):
            continue
        validated.append(entry)

    return validated


# Evidence that the document genuinely requests a payment: a currency
# amount AND a payment-action verb, BOTH present somewhere in the source
# text. A single broad keyword (the previous approach - "Betrag", "EUR",
# "Rechnung", or similar) is not enough: a real production false positive
# was an Antragsformular (application form) for a credit-card debt
# insurance product, whose text mentioned "Kreditkarte", "Bank", and
# "Versicherung" without requesting any payment at all - none of those
# individually imply a payment demand, but the old single-keyword check
# (which also included "Rechnung"/"Betrag") would have accepted any of
# them as sufficient evidence. Requiring an amount AND a verb together is
# still deliberately loose (no proximity/sentence-level check, no attempt
# to also require a due date) - the goal remains only to catch the case
# where the LLM claims payment_requested=true with no textual basis
# whatsoever, not to precisely parse every real payment demand.
_PAYMENT_AMOUNT_RE = re.compile(r"(?:€\s?\d[\d.,]*|\d[\d.,]*\s?(?:€|eur\b))", re.IGNORECASE)

_PAYMENT_ACTION_VERBS_DE = (
    "zu zahlen", "zahlen sie", "bitte zahlen", "überweisen", "überweisung",
    "entrichten", "beglichen", "fällig", "zahlungsfrist", "einzuzahlen",
    "vollstreckung",
)

# Turkish payment-related wording that a free-text field (action_summary,
# summary, turkish_explanation) might contain when it asserts a payment
# obligation the source text doesn't actually support. Used two ways: (1)
# to decide whether action_summary needs to be dropped once
# payment_requested is downgraded (_validate_payment_requested), and (2) by
# validate_explanatory_text to catch the same fabricated-payment-claim
# pattern in summary/turkish_explanation directly - which matters because
# those two fields are produced by every provider even when it populates no
# other document_intelligence.SIGNAL_KEYS at all (ClaudeProvider's prompt
# didn't, until it was wired into the shared signal-key prompt - see
# claude_provider.py), so a payment_requested=false check alone would miss
# a payment narrative invented straight into the prose.
_PAYMENT_KEYWORDS_TR = (
    "öde", "ödeme", "ödeyin", "ödenmesi", "ödenecek", "borç", "borc",
    "tutar", "fatura", "avans", "€", "eur", " tl",
)


def _has_payment_evidence(source_text: str) -> bool:
    lowered_text = source_text.lower()
    has_amount = bool(_PAYMENT_AMOUNT_RE.search(source_text))
    has_action_verb = any(verb in lowered_text for verb in _PAYMENT_ACTION_VERBS_DE)
    return has_amount and has_action_verb


def _drop_if_hallucinated_date(value: Optional[str], source_dates: Set[date]) -> Optional[str]:
    """None/empty in, None out. Otherwise drops value entirely (not a
    partial edit - see the fail-closed rationale repeated throughout this
    module) if it contains an absolute date not found anywhere in the
    source text."""
    if not _is_verifiable_value(value):
        return None
    field_dates = find_all_dates_in_text(value)
    if field_dates and not field_dates.issubset(source_dates):
        return None
    return value


def _drop_if_unevidenced_payment_claim(value: Optional[str], source_text: str) -> Optional[str]:
    if not value:
        return value
    if any(keyword in value.lower() for keyword in _PAYMENT_KEYWORDS_TR) and not _has_payment_evidence(
        source_text
    ):
        # Not attempting to surgically remove just the payment-related
        # clause from a free-form LLM sentence - that risks leaving a
        # grammatically broken or still-misleading remainder. Dropping the
        # whole (now partly fabricated) field is the same fail-closed
        # choice already made for individual entities above.
        return None
    return value


def _validate_payment_requested(
    payment_requested: bool,
    action_summary: Optional[str],
    source_text: str,
) -> Tuple[bool, Optional[str]]:
    if not payment_requested:
        return payment_requested, action_summary

    if _has_payment_evidence(source_text):
        return payment_requested, action_summary

    # No textual evidence anywhere in the source for a payment demand -
    # fail closed rather than surface a fabricated "pay within N days"
    # claim to the reader.
    action_summary = _drop_if_unevidenced_payment_claim(action_summary, source_text)

    return False, action_summary


def validate_explanatory_text(
    value: Any,
    source_text: Optional[str],
) -> Optional[str]:
    """Fail-closed verification for summary/turkish_explanation - the two
    free-form LLM fields never covered by validate_intelligence_signals.
    Unlike every other field in this module, these have no structured
    counterpart, and every AI provider produces them regardless of whether
    it also populates document_intelligence.SIGNAL_KEYS - so this is the
    only backstop against a hallucinated date or an invented payment
    obligation embedded directly in the prose shown to the reader
    ("Açıklama" in the UI). Confirmed production case: a credit-card
    debt-insurance APPLICATION FORM (nothing billed, nothing due) came back
    from a provider populating no SIGNAL_KEYS at all (ClaudeProvider's
    prompt, before it was wired into the shared signal-key prompt - see
    claude_provider.py) classified as an invoice, with four fabricated
    dates and a "pay within 15 days" narrative baked into
    turkish_explanation - payment_requested itself was never even involved.
    Kept as a backstop even now that Claude is wired in too: a future
    provider or prompt regression could reintroduce the same gap.
    """
    if not isinstance(value, str) or not value.strip():
        return None

    text = source_text or ""
    source_dates = find_all_dates_in_text(text)

    value = _drop_if_hallucinated_date(value, source_dates)
    value = _drop_if_unevidenced_payment_claim(value, text)

    return value


def _validate_date_string(value: Any, source_dates: Set[date]) -> Optional[str]:
    if not _is_verifiable_value(value):
        return None
    try:
        parsed = date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None
    if parsed not in source_dates:
        return None
    return value


def _validate_deadline_raw_text(value: Any, source_dates: Set[date]) -> Optional[str]:
    if not _is_verifiable_value(value):
        return None
    absolute_date = parse_absolute_date(value)
    if absolute_date is None:
        # A relative phrase ("innerhalb von 14 Tagen") or one that doesn't
        # parse at all - no literal date to verify here, so it's left to
        # resolve_deadline()'s own existing fail-closed handling.
        return value
    if absolute_date not in source_dates:
        return None
    return value


def validate_intelligence_signals(
    raw_response: Optional[Dict[str, Any]],
    source_text: Optional[str],
) -> Dict[str, Any]:
    """Deterministic safety net for the free-form date/payment signal keys
    in raw_response, applied before document_intelligence.derive_intelligence_fields()
    turns them into Document columns and the deadline/priority engines act
    on them.

    derive_intelligence_fields() itself never receives source_text and only
    checks these values for the right Python type (see its _safe_* helpers)
    - it has no way to know a syntactically valid date or a well-formed
    boolean is actually wrong. This function is the analogue of
    validate_extracted_entities() for those keys: a value that cannot be
    verified against the source document is dropped (set to None/False)
    rather than surfaced, so a wrong date or an invented payment demand
    never reaches deadline_engine/priority_engine or the reader.
    """
    if not isinstance(raw_response, dict):
        # Same defensive convention as derive_intelligence_fields itself:
        # a non-dict payload becomes an empty payload, never a crash or a
        # pass-through of an unusable value.
        return {}

    text = source_text or ""
    source_dates = find_all_dates_in_text(text)

    validated = dict(raw_response)
    validated[DEADLINE_RAW_TEXT_KEY] = _validate_deadline_raw_text(
        raw_response.get(DEADLINE_RAW_TEXT_KEY), source_dates
    )
    validated[DOCUMENT_DATE_KEY] = _validate_date_string(
        raw_response.get(DOCUMENT_DATE_KEY), source_dates
    )
    validated[EFFECTIVE_DATE_KEY] = _validate_date_string(
        raw_response.get(EFFECTIVE_DATE_KEY), source_dates
    )

    payment_requested = raw_response.get(PAYMENT_REQUESTED_KEY) is True
    action_summary = _drop_if_hallucinated_date(raw_response.get(ACTION_SUMMARY_KEY), source_dates)
    payment_requested, action_summary = _validate_payment_requested(
        payment_requested, action_summary, text
    )
    validated[PAYMENT_REQUESTED_KEY] = payment_requested
    validated[ACTION_SUMMARY_KEY] = action_summary

    return validated
