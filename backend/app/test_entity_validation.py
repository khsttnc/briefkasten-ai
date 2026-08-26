import unittest

from .entity_validation import (
    MAX_ENTITIES_PER_TYPE_BEFORE_SUMMARIZING,
    MAX_EXTRACTED_ENTITIES,
    validate_explanatory_text,
    validate_extracted_entities,
    validate_important_dates,
    validate_intelligence_signals,
)

SOURCE_TEXT = (
    "Ihre Kfz-Versicherung AD-5409239121 (bitte stets angeben)\n"
    "Amtl. Kennzeichen: BE-ZL 37, ADAC-Mitgliedsnummer 734333034\n"
    "Sehr geehrter Herr Tuetuenue,\n"
)

# A real-shaped Kündigung (termination notice) that mentions a date and a
# relative reporting deadline, but no payment of any kind - used across the
# regression tests below for the exact bug class reported in production:
# a hallucinated date substitution (2020 -> 2023) and an invented
# payment_requested=true/"pay within 15 days" claim on a document that
# never asks for money.
KUENDIGUNG_TEXT = (
    "Kündigung des Arbeitsverhältnisses\n"
    "Berlin, den 10.01.2020\n"
    "Sehr geehrte Frau Mustermann,\n"
    "hiermit kündigen wir das Arbeitsverhältnis zum 28.02.2020.\n"
    "Bitte melden Sie sich innerhalb von 3 Tagen nach Zugang dieser "
    "Kündigung bei der Agentur für Arbeit, um eine Sperrzeit zu vermeiden.\n"
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


class DateTypedExtractedEntityTestCase(unittest.TestCase):
    """extracted_entities date values (see _is_date_type) must be checked
    against the source the same way code/number entities are - not
    currently produced by the extraction prompt, but not silently exempt
    either if it ever is."""

    def test_date_matching_source_is_accepted(self):
        entities = [{"type": "important_date", "value": "10.01.2020"}]
        self.assertEqual(validate_extracted_entities(entities, KUENDIGUNG_TEXT), entities)

    def test_date_not_in_source_is_rejected(self):
        # The exact reported production bug: the model copies a source date
        # (2020) as a different year (2023) that never appears in the text.
        entities = [{"type": "important_date", "value": "10.01.2023"}]
        self.assertEqual(validate_extracted_entities(entities, KUENDIGUNG_TEXT), [])

    def test_unparseable_date_value_is_rejected(self):
        entities = [{"type": "important_date", "value": "irgendwann"}]
        self.assertEqual(validate_extracted_entities(entities, KUENDIGUNG_TEXT), [])


class ImportantDatesValidationTestCase(unittest.TestCase):
    def test_date_present_in_source_is_kept(self):
        result = validate_important_dates(["10.01.2020"], KUENDIGUNG_TEXT)
        self.assertEqual(result, ["10.01.2020"])

    def test_hallucinated_year_is_dropped(self):
        result = validate_important_dates(["10.01.2023"], KUENDIGUNG_TEXT)
        self.assertEqual(result, [])

    def test_iso_date_matching_source_is_kept(self):
        result = validate_important_dates(["2020-02-28"], KUENDIGUNG_TEXT)
        self.assertEqual(result, ["2020-02-28"])

    def test_entry_without_any_parseable_date_is_kept(self):
        # Nothing to verify - not the class of bug this guards against.
        result = validate_important_dates(["unbestimmter Zeitpunkt"], KUENDIGUNG_TEXT)
        self.assertEqual(result, ["unbestimmter Zeitpunkt"])

    def test_none_and_empty_return_empty_list(self):
        self.assertEqual(validate_important_dates(None, KUENDIGUNG_TEXT), [])
        self.assertEqual(validate_important_dates([], KUENDIGUNG_TEXT), [])


class IntelligenceSignalDateValidationTestCase(unittest.TestCase):
    """Regression guard for the reported production bug: a date on the
    source document (2020) coming back from the model as a different,
    non-existent year (2023) in document_date/effective_date/
    deadline_raw_text - none of these were checked against the source text
    at all before validate_intelligence_signals existed."""

    def test_document_date_matching_source_is_kept(self):
        raw = {"document_date": "2020-01-10"}
        result = validate_intelligence_signals(raw, KUENDIGUNG_TEXT)
        self.assertEqual(result["document_date"], "2020-01-10")

    def test_document_date_with_hallucinated_year_is_dropped(self):
        raw = {"document_date": "2023-01-10"}
        result = validate_intelligence_signals(raw, KUENDIGUNG_TEXT)
        self.assertIsNone(result["document_date"])

    def test_effective_date_with_hallucinated_year_is_dropped(self):
        raw = {"effective_date": "2023-02-28"}
        result = validate_intelligence_signals(raw, KUENDIGUNG_TEXT)
        self.assertIsNone(result["effective_date"])

    def test_effective_date_matching_source_is_kept(self):
        raw = {"effective_date": "2020-02-28"}
        result = validate_intelligence_signals(raw, KUENDIGUNG_TEXT)
        self.assertEqual(result["effective_date"], "2020-02-28")

    def test_deadline_raw_text_with_absolute_date_not_in_source_is_dropped(self):
        raw = {"deadline_raw_text": "bis zum 15.09.2026"}
        result = validate_intelligence_signals(raw, KUENDIGUNG_TEXT)
        self.assertIsNone(result["deadline_raw_text"])

    def test_deadline_raw_text_with_absolute_date_in_source_is_kept(self):
        raw = {"deadline_raw_text": "zum 28.02.2020"}
        result = validate_intelligence_signals(raw, KUENDIGUNG_TEXT)
        self.assertEqual(result["deadline_raw_text"], "zum 28.02.2020")

    def test_relative_deadline_phrase_has_no_date_to_verify_and_is_kept(self):
        raw = {"deadline_raw_text": "innerhalb von 3 Tagen nach Zugang dieser Kündigung"}
        result = validate_intelligence_signals(raw, KUENDIGUNG_TEXT)
        self.assertEqual(
            result["deadline_raw_text"], "innerhalb von 3 Tagen nach Zugang dieser Kündigung"
        )

    def test_non_dict_raw_response_passes_through(self):
        self.assertEqual(validate_intelligence_signals("not a dict", KUENDIGUNG_TEXT), {})
        self.assertEqual(validate_intelligence_signals(None, KUENDIGUNG_TEXT), {})


class PaymentRequestedValidationTestCase(unittest.TestCase):
    """Regression guard for the reported production bug: payment_requested
    coming back true, with an action_summary telling the reader to
    "pay within 15 days", on a document (a plain Kündigung) that never
    mentions any payment at all."""

    def test_payment_requested_without_any_evidence_is_downgraded_to_false(self):
        raw = {
            "payment_requested": True,
            "action_summary": "15 gün içinde ödeyin.",
        }
        result = validate_intelligence_signals(raw, KUENDIGUNG_TEXT)
        self.assertFalse(result["payment_requested"])

    def test_action_summary_is_cleared_when_payment_claim_is_dropped(self):
        raw = {
            "payment_requested": True,
            "action_summary": "15 gün içinde ödeyin.",
        }
        result = validate_intelligence_signals(raw, KUENDIGUNG_TEXT)
        self.assertIsNone(result["action_summary"])

    def test_action_summary_without_payment_wording_is_kept_even_when_downgraded(self):
        raw = {
            "payment_requested": True,
            "action_summary": "Bitte fristgerecht bei der Agentur für Arbeit melden.",
        }
        result = validate_intelligence_signals(raw, KUENDIGUNG_TEXT)
        self.assertFalse(result["payment_requested"])
        self.assertEqual(
            result["action_summary"], "Bitte fristgerecht bei der Agentur für Arbeit melden."
        )

    def test_payment_requested_with_textual_evidence_is_kept(self):
        # Needs both an amount AND a payment-action verb (see
        # _has_payment_evidence) - a bare "Betrag" mention alone is no
        # longer sufficient evidence (see PaymentEvidenceTighteningTestCase).
        text_with_payment = KUENDIGUNG_TEXT + "Der Betrag von 129,90 EUR ist zu zahlen.\n"
        raw = {
            "payment_requested": True,
            "action_summary": "Ödemeyi yapın.",
        }
        result = validate_intelligence_signals(raw, text_with_payment)
        self.assertTrue(result["payment_requested"])
        self.assertEqual(result["action_summary"], "Ödemeyi yapın.")

    def test_payment_requested_false_is_left_untouched(self):
        raw = {"payment_requested": False, "action_summary": "Fristgerecht melden."}
        result = validate_intelligence_signals(raw, KUENDIGUNG_TEXT)
        self.assertFalse(result["payment_requested"])
        self.assertEqual(result["action_summary"], "Fristgerecht melden.")


# A real-shaped Antragsformular (application form) for a credit-card debt
# insurance product - mentions Kreditkarte/Bank/Versicherung by name (what
# the form is ABOUT) but never actually asks the reader to pay anything.
# This is the exact production false positive that motivated tightening the
# payment-evidence check: the old broad keyword list ("Betrag", "EUR",
# "Rechnung") would have accepted this text as evidence of a payment
# demand, and it also contains no date at all, matching the reported
# hallucinated-date incident.
ANTRAGSFORMULAR_TEXT = (
    "Antragsformular für vorübergehende Arbeitsunfähigkeit\n"
    "Restschuldversicherung zu Ihrer Kreditkarte - Advanzia Bank\n"
    "Bitte füllen Sie dieses Formular vollständig aus und senden Sie es "
    "zusammen mit einer ärztlichen Bescheinigung zurück.\n"
    "Crawford & Company im Auftrag der Versicherung.\n"
)

# The real production over-correction case (the excerpt provided): a
# EUROPA-go vehicle insurance contract-termination notice (Vertragsaufhebung)
# with a clearly-stated effective_date and a neutral, non-demanding mention
# of a separate invoice. The broader payment keyword list (including
# "fatura") previously dropped the entire (correct) explanation for this
# document just because a plausible Turkish translation of "Beitragsrechnung"
# ("prim faturası") contains "fatura" - even though nothing here asks the
# reader to pay anything or by when.
EUROPA_GO_VERTRAGSAUFHEBUNG_TEXT = (
    "Ihr Vertrag für das Fahrzeug mit dem amtlichen Kennzeichen BE-EG 961 "
    "endet am 10.12.2025. Die Abrechnung entnehmen Sie bitte der separaten "
    "Beitragsrechnung.\n"
)


class PaymentEvidenceTighteningTestCase(unittest.TestCase):
    """Regression guard for the reported production bug: a document merely
    naming a bank, credit card, or insurance product must not be accepted
    as evidence of an actual payment demand - only an amount AND a
    payment-action verb, together, count."""

    def test_amount_and_verb_together_is_sufficient_evidence(self):
        raw = {"payment_requested": True, "action_summary": "Ödeyin."}
        text = "Bitte zahlen Sie den Betrag von 50,00 EUR bis zum Fälligkeitsdatum."
        result = validate_intelligence_signals(raw, text)
        self.assertTrue(result["payment_requested"])

    def test_bank_credit_card_insurance_wording_alone_is_not_evidence(self):
        raw = {"payment_requested": True, "action_summary": "15 gün içinde ödeyin."}
        result = validate_intelligence_signals(raw, ANTRAGSFORMULAR_TEXT)
        self.assertFalse(result["payment_requested"])
        self.assertIsNone(result["action_summary"])

    def test_amount_without_action_verb_is_not_sufficient_evidence(self):
        raw = {"payment_requested": True, "action_summary": "Ödeyin."}
        text = KUENDIGUNG_TEXT + "Ihr aktueller Kontostand betrug zuletzt 50,00 EUR.\n"
        result = validate_intelligence_signals(raw, text)
        self.assertFalse(result["payment_requested"])

    def test_action_verb_without_amount_is_not_sufficient_evidence(self):
        raw = {"payment_requested": True, "action_summary": "Ödeyin."}
        text = KUENDIGUNG_TEXT + "Der Betrag ist fällig.\n"
        result = validate_intelligence_signals(raw, text)
        self.assertFalse(result["payment_requested"])


class ExplanatoryTextValidationTestCase(unittest.TestCase):
    """validate_explanatory_text is the only guard for summary/
    turkish_explanation - fields with no structured counterpart, produced
    by every AI provider regardless of whether document_intelligence.
    SIGNAL_KEYS are populated at all (see claude_provider.py before this
    fix). Regression guard for the reported production bug: an
    Antragsformular came back with four fabricated dates and a "pay within
    15 days" narrative baked directly into turkish_explanation."""

    def test_text_without_dates_or_payment_claims_is_kept(self):
        text = "Bitte füllen Sie das Formular aus und senden Sie es zurück."
        self.assertEqual(validate_explanatory_text(text, ANTRAGSFORMULAR_TEXT), text)

    def test_text_with_date_not_in_source_is_dropped(self):
        text = "Der Antrag muss bis zum 20.01.2026 eingereicht werden."
        self.assertIsNone(validate_explanatory_text(text, ANTRAGSFORMULAR_TEXT))

    def test_text_with_date_present_in_source_is_kept(self):
        text = "Kündigung zum 28.02.2020."
        self.assertEqual(validate_explanatory_text(text, KUENDIGUNG_TEXT), text)

    def test_fabricated_payment_narrative_without_evidence_is_dropped(self):
        # The exact reported production bug, translated: "this document
        # contains an invoice and requires the customer to make their
        # credit card bill payments" / "pay within 15 days".
        text = (
            "Bu belge, müşterinin kredi kartı fatura ödemelerini yapması "
            "gereken bir fatura ve 15 gün içinde ödeme süresi içerir."
        )
        self.assertIsNone(validate_explanatory_text(text, ANTRAGSFORMULAR_TEXT))

    def test_payment_wording_with_real_evidence_is_kept(self):
        text = "Lütfen 129,90 EUR tutarını ödeyin."
        source = KUENDIGUNG_TEXT + "Der Betrag von 129,90 EUR ist zu zahlen.\n"
        self.assertEqual(validate_explanatory_text(text, source), text)

    def test_none_and_blank_input_returns_none(self):
        self.assertIsNone(validate_explanatory_text(None, ANTRAGSFORMULAR_TEXT))
        self.assertIsNone(validate_explanatory_text("   ", ANTRAGSFORMULAR_TEXT))
        self.assertIsNone(validate_explanatory_text(123, ANTRAGSFORMULAR_TEXT))


class OverAggressiveValidationRegressionTestCase(unittest.TestCase):
    """Regression guard for the reported over-correction bug: a real
    EUROPA-go Vertragsaufhebung (vehicle insurance contract termination),
    with a genuine, source-backed effective_date and a purely informational
    mention of a separate invoice, had its correct explanation dropped
    entirely and its effective_date never reached the reader. The
    validation layer's job is to reject UNVERIFIABLE content, not to reject
    verifiable content that happens to mention billing vocabulary in
    passing - the previous, broader Turkish keyword list ("fatura", "tutar",
    "borç", "€"/"eur") conflated the two."""

    def test_neutral_invoice_mention_is_kept_not_treated_as_payment_demand(self):
        # Plausible Turkish rendering of "Die Abrechnung entnehmen Sie
        # bitte der separaten Beitragsrechnung" - references an invoice
        # document without demanding payment or stating a deadline.
        text = (
            "BE-EG 961 plakalı aracınıza ait sigorta sözleşmeniz 10.12.2025 "
            "tarihinde sona eriyor. Hesaplama bilgilerini ayrı gönderilen "
            "prim faturasında bulabilirsiniz."
        )
        self.assertEqual(
            validate_explanatory_text(text, EUROPA_GO_VERTRAGSAUFHEBUNG_TEXT), text
        )

    def test_actual_payment_demand_is_still_dropped_without_evidence(self):
        # Sanity check that narrowing the keyword list to the "öde" stem
        # didn't also reopen the original bug: a genuine (fabricated, in
        # this case) payment demand on the same source must still be
        # dropped, since the source has no amount+verb evidence at all.
        text = "15 gün içinde ödeyin."
        self.assertIsNone(
            validate_explanatory_text(text, EUROPA_GO_VERTRAGSAUFHEBUNG_TEXT)
        )

    def test_effective_date_stated_in_source_is_verified_and_kept(self):
        raw = {"effective_date": "2025-12-10"}
        result = validate_intelligence_signals(raw, EUROPA_GO_VERTRAGSAUFHEBUNG_TEXT)
        self.assertEqual(result["effective_date"], "2025-12-10")

    def test_important_date_stated_in_source_is_verified_and_kept(self):
        result = validate_important_dates(["10.12.2025"], EUROPA_GO_VERTRAGSAUFHEBUNG_TEXT)
        self.assertEqual(result, ["10.12.2025"])


# A real-shaped CHECK24 vehicle insurance QUOTE (Angebot/Tarifübersicht,
# not a bill): states the selected tariff, its start date, and the
# monthly premium as plain product information. No demand verb
# ("zu zahlen"/"fällig"/etc.) anywhere - a real quote document doesn't
# read like a Mahnung, it reads like a price sheet.
CHECK24_INSURANCE_QUOTE_TEXT = (
    "CHECK24 Kfz-Versicherungsvergleich - Ihr Angebot\n"
    "Fahrzeugdaten, Ihre Praeferenzen und der gewaehlte Tarif:\n"
    "Gewaehlter Tarif: ADAC Basis\n"
    "Versicherungsbeginn: 03.07.2026\n"
    "Monatlicher Beitrag: 71,19 EUR\n"
)


class PaymentInformationVsDemandRegressionTestCase(unittest.TestCase):
    """Regression guard for the reported over-correction bug: an insurance
    QUOTE stating a monthly premium as plain product information ("aylık
    prim 71,19 €") had its entire correct explanation dropped, because the
    old check required an amount AND a separate demand verb ("zu zahlen"
    etc.) to co-occur in the source - a quote document never uses that
    kind of wording, it's not a bill. The source-stated amount itself
    (verifiable) is what should decide this, not the presence of a
    command verb the document was never going to contain."""

    def test_informational_premium_amount_matching_source_is_kept(self):
        text = (
            "Belge, müşterinin araç bilgileri, tercihleri ve seçtiği sigorta "
            "tarifesi hakkında bilgi verir. Seçilen sigorta ADAC Basis ile "
            "03.07.2026 tarihinden itibaren yürürlüğe girer ve aylık 71,19 € "
            "prim ödenecektir."
        )
        self.assertEqual(
            validate_explanatory_text(text, CHECK24_INSURANCE_QUOTE_TEXT), text
        )

    def test_premium_amount_not_matching_source_is_still_dropped(self):
        # Sanity check: verifying the amount, not just detecting "öde"
        # wording, must still fail closed on a genuinely fabricated
        # number - the fix must not become "always keep if it mentions an
        # amount at all".
        text = "Aylık 199,99 € prim ödenecektir."
        self.assertIsNone(
            validate_explanatory_text(text, CHECK24_INSURANCE_QUOTE_TEXT)
        )

    def test_differently_formatted_matching_amount_is_still_recognized(self):
        # "71.19" (dot decimal) vs source's "71,19" (comma decimal) -
        # same amount, different formatting, must still match.
        text = "Aylık prim: 71.19 EUR."
        self.assertEqual(
            validate_explanatory_text(text, CHECK24_INSURANCE_QUOTE_TEXT), text
        )


if __name__ == "__main__":
    unittest.main()
