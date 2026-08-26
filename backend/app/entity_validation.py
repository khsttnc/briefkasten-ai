from __future__ import annotations

import logging
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

# Deliberately logged (not silently dropped) at WARNING - the default level
# that shows up in `docker compose logs backend` with no extra
# configuration needed (see main.py's "briefkasten" logger, which never
# calls logging.basicConfig - the root logger's own WARNING-level default
# applies). Real production cost of the alternative: three separate
# incidents where a field came back empty/wrong and diagnosing which rule
# caught it required pulling the raw AI response straight out of the
# database by hand each time. Every log line below names only the field
# and the rule that fired - never the field's actual (possibly
# user-document-derived) content.
logger = logging.getLogger("briefkasten.entity_validation")

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
    dropped = 0
    for entity in entities:
        if not isinstance(entity, dict):
            continue

        entity_type = entity.get("type")
        type_key = entity_type.strip().lower() if isinstance(entity_type, str) else None
        value = entity.get("value")
        verifiable = True

        if type_key in _STRICT_EXACT_TYPES:
            verifiable = _is_verifiable_value(value) and value in text
        elif type_key in _FORMAT_TOLERANT_TYPES:
            if not _is_verifiable_value(value):
                verifiable = False
            else:
                normalized_value = _normalize_alnum(value)
                verifiable = bool(normalized_value) and normalized_value in normalized_text
        elif _is_date_type(type_key):
            if not _is_verifiable_value(value):
                verifiable = False
            else:
                parsed = parse_absolute_date(value)
                verifiable = parsed is not None and parsed in source_dates

        if verifiable:
            validated.append(entity)
        else:
            dropped += 1

    if dropped:
        logger.warning(
            "validation: extracted_entities dropped %d/%d (not_in_source)", dropped, len(entities)
        )

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

    if len(validated) != len(important_dates):
        logger.warning(
            "validation: important_dates filtered %d -> %d (dates_not_in_source)",
            len(important_dates),
            len(validated),
        )

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

# The Turkish verb stem "öde-" (ödemek = to pay) - matches ödeme, ödeyin,
# ödenmesi, ödenecek, ödemeniz, ödemek, etc. via substring, without needing
# to enumerate every inflected form. Used to catch a fabricated payment
# DEMAND smuggled into a free-text field (action_summary, summary,
# turkish_explanation), not to catch every mention of money/billing
# vocabulary in general - deliberately does NOT include neutral financial
# nouns like "fatura" (invoice), "tutar" (amount), "borç" (debt), "€"/"eur"
# (the previous, broader list did), because those regularly appear in
# purely informational sentences with no payment demand at all. Real
# production false positive from the broader list: a Vertragsaufhebung
# (insurance contract termination, nothing owed) had its entire - correct,
# source-backed - explanation dropped because it mentioned "fatura" in
# passing ("hesaplama ayrı faturada" = "see the separate invoice for the
# breakdown", a neutral pointer to a document, not a demand to pay) - that
# sentence contains no "öde"-rooted word at all, so this narrower check
# would not have dropped it. Used two ways: (1) to decide whether
# action_summary needs to be dropped once payment_requested is downgraded
# (_validate_payment_requested), and (2) by validate_explanatory_text to
# catch the same pattern in summary/turkish_explanation directly - which
# matters because those two fields are produced by every provider even when
# it populates no other document_intelligence.SIGNAL_KEYS at all
# (ClaudeProvider's prompt didn't, until it was wired into the shared
# signal-key prompt - see claude_provider.py), so a payment_requested=false
# check alone would miss a payment narrative invented straight into the
# prose.
_PAYMENT_DEMAND_PHRASES_TR = ("öde",)


def _has_payment_evidence(source_text: str) -> bool:
    lowered_text = source_text.lower()
    has_amount = bool(_PAYMENT_AMOUNT_RE.search(source_text))
    has_action_verb = any(verb in lowered_text for verb in _PAYMENT_ACTION_VERBS_DE)
    return has_amount and has_action_verb


def _drop_if_hallucinated_date(
    value: Optional[str], source_dates: Set[date]
) -> Tuple[Optional[str], Optional[str]]:
    """None/empty in, (None, None) out. Otherwise drops value entirely (not
    a partial edit - see the fail-closed rationale repeated throughout this
    module) if it contains an absolute date not found anywhere in the
    source text, returning (None, reason) so the caller can log which rule
    fired. Returns (value, None) when kept."""
    if not _is_verifiable_value(value):
        return None, None
    field_dates = find_all_dates_in_text(value)
    if field_dates and not field_dates.issubset(source_dates):
        return None, "hallucinated_date"
    return value, None


def _drop_if_unevidenced_payment_claim(
    value: Optional[str], source_text: str
) -> Tuple[Optional[str], Optional[str]]:
    if not value:
        return value, None
    if any(
        phrase in value.lower() for phrase in _PAYMENT_DEMAND_PHRASES_TR
    ) and not _has_payment_evidence(source_text):
        # Not attempting to surgically remove just the payment-related
        # clause from a free-form LLM sentence - that risks leaving a
        # grammatically broken or still-misleading remainder. Dropping the
        # whole (now partly fabricated) field is the same fail-closed
        # choice already made for individual entities above.
        return None, "unevidenced_payment_claim"
    return value, None


def _normalize_amount(raw: str) -> str:
    """"71,19 €" / "€71.19" / "71.19 EUR" -> "71.19", so the same amount
    written with a different decimal/thousands separator or currency
    marker still compares equal."""
    digits = re.sub(r"[^\d.,]", "", raw)
    if "," in digits and "." in digits:
        if digits.rfind(",") > digits.rfind("."):
            digits = digits.replace(".", "").replace(",", ".")
        else:
            digits = digits.replace(",", "")
    elif "," in digits:
        digits = digits.replace(",", ".")
    try:
        return f"{float(digits):.2f}"
    except ValueError:
        return digits


def _extract_amounts(text: str) -> Set[str]:
    return {_normalize_amount(match.group(0)) for match in _PAYMENT_AMOUNT_RE.finditer(text)}


def _drop_if_unverifiable_payment_narrative(
    value: Optional[str], source_text: str
) -> Tuple[Optional[str], Optional[str]]:
    """Used only by validate_explanatory_text (summary/turkish_explanation)
    - unlike _drop_if_unevidenced_payment_claim above (used for
    action_summary, an INSTRUCTIONAL "what to do" field), these two are
    DESCRIPTIVE fields, so a specific amount being verifiable in the
    source is itself sufficient evidence - no separate "you must pay" verb
    needs to also be present. Real production false positive from
    requiring amount+verb here too: a CHECK24 insurance quote stating
    "aylık prim 71,19 € öden[ecektir]" (informational - "the monthly
    premium is €71.19") had its entire correct explanation dropped,
    because the source is a product quote, not a bill, and so never
    contains an explicit demand verb like "zu zahlen"/"fällig" - even
    though the amount itself was genuinely, verifiably in the source.
    Stating a real, source-backed number is not the same claim as
    demanding payment of it; only an amount that does NOT appear in the
    source (or a payment claim with no amount attached at all, e.g. "pay
    within 15 days" with no source amount to check) is still fail-closed.
    """
    if not value:
        return value, None
    if not any(phrase in value.lower() for phrase in _PAYMENT_DEMAND_PHRASES_TR):
        return value, None

    field_amounts = _extract_amounts(value)
    if field_amounts:
        source_amounts = _extract_amounts(source_text)
        if field_amounts.issubset(source_amounts):
            return value, None
        return None, "unverified_amount"

    if _has_payment_evidence(source_text):
        return value, None
    return None, "unevidenced_payment_claim"


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
    logger.warning("validation: payment_requested downgraded true->false (unevidenced_payment_demand)")
    action_summary, reason = _drop_if_unevidenced_payment_claim(action_summary, source_text)
    if reason:
        logger.warning("validation: action_summary dropped (%s)", reason)

    return False, action_summary


def validate_explanatory_text(
    value: Any,
    source_text: Optional[str],
    field_name: str = "explanatory_text",
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

    field_name is used only for logging (which field got dropped and why -
    see the module-level logger comment) - callers pass "summary" /
    "turkish_explanation" so the two are distinguishable in the logs,
    since both go through this exact same function.
    """
    if not isinstance(value, str) or not value.strip():
        return None

    text = source_text or ""
    source_dates = find_all_dates_in_text(text)

    value, reason = _drop_if_hallucinated_date(value, source_dates)
    if reason:
        logger.warning("validation: %s dropped (%s)", field_name, reason)
        return None

    value, reason = _drop_if_unverifiable_payment_narrative(value, text)
    if reason:
        logger.warning("validation: %s dropped (%s)", field_name, reason)
        return None

    return value


def _validate_date_string(
    value: Any, source_dates: Set[date]
) -> Tuple[Optional[str], Optional[str]]:
    if not _is_verifiable_value(value):
        return None, None
    try:
        parsed = date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None, "unparseable_date"
    if parsed not in source_dates:
        return None, "date_not_in_source"
    return value, None


def _validate_deadline_raw_text(
    value: Any, source_dates: Set[date]
) -> Tuple[Optional[str], Optional[str]]:
    if not _is_verifiable_value(value):
        return None, None
    absolute_date = parse_absolute_date(value)
    if absolute_date is None:
        # A relative phrase ("innerhalb von 14 Tagen") or one that doesn't
        # parse at all - no literal date to verify here, so it's left to
        # resolve_deadline()'s own existing fail-closed handling.
        return value, None
    if absolute_date not in source_dates:
        return None, "date_not_in_source"
    return value, None


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

    deadline_raw_text, reason = _validate_deadline_raw_text(
        raw_response.get(DEADLINE_RAW_TEXT_KEY), source_dates
    )
    if reason:
        logger.warning("validation: deadline_raw_text dropped (%s)", reason)
    validated[DEADLINE_RAW_TEXT_KEY] = deadline_raw_text

    document_date, reason = _validate_date_string(raw_response.get(DOCUMENT_DATE_KEY), source_dates)
    if reason:
        logger.warning("validation: document_date dropped (%s)", reason)
    validated[DOCUMENT_DATE_KEY] = document_date

    effective_date, reason = _validate_date_string(raw_response.get(EFFECTIVE_DATE_KEY), source_dates)
    if reason:
        logger.warning("validation: effective_date dropped (%s)", reason)
    validated[EFFECTIVE_DATE_KEY] = effective_date

    payment_requested = raw_response.get(PAYMENT_REQUESTED_KEY) is True
    action_summary, reason = _drop_if_hallucinated_date(
        raw_response.get(ACTION_SUMMARY_KEY), source_dates
    )
    if reason:
        logger.warning("validation: action_summary dropped (%s)", reason)
    payment_requested, action_summary = _validate_payment_requested(
        payment_requested, action_summary, text
    )
    validated[PAYMENT_REQUESTED_KEY] = payment_requested
    validated[ACTION_SUMMARY_KEY] = action_summary

    return validated
