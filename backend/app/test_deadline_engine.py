import unittest
from datetime import date

from .deadline_engine import resolve_deadline


class AbsoluteDeadlineTestCase(unittest.TestCase):
    def test_numeric_date_is_exact(self):
        result = resolve_deadline("bis zum 15.09.2026")
        self.assertEqual(result.deadline_type, "absolute")
        self.assertEqual(result.deadline_certainty, "exact")
        self.assertEqual(result.deadline_estimated_date, date(2026, 9, 15))

    def test_written_month_date_is_exact(self):
        result = resolve_deadline("spätestens bis 15. September 2026 zu antworten")
        self.assertEqual(result.deadline_type, "absolute")
        self.assertEqual(result.deadline_certainty, "exact")
        self.assertEqual(result.deadline_estimated_date, date(2026, 9, 15))

    def test_never_fabricates_a_date_for_an_invalid_calendar_date(self):
        # 31.02. does not exist - must not silently round to a nearby date.
        result = resolve_deadline("bis zum 31.02.2026")
        self.assertEqual(result.deadline_type, "none")
        self.assertEqual(result.deadline_certainty, "unknown_needs_review")
        self.assertIsNone(result.deadline_estimated_date)


class RelativeDeadlineTestCase(unittest.TestCase):
    def test_relative_days_without_document_date_is_unresolved(self):
        # No Bescheiddatum available - must not guess a date.
        result = resolve_deadline("innerhalb von 14 Tagen")
        self.assertEqual(result.deadline_type, "relative")
        self.assertEqual(result.deadline_certainty, "unknown_needs_review")
        self.assertIsNone(result.deadline_estimated_date)

    def test_relative_days_post_2025_uses_4_day_zustellfiktion(self):
        # VwVfG §41(2) etc as amended: 4 days after posting, from 2025-01-01.
        result = resolve_deadline("innerhalb von 14 Tagen", document_date=date(2026, 1, 10))
        self.assertEqual(result.deadline_type, "relative")
        self.assertEqual(result.deadline_certainty, "estimated")
        # deemed delivery: 2026-01-10 + 4 = 2026-01-14; +14 days = 2026-01-28
        self.assertEqual(result.deadline_estimated_date, date(2026, 1, 28))

    def test_relative_days_pre_2025_uses_3_day_zustellfiktion(self):
        result = resolve_deadline("innerhalb von 14 Tagen", document_date=date(2024, 6, 1))
        self.assertEqual(result.deadline_certainty, "estimated")
        # deemed delivery: 2024-06-01 + 3 = 2024-06-04; +14 days = 2024-06-18
        self.assertEqual(result.deadline_estimated_date, date(2024, 6, 18))

    def test_relative_weeks(self):
        result = resolve_deadline("binnen 2 Wochen", document_date=date(2026, 1, 10))
        # deemed delivery: 2026-01-14; +14 days (2 weeks) = 2026-01-28
        self.assertEqual(result.deadline_estimated_date, date(2026, 1, 28))

    def test_relative_spelled_out_single_month(self):
        result = resolve_deadline("innerhalb eines Monats", document_date=date(2026, 1, 10))
        self.assertEqual(result.deadline_certainty, "estimated")
        # deemed delivery: 2026-01-14; +1 month = 2026-02-14
        self.assertEqual(result.deadline_estimated_date, date(2026, 2, 14))

    def test_relative_month_end_overflow_is_clamped(self):
        result = resolve_deadline("innerhalb eines Monats", document_date=date(2026, 1, 27))
        # deemed delivery: 2026-01-31; +1 month -> Feb has no 31st -> 2026-02-28
        self.assertEqual(result.deadline_estimated_date, date(2026, 2, 28))


class SpaetestensAndSpelledNumbersTestCase(unittest.TestCase):
    """Regression test for: a real Kündigung's §38 SGB III Arbeitsagentur
    reporting duty (Sperrzeit risk) used "spätestens drei Tage nach ..."
    phrasing, which the relative-deadline regex did not recognize at all
    (only "innerhalb (von)"/"binnen" triggers, and only spelled-out "one",
    not "drei")."""

    def test_spaetestens_with_spelled_out_drei_tage(self):
        result = resolve_deadline(
            "spätestens drei Tage nach Zugang dieser Kündigung",
            document_date=date(2026, 1, 10),
        )
        self.assertEqual(result.deadline_type, "relative")
        self.assertEqual(result.deadline_certainty, "estimated")
        # deemed delivery: 2026-01-14; +3 days = 2026-01-17
        self.assertEqual(result.deadline_estimated_date, date(2026, 1, 17))

    def test_spaetestens_without_document_date_is_unresolved(self):
        result = resolve_deadline("spätestens drei Tage nach Kenntnis der Kündigung")
        self.assertEqual(result.deadline_type, "relative")
        self.assertEqual(result.deadline_certainty, "unknown_needs_review")

    def test_spelled_out_zwei_tage(self):
        result = resolve_deadline("innerhalb von zwei Tagen", document_date=date(2026, 1, 10))
        # deemed delivery: 2026-01-14; +2 days = 2026-01-16
        self.assertEqual(result.deadline_estimated_date, date(2026, 1, 16))

    def test_spelled_out_numbers_up_to_zehn(self):
        result = resolve_deadline("binnen zehn Tagen", document_date=date(2026, 1, 10))
        # deemed delivery: 2026-01-14; +10 days = 2026-01-24
        self.assertEqual(result.deadline_estimated_date, date(2026, 1, 24))


class NoOrUnclearDeadlineTestCase(unittest.TestCase):
    def test_empty_text_is_none_and_exact(self):
        result = resolve_deadline(None)
        self.assertEqual(result.deadline_type, "none")
        self.assertEqual(result.deadline_certainty, "exact")
        self.assertIsNone(result.deadline_estimated_date)

    def test_blank_text_is_none_and_exact(self):
        result = resolve_deadline("   ")
        self.assertEqual(result.deadline_type, "none")
        self.assertEqual(result.deadline_certainty, "exact")

    def test_unparseable_mention_is_flagged_for_review(self):
        # A deadline is plausibly mentioned ("so schnell wie möglich") but in
        # a form we don't confidently parse - must not be dropped silently.
        result = resolve_deadline("bitte so schnell wie möglich antworten")
        self.assertEqual(result.deadline_type, "none")
        self.assertEqual(result.deadline_certainty, "unknown_needs_review")
        self.assertIsNone(result.deadline_estimated_date)

    def test_raw_text_is_passed_through_unchanged(self):
        raw = "innerhalb von 14 Tagen"
        result = resolve_deadline(raw, document_date=date(2026, 1, 10))
        self.assertEqual(result.deadline_raw_text, raw)


class MultipleDeadlinesDetectedTestCase(unittest.TestCase):
    """Option A from review: a document with more than one distinct
    deadline phrase must never silently resolve to a single confident
    date - it degrades to unknown_needs_review even if the chosen phrase
    itself parses cleanly, same fail-closed treatment as an unparseable
    phrase."""

    def test_downgrades_an_otherwise_exact_absolute_date(self):
        result = resolve_deadline("bis zum 15.09.2026", multiple_deadlines_detected=True)
        self.assertEqual(result.deadline_type, "absolute")
        self.assertEqual(result.deadline_certainty, "unknown_needs_review")
        self.assertIsNone(result.deadline_estimated_date)

    def test_downgrades_an_otherwise_estimated_relative_date(self):
        result = resolve_deadline(
            "innerhalb von 14 Tagen",
            document_date=date(2026, 1, 10),
            multiple_deadlines_detected=True,
        )
        self.assertEqual(result.deadline_type, "relative")
        self.assertEqual(result.deadline_certainty, "unknown_needs_review")
        self.assertIsNone(result.deadline_estimated_date)

    def test_already_unresolved_relative_deadline_is_unaffected(self):
        # No document_date -> already unknown_needs_review regardless of the
        # flag; must not change shape further.
        without_flag = resolve_deadline("innerhalb von 14 Tagen")
        with_flag = resolve_deadline("innerhalb von 14 Tagen", multiple_deadlines_detected=True)
        self.assertEqual(without_flag, with_flag)

    def test_false_flag_does_not_change_a_single_clean_deadline(self):
        result = resolve_deadline("bis zum 15.09.2026", multiple_deadlines_detected=False)
        self.assertEqual(result.deadline_certainty, "exact")
        self.assertEqual(result.deadline_estimated_date, date(2026, 9, 15))

    def test_raw_text_still_passed_through_when_downgraded(self):
        raw = "bis zum 15.09.2026"
        result = resolve_deadline(raw, multiple_deadlines_detected=True)
        self.assertEqual(result.deadline_raw_text, raw)


if __name__ == "__main__":
    unittest.main()
