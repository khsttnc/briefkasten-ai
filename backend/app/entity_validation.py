from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

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

    return validated
