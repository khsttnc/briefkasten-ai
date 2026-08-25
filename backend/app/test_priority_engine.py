import unittest

from .priority_engine import PriorityInput, classify_priority


class FloorRuleTestCase(unittest.TestCase):
    """Anhörung and Mahnbescheid must never end up below 'high', regardless
    of how little else about the document raises its score."""

    def test_anhoerung_with_no_other_signals_is_at_least_high(self):
        result = classify_priority(PriorityInput(document_type="Anhörung"))
        self.assertEqual(result.priority_level, "high")

    def test_mahnbescheid_with_no_other_signals_is_at_least_high(self):
        result = classify_priority(PriorityInput(document_type="Mahnbescheid"))
        self.assertEqual(result.priority_level, "high")

    def test_floor_does_not_downgrade_an_already_critical_document(self):
        result = classify_priority(
            PriorityInput(
                sender_category="Gericht",
                document_type="Mahnbescheid",
                deadline_type="absolute",
                deadline_certainty="exact",
                payment_requested=True,
                objection_right_mentioned=True,
            )
        )
        self.assertEqual(result.priority_level, "critical")


class MahnungVsMahnbescheidTestCase(unittest.TestCase):
    """Mahnung (informal reminder) and Mahnbescheid (formal court order) are
    different document_type values with very different consequences - a
    Mahnung must NOT get the Mahnbescheid floor."""

    def test_mahnung_alone_is_not_floored_to_high(self):
        result = classify_priority(PriorityInput(document_type="Mahnung"))
        self.assertNotEqual(result.priority_level, "high")
        self.assertEqual(result.priority_level, "low")

    def test_mahnung_with_extra_signals_can_still_reach_high_on_its_own_merit(self):
        result = classify_priority(
            PriorityInput(
                sender_category="Inkasso",
                document_type="Mahnung",
                deadline_type="absolute",
                payment_requested=True,
            )
        )
        # 2 (Inkasso) + 1 (Mahnung) + 2 (absolute) + 1 (payment) = 6 -> high
        self.assertEqual(result.priority_level, "high")


class KuendigungTestCase(unittest.TestCase):
    """Kündigung (termination notice) must never be conflated with Mahnung
    (informal payment reminder) - they are unrelated document types with
    very different consequences, and this taxonomy gap was the root cause
    of a real employment-termination letter being misclassified as
    Mahnung."""

    def test_kuendigung_alone_scores_like_bescheid(self):
        result = classify_priority(PriorityInput(document_type="Kündigung"))
        # 2 (Kündigung) -> normal, same weight class as Bescheid.
        self.assertEqual(result.priority_level, "normal")

    def test_kuendigung_is_not_floored_to_high(self):
        result = classify_priority(PriorityInput(document_type="Kündigung"))
        self.assertNotEqual(result.priority_level, "high")

    def test_kuendigung_with_absolute_deadline_reaches_high(self):
        result = classify_priority(
            PriorityInput(
                document_type="Kündigung",
                deadline_type="absolute",
                deadline_certainty="exact",
            )
        )
        # 2 (Kündigung) + 2 (absolute deadline) = 4 -> high
        self.assertEqual(result.priority_level, "high")


class ScoringTestCase(unittest.TestCase):
    def test_no_signals_is_low(self):
        result = classify_priority(PriorityInput())
        self.assertEqual(result.priority_level, "low")

    def test_private_information_letter_is_low(self):
        result = classify_priority(
            PriorityInput(sender_category="Privat", document_type="Information")
        )
        self.assertEqual(result.priority_level, "low")

    def test_authority_with_change_notice_and_absolute_deadline_is_normal_or_above(self):
        result = classify_priority(
            PriorityInput(
                sender_category="Behörde",
                document_type="Änderungsbescheid",
                deadline_type="absolute",
                deadline_certainty="exact",
            )
        )
        # 2 (Behörde) + 2 (Änderungsbescheid) + 2 (absolute) = 6 -> high
        self.assertEqual(result.priority_level, "high")

    def test_unresolved_deadline_certainty_bumps_score_up(self):
        without_bump = classify_priority(
            PriorityInput(sender_category="Unternehmen", deadline_type="none")
        )
        with_bump = classify_priority(
            PriorityInput(
                sender_category="Unternehmen",
                deadline_type="relative",
                deadline_certainty="unknown_needs_review",
            )
        )
        self.assertGreater(
            self._score_from_reasoning(with_bump.priority_reasoning),
            self._score_from_reasoning(without_bump.priority_reasoning),
        )

    @staticmethod
    def _score_from_reasoning(reasoning: str) -> int:
        # "... -> Score N -> 'level'"
        marker = "Score "
        start = reasoning.index(marker) + len(marker)
        end = reasoning.index(" ->", start)
        return int(reasoning[start:end])


class ReasoningTestCase(unittest.TestCase):
    def test_reasoning_is_never_empty(self):
        result = classify_priority(PriorityInput())
        self.assertTrue(result.priority_reasoning)

    def test_reasoning_mentions_floor_when_applied(self):
        result = classify_priority(PriorityInput(document_type="Anhörung"))
        self.assertIn("Mindestpriorität", result.priority_reasoning)

    def test_reasoning_does_not_mention_floor_when_not_applied(self):
        result = classify_priority(
            PriorityInput(sender_category="Gericht", document_type="Mahnbescheid",
                          deadline_type="absolute", payment_requested=True,
                          objection_right_mentioned=True)
        )
        self.assertNotIn("Mindestpriorität", result.priority_reasoning)


if __name__ == "__main__":
    unittest.main()
