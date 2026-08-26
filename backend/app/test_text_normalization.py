import unittest

from .services import _normalize_extracted_text


class NormalizeExtractedTextTestCase(unittest.TestCase):
    """Regression guard for a real production bug: a PDF's own text layer
    embedded a soft hyphen (U+00AD, invisible when rendered) mid-word at a
    line-wrap point - "Lastschriftverfahren" was extracted as
    "Lastschriftverfah­ren" by PyMuPDF's page.get_text(), which broke
    every downstream substring/regex check that looked for whole words
    like "fällig" split across the invisible character. Normalized once
    here, at the single point extracted text enters the system."""

    def test_soft_hyphen_is_stripped(self):
        raw = "Lastschriftverfah­ren"
        self.assertEqual(_normalize_extracted_text(raw), "Lastschriftverfahren")

    def test_soft_hyphen_inside_a_keyword_no_longer_breaks_substring_matching(self):
        raw = "Der Betrag ist f­ällig."
        normalized = _normalize_extracted_text(raw)
        self.assertIn("fällig", normalized)

    def test_zero_width_space_is_stripped(self):
        raw = "Versicherungsschein-Num​mer"
        self.assertEqual(_normalize_extracted_text(raw), "Versicherungsschein-Nummer")

    def test_zero_width_joiner_and_non_joiner_are_stripped(self):
        raw = "a‌b‍c"
        self.assertEqual(_normalize_extracted_text(raw), "abc")

    def test_bom_is_stripped(self):
        raw = "﻿Überweisen Sie den Betrag."
        self.assertEqual(_normalize_extracted_text(raw), "Überweisen Sie den Betrag.")

    def test_text_without_any_invisible_characters_is_unchanged(self):
        raw = "Ein ganz normaler Satz ohne unsichtbare Zeichen."
        self.assertEqual(_normalize_extracted_text(raw), raw)

    def test_empty_string_is_unchanged(self):
        self.assertEqual(_normalize_extracted_text(""), "")


if __name__ == "__main__":
    unittest.main()
