import unittest

from .entity_validation import (
    MAX_ENTITIES_PER_TYPE_BEFORE_SUMMARIZING,
    MAX_EXTRACTED_ENTITIES,
    validate_extracted_entities,
)

SOURCE_TEXT = (
    "Ihre Kfz-Versicherung AD-5409239121 (bitte stets angeben)\n"
    "Amtl. Kennzeichen: BE-ZL 37, ADAC-Mitgliedsnummer 734333034\n"
    "Sehr geehrter Herr Tuetuenue,\n"
)


class AdacMembershipNumberValidationTestCase(unittest.TestCase):
    """Regression guard for the digit-corruption bug: qwen3:8b occasionally
    dropped or inserted a character inside the ADAC membership number. These
    are the exact three cases observed in production data."""

    def test_exact_value_is_accepted(self):
        entities = [{"type": "adac_membership_number", "value": "734333034"}]
        result = validate_extracted_entities(entities, SOURCE_TEXT)
        self.assertEqual(result, entities)

    def test_digit_dropped_is_rejected(self):
        entities = [{"type": "adac_membership_number", "value": "73433034"}]
        result = validate_extracted_entities(entities, SOURCE_TEXT)
        self.assertEqual(result, [])

    def test_comma_inserted_is_rejected(self):
        entities = [{"type": "adac_membership_number", "value": "73433,3034"}]
        result = validate_extracted_entities(entities, SOURCE_TEXT)
        self.assertEqual(result, [])


class StrictExactTypesTestCase(unittest.TestCase):
    def test_policy_or_contract_number_exact_match_accepted(self):
        entities = [{"type": "policy_or_contract_number", "value": "AD-5409239121"}]
        self.assertEqual(validate_extracted_entities(entities, SOURCE_TEXT), entities)

    def test_policy_or_contract_number_fabricated_value_rejected(self):
        entities = [{"type": "policy_or_contract_number", "value": "AD-5409239122"}]
        self.assertEqual(validate_extracted_entities(entities, SOURCE_TEXT), [])

    def test_evb_number_with_no_real_number_in_source_is_always_rejected(self):
        # SOURCE_TEXT contains no eVB number at all. Any value the model
        # invents for this type cannot be a literal substring of the source,
        # so it is dropped without any eVB-specific logic being needed.
        entities = [{"type": "evb_number", "value": "12345678"}]
        self.assertEqual(validate_extracted_entities(entities, SOURCE_TEXT), [])

    def test_type_matching_is_case_and_whitespace_insensitive(self):
        entities = [{"type": "  ADAC_Membership_Number  ", "value": "734333034"}]
        self.assertEqual(validate_extracted_entities(entities, SOURCE_TEXT), entities)

    def test_missing_value_is_rejected(self):
        entities = [{"type": "adac_membership_number"}]
        self.assertEqual(validate_extracted_entities(entities, SOURCE_TEXT), [])

    def test_null_value_is_rejected(self):
        entities = [{"type": "adac_membership_number", "value": None}]
        self.assertEqual(validate_extracted_entities(entities, SOURCE_TEXT), [])

    def test_blank_value_is_rejected(self):
        entities = [{"type": "adac_membership_number", "value": "   "}]
        self.assertEqual(validate_extracted_entities(entities, SOURCE_TEXT), [])

    def test_no_separator_normalization_is_applied(self):
        # Strict types must not tolerate even a formatting-only change - a
        # value that is only accepted after normalization must still be
        # rejected, unlike license_plate.
        entities = [{"type": "policy_or_contract_number", "value": "AD 5409239121"}]
        self.assertEqual(validate_extracted_entities(entities, SOURCE_TEXT), [])


class LicensePlateFormatToleranceTestCase(unittest.TestCase):
    def test_exact_source_format_accepted(self):
        entities = [{"type": "license_plate", "value": "BE-ZL 37"}]
        self.assertEqual(validate_extracted_entities(entities, SOURCE_TEXT), entities)

    def test_reformatted_without_space_or_hyphen_accepted(self):
        entities = [{"type": "license_plate", "value": "BEZL37"}]
        self.assertEqual(validate_extracted_entities(entities, SOURCE_TEXT), entities)

    def test_lowercase_variant_accepted(self):
        entities = [{"type": "license_plate", "value": "be-zl 37"}]
        self.assertEqual(validate_extracted_entities(entities, SOURCE_TEXT), entities)

    def test_changed_digit_is_rejected(self):
        entities = [{"type": "license_plate", "value": "BE-ZL 38"}]
        self.assertEqual(validate_extracted_entities(entities, SOURCE_TEXT), [])

    def test_fabricated_plate_is_rejected(self):
        entities = [{"type": "license_plate", "value": "M-AB 1234"}]
        self.assertEqual(validate_extracted_entities(entities, SOURCE_TEXT), [])

    def test_blank_value_is_rejected(self):
        entities = [{"type": "license_plate", "value": ""}]
        self.assertEqual(validate_extracted_entities(entities, SOURCE_TEXT), [])


class OutOfScopeAndMalformedEntitiesTestCase(unittest.TestCase):
    def test_unrelated_entity_types_pass_through_unmodified(self):
        entities = [
            {"type": "customer_name", "value": "Anything, even unverifiable text"},
            {"type": "insurance_company", "value": "ADAC Autoversicherung AG"},
            {"type": "address", "value": "Nonexistent Street 999"},
        ]
        self.assertEqual(validate_extracted_entities(entities, SOURCE_TEXT), entities)

    def test_legacy_schema_entities_without_type_key_pass_through(self):
        entities = [{"name": "Test GmbH"}]
        self.assertEqual(validate_extracted_entities(entities, SOURCE_TEXT), entities)

    def test_non_dict_entity_is_dropped_defensively(self):
        entities = ["not-a-dict", {"type": "adac_membership_number", "value": "734333034"}]
        result = validate_extracted_entities(entities, SOURCE_TEXT)
        self.assertEqual(result, [{"type": "adac_membership_number", "value": "734333034"}])

    def test_none_entities_returns_empty_list(self):
        self.assertEqual(validate_extracted_entities(None, SOURCE_TEXT), [])

    def test_empty_entities_returns_empty_list(self):
        self.assertEqual(validate_extracted_entities([], SOURCE_TEXT), [])

    def test_missing_source_text_rejects_all_code_number_entities(self):
        entities = [
            {"type": "adac_membership_number", "value": "734333034"},
            {"type": "license_plate", "value": "BE-ZL 37"},
        ]
        self.assertEqual(validate_extracted_entities(entities, None), [])
        self.assertEqual(validate_extracted_entities(entities, ""), [])


class EntityCountCapTestCase(unittest.TestCase):
    """Regression test for a real finding: a document with many distinct
    repeated reference numbers (140 policy numbers in a real test) made the
    LLM enumerate every single one, ballooning the response to ~6000
    completion tokens. Must never trust the prompt's own cap - enforce it
    here regardless of what the LLM actually returned."""

    def test_entities_at_or_under_the_cap_pass_through_unchanged(self):
        # Distinct types (not one type repeated) - this isolates the
        # overall-count cap from the per-type collapsing behavior.
        entities = [
            {"type": f"type_{i}", "value": f"value_{i}"} for i in range(MAX_EXTRACTED_ENTITIES)
        ]
        self.assertEqual(validate_extracted_entities(entities, None), entities)

    def test_many_of_the_same_type_collapse_to_one_count_entry(self):
        # vehicle_reference (not a _STRICT_EXACT_TYPES member) so source-text
        # verification doesn't interfere with isolating the capping behavior.
        count = MAX_ENTITIES_PER_TYPE_BEFORE_SUMMARIZING + 3
        entities = [
            {"type": "vehicle_reference", "value": f"AD-{i}"} for i in range(count)
        ] + [{"type": "customer_name", "value": "extra to force over-cap"}]
        result = validate_extracted_entities(entities, None)
        vehicle_entries = [e for e in result if e["type"] == "vehicle_reference"]
        self.assertEqual(len(vehicle_entries), 1)
        self.assertIn(str(count), vehicle_entries[0]["value"])

    def test_collapsing_still_respects_the_overall_cap(self):
        # Many distinct single-occurrence types, none individually over
        # MAX_ENTITIES_PER_TYPE_BEFORE_SUMMARIZING - per-type collapsing
        # alone wouldn't reduce this, so the overall truncation must still
        # apply.
        entities = [
            {"type": f"type_{i}", "value": f"value_{i}"} for i in range(MAX_EXTRACTED_ENTITIES + 10)
        ]
        result = validate_extracted_entities(entities, None)
        self.assertLessEqual(len(result), MAX_EXTRACTED_ENTITIES)

    def test_few_entities_of_a_repeated_type_are_not_collapsed(self):
        # At or below MAX_ENTITIES_PER_TYPE_BEFORE_SUMMARIZING, individual
        # entries are still useful and must not be summarized away, even
        # if some other type pushes the total over MAX_EXTRACTED_ENTITIES.
        few = [{"type": "vehicle_reference", "value": f"AD-{i}"} for i in range(3)]
        many_other_single_types = [
            {"type": f"type_{i}", "value": f"value_{i}"} for i in range(MAX_EXTRACTED_ENTITIES)
        ]
        result = validate_extracted_entities(few + many_other_single_types, None)
        vehicle_entries = [e for e in result if e["type"] == "vehicle_reference"]
        self.assertEqual(len(vehicle_entries), 3)


if __name__ == "__main__":
    unittest.main()
