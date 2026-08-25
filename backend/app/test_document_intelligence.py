import unittest
from datetime import date
from unittest.mock import patch

from .document_intelligence import derive_intelligence_fields


class MissingOrEmptyInputTestCase(unittest.TestCase):
    """The LLM prompt work that populates these signal keys hasn't landed
    yet, and an AI-provider call can fail outright - both must degrade to
    safe defaults, never raise."""

    def test_none_raw_response_yields_safe_defaults(self):
        fields = derive_intelligence_fields(None)
        self.assertIsNone(fields["sender_category"])
        self.assertIsNone(fields["document_type"])
        self.assertEqual(fields["deadline_type"], "none")
        self.assertEqual(fields["deadline_certainty"], "exact")
        self.assertIsNone(fields["deadline_estimated_date"])
        self.assertEqual(fields["priority_level"], "low")
        self.assertFalse(fields["requires_action"])

    def test_empty_dict_yields_safe_defaults(self):
        fields = derive_intelligence_fields({})
        self.assertEqual(fields["deadline_type"], "none")
        self.assertEqual(fields["priority_level"], "low")

    def test_non_dict_raw_response_yields_safe_defaults(self):
        # analysis_result.raw_response can in principle be a non-dict value
        # (services.py itself wraps it, but this must not depend on that).
        fields = derive_intelligence_fields("not a dict")  # type: ignore[arg-type]
        self.assertEqual(fields["deadline_type"], "none")
        self.assertEqual(fields["priority_level"], "low")

    def test_unrecognized_keys_are_ignored_not_fatal(self):
        fields = derive_intelligence_fields({"document_type": "letter", "some_other_key": 123})
        # "document_type" here is DocumentAIAnalysis's free-form LLM label,
        # not the "classified_document_type" key this module reads.
        self.assertIsNone(fields["document_type"])
        self.assertEqual(fields["priority_level"], "low")


class MalformedSignalTypesTestCase(unittest.TestCase):
    """Wrong-typed values for a signal key must be treated as absent, not
    raise or get coerced into something misleading."""

    def test_non_string_sender_category_is_ignored(self):
        fields = derive_intelligence_fields({"sender_category": 42})
        self.assertIsNone(fields["sender_category"])

    def test_non_bool_requires_action_is_treated_as_false(self):
        fields = derive_intelligence_fields({"requires_action": "yes"})
        self.assertFalse(fields["requires_action"])

    def test_malformed_document_date_does_not_break_relative_deadline_resolution(self):
        fields = derive_intelligence_fields(
            {"deadline_raw_text": "innerhalb von 14 Tagen", "document_date": "not-a-date"}
        )
        self.assertEqual(fields["deadline_type"], "relative")
        self.assertEqual(fields["deadline_certainty"], "unknown_needs_review")
        self.assertIsNone(fields["deadline_estimated_date"])


class FullValidPayloadTestCase(unittest.TestCase):
    def test_full_payload_produces_expected_fields(self):
        fields = derive_intelligence_fields(
            {
                "sender_category": "Behörde",
                "sender_institution": "Jobcenter Berlin Mitte",
                "classified_document_type": "Änderungsbescheid",
                "deadline_raw_text": "innerhalb von 14 Tagen",
                "document_date": "2026-01-10",
                "requires_action": True,
                "payment_requested": False,
                "objection_right_mentioned": True,
                "action_summary": "Widerspruch einlegen falls Betrag falsch.",
            }
        )
        self.assertEqual(fields["sender_category"], "Behörde")
        self.assertEqual(fields["sender_institution"], "Jobcenter Berlin Mitte")
        self.assertEqual(fields["document_type"], "Änderungsbescheid")
        self.assertEqual(fields["deadline_type"], "relative")
        self.assertEqual(fields["deadline_certainty"], "estimated")
        self.assertEqual(fields["deadline_estimated_date"], date(2026, 1, 28))
        self.assertTrue(fields["requires_action"])
        self.assertEqual(fields["action_summary"], "Widerspruch einlegen falls Betrag falsch.")
        # Behörde(2) + Änderungsbescheid(2) + objection(1) + relative(1) = 6 -> high
        self.assertEqual(fields["priority_level"], "high")


class EffectiveDateTestCase(unittest.TestCase):
    """Regression test for: a real Kündigung's employment end date was at
    risk of being conflated with the reader's actual action deadline (the
    §38 SGB III Arbeitsagentur reporting duty). effective_date must be
    parsed and returned independently of deadline_raw_text/deadline_type,
    and never feed into deadline resolution."""

    def test_effective_date_is_parsed_independently_of_deadline(self):
        fields = derive_intelligence_fields(
            {
                "classified_document_type": "Kündigung",
                "deadline_raw_text": "spätestens drei Tage nach Zugang dieser Kündigung",
                "document_date": "2026-01-10",
                "effective_date": "2026-04-27",
            }
        )
        self.assertEqual(fields["document_type"], "Kündigung")
        self.assertEqual(fields["effective_date"], date(2026, 4, 27))
        # deemed delivery: 2026-01-14; +3 days = 2026-01-17 - unaffected by
        # effective_date, which is a completely separate concept.
        self.assertEqual(fields["deadline_type"], "relative")
        self.assertEqual(fields["deadline_estimated_date"], date(2026, 1, 17))

    def test_missing_effective_date_is_none(self):
        fields = derive_intelligence_fields({"classified_document_type": "Kündigung"})
        self.assertIsNone(fields["effective_date"])

    def test_malformed_effective_date_is_ignored_not_fatal(self):
        fields = derive_intelligence_fields({"effective_date": "nächstmöglicher Zeitpunkt"})
        self.assertIsNone(fields["effective_date"])


class MultipleDeadlinesSignalTestCase(unittest.TestCase):
    """Option A from review: multiple_deadlines_detected must flow through
    to resolve_deadline() and downgrade an otherwise-confident date, and
    the resulting unknown_needs_review certainty must still bump the
    priority score the same way an unparseable deadline does."""

    def test_true_flag_downgrades_an_otherwise_exact_date(self):
        fields = derive_intelligence_fields(
            {
                "deadline_raw_text": "bis zum 15.09.2026",
                "multiple_deadlines_detected": True,
            }
        )
        self.assertEqual(fields["deadline_type"], "absolute")
        self.assertEqual(fields["deadline_certainty"], "unknown_needs_review")
        self.assertIsNone(fields["deadline_estimated_date"])

    def test_missing_flag_defaults_to_false_and_does_not_downgrade(self):
        fields = derive_intelligence_fields({"deadline_raw_text": "bis zum 15.09.2026"})
        self.assertEqual(fields["deadline_certainty"], "exact")
        self.assertEqual(fields["deadline_estimated_date"], date(2026, 9, 15))

    def test_non_bool_flag_value_is_treated_as_false(self):
        fields = derive_intelligence_fields(
            {"deadline_raw_text": "bis zum 15.09.2026", "multiple_deadlines_detected": "true"}
        )
        self.assertEqual(fields["deadline_certainty"], "exact")


class EngineFailureIsolationTestCase(unittest.TestCase):
    """Even if a downstream engine misbehaves unexpectedly, this module must
    still return a safe, complete result rather than propagate."""

    def test_priority_engine_exception_falls_back_to_safe_defaults(self):
        with patch(
            "app.document_intelligence.classify_priority",
            side_effect=RuntimeError("boom"),
        ):
            fields = derive_intelligence_fields({"sender_category": "Gericht"})
        self.assertEqual(fields["priority_level"], "low")
        self.assertEqual(fields["deadline_type"], "none")

    def test_deadline_engine_exception_falls_back_to_safe_defaults(self):
        with patch(
            "app.document_intelligence.resolve_deadline",
            side_effect=RuntimeError("boom"),
        ):
            fields = derive_intelligence_fields({"deadline_raw_text": "bis zum 15.09.2026"})
        self.assertEqual(fields["deadline_type"], "none")
        self.assertEqual(fields["priority_level"], "low")


if __name__ == "__main__":
    unittest.main()
