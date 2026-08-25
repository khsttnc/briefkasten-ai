from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .document_intelligence import OUTPUT_LANGUAGE_NAME

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


def validate_extracted_entities(
    entities: Optional[List[Dict[str, Any]]],
    source_text: Optional[str],
) -> List[Dict[str, Any]]:
    """Deterministic safety net for code/number entities extracted by an AI provider.

    The goal is not to make the model more accurate - it is to guarantee that
    a wrong code/number value never reaches the database or the user. An
    entity whose value cannot be verified against the source text is dropped
    rather than surfaced; a missing entity is safer than a wrong one.
    """
    if not entities:
        return []

    text = source_text or ""
    normalized_text = _normalize_alnum(text)

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

        validated.append(entity)

    return _collapse_and_cap_entities(validated)
