import unittest

from .entity_validation import validate_extracted_entities

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


if __name__ == "__main__":
    unittest.main()
