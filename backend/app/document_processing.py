import logging
import re
from typing import Optional

from .ai_service import AIAnalysisResult, AIService

logger = logging.getLogger("briefkasten.document_processing")

# Joins consecutive PDF/OCR pages in services.py (both the native-text and
# OCR extraction paths). Three real newlines rather than an exotic marker
# string like "[PAGE BREAK]": a human reading the OCR preview (now shown in
# full, see App.tsx) just sees a paragraph-sized gap, nothing that looks
# broken, while detect_possible_multiple_documents below can still count it
# reliably. Also fixes a real bug: the native-text path used to concatenate
# pages with no separator at all (`text += page.get_text()`), which could
# glue the last word of one page to the first word of the next.
PAGE_SEPARATOR = "\n\n\n"

# A document's extracted text beyond this length is not sent to the AI
# provider as-is. Real, measured ceiling (not a guess - see
# scratchpad test_nvidia_context.py run against the live NVIDIA API):
# nvidia/nemotron-3-nano-30b-a3b's actual max context is 1,000,000 tokens
# (confirmed by the API's own rejection message at ~1.003M tokens), which
# for German text is roughly 4 chars/token - a real 206,540-character
# document (the incident that originally motivated truncation) only used
# 54,317 of those tokens (5.4%). This constant is deliberately set far
# below the true ~3.9M-char ceiling: at 2,000,000 chars a real test call
# took 52.6s and the model's completion hit its max_tokens cap outright
# (a truncated-response risk in its own right, independent of context
# size) - 500k chars keeps well clear of both the latency growth and that
# risk while comfortably covering every realistic use case, including a
# ~200-page contract or insurance policy. A single named constant so the
# budget is easy to retune later if real usage patterns demand it.
MAX_ANALYSIS_TEXT_CHARS = 500_000

# How MAX_ANALYSIS_TEXT_CHARS is split between the start and end of the
# document when it must be truncated. Weighted toward the head (cover
# letter, sender, key dates); a smaller tail share is kept in case a
# signature or closing notice carries something relevant instead. Must sum
# to MAX_ANALYSIS_TEXT_CHARS.
TRUNCATION_HEAD_CHARS = 350_000
TRUNCATION_TAIL_CHARS = 150_000

assert TRUNCATION_HEAD_CHARS + TRUNCATION_TAIL_CHARS == MAX_ANALYSIS_TEXT_CHARS


def is_text_truncated_for_analysis(character_count: Optional[int]) -> bool:
    """Single source of truth for "was/would this document's text be
    truncated for AI analysis" - derived from the already-stored
    Document.character_count rather than a separately persisted flag, so a
    cached analysis and a fresh one always agree, and retuning
    MAX_ANALYSIS_TEXT_CHARS immediately reflects in every read path."""
    return character_count is not None and character_count > MAX_ANALYSIS_TEXT_CHARS


def _truncate_for_analysis(text: str) -> str:
    """Never invents content for an omitted middle: the LLM is told exactly
    how many characters were cut and explicitly instructed not to guess
    about that section (see the marker text, and the matching prompt
    instruction in providers/ollama_provider.py) - the same fail-closed
    spirit as deadline_engine.py's "don't compute a date you can't derive
    with confidence"."""
    if len(text) <= MAX_ANALYSIS_TEXT_CHARS:
        return text

    omitted_chars = len(text) - TRUNCATION_HEAD_CHARS - TRUNCATION_TAIL_CHARS
    marker = (
        f"\n\n[SYSTEM NOTE: {omitted_chars} characters in the middle of this "
        "document were omitted here for length by the application, not by "
        "the sender - they are NOT part of the original document's own "
        "content. Do not guess, invent, or assume what the omitted section "
        "said (in particular, never invent a deadline, date, or amount for "
        "it) - base your answer only on the text actually shown before and "
        "after this note.]\n\n"
    )
    return text[:TRUNCATION_HEAD_CHARS] + marker + text[-TRUNCATION_TAIL_CHARS:]


# Real personal-mail document-type headers this app's users actually
# upload (see the Advanzia Bank Kontoauszug + Crawford & Company form
# multi-document report). Matched case-insensitively as a WHOLE word only
# (no \w* suffix wildcard) - an earlier version allowed inflected suffixes
# (Kontoauszug\w*), which caught real bugs before shipping: "Vertrag\w*"
# matched "Vertragsklausel"/"Vertragsbedingungen"/"Vertragslaufzeit", all
# extremely common *within* a single, entirely ordinary contract, which
# would have flagged almost every real Mietvertrag/Arbeitsvertrag as
# "multiple documents". Exact-word matching misses plurals
# (Kontoauszüge, Kündigungen) but that's the safer direction to err in for
# an unvalidated heuristic - a missed detection just means no hint is
# added (same as today), a false positive puts a wrong warning in front of
# the user. "Vertrag" itself was dropped from the list for the same
# reason: it is normal for one contract to reference "der Vertrag"/"dieser
# Vertrag" several times in its own body text.
_DOCUMENT_STAMP_WORDS = (
    "Kontoauszug",
    "Rechnung",
    "Mahnung",
    "Bescheid",
    "Kündigung",
    "Antragsformular",
    "Police",
    "Abrechnung",
    "Kreditkartenabrechnung",
    "Zahlungserinnerung",
)
_STAMP_WORD_PATTERNS = {
    word: re.compile(rf"\b{word}\b", re.IGNORECASE) for word in _DOCUMENT_STAMP_WORDS
}

# Standard German IBAN shape: "DE" + 2 check digits + 18 more digits,
# usually grouped in 4s with spaces but not always - matches both.
_IBAN_RE = re.compile(r"\bDE\d{2}(?:\s?\d{4}){4}\s?\d{2}\b")

# Starting thresholds only - not yet validated against a real-document
# sample (see chat/TODO: the next step is measuring these against real
# uploads before deciding whether to build actual document-splitting on
# top of this). Named constants so that round of tuning can change these
# numbers without touching the detection logic itself.
MIN_STAMP_WORD_REPEATS = 3
MIN_IBAN_MENTIONS = 2
MIN_PAGE_BREAKS_FOR_SIGNAL = 2


def detect_possible_multiple_documents(text: str) -> bool:
    """Cheap, deterministic pre-check for a scanned bundle of several
    separate documents in one upload (e.g. several months of a bank
    statement plus an unrelated form, concatenated into one PDF before
    scanning) - runs with zero extra LLM cost, so the common
    single-document case pays nothing extra. This is NOT a segmentation:
    it only feeds a hint into the prompt (see
    providers/ollama_provider.py's possible_multiple_documents parameter)
    so the model at least tries to cover every document/deadline it can
    find instead of silently describing only the first one.

    Any one signal alone is too common in a genuinely single document (a
    multi-page contract has page breaks; a single invoice can say
    "Rechnung" more than once; one IBAN is entirely normal) - only flags
    when at least two of the three independent signals agree.
    """
    if not text:
        return False

    page_breaks = text.count(PAGE_SEPARATOR)
    repeated_stamp_words = [
        word
        for word, pattern in _STAMP_WORD_PATTERNS.items()
        if len(pattern.findall(text)) >= MIN_STAMP_WORD_REPEATS
    ]
    iban_mentions = len(_IBAN_RE.findall(text))

    signals_hit = sum(
        [
            page_breaks >= MIN_PAGE_BREAKS_FOR_SIGNAL,
            bool(repeated_stamp_words),
            iban_mentions >= MIN_IBAN_MENTIONS,
        ]
    )
    flagged = signals_hit >= 2

    if flagged:
        logger.info(
            "multi_document_heuristic: flagged (page_breaks=%d, "
            "repeated_stamp_words=%s, iban_mentions=%d)",
            page_breaks,
            repeated_stamp_words,
            iban_mentions,
        )

    return flagged


class DocumentProcessingOrchestrator:
    def __init__(self, provider):
        self.provider = provider
        self.ai_service = AIService(provider)

    def run(self, text: str, *, possible_multiple_documents: bool = False) -> AIAnalysisResult:
        return self.ai_service.analyze(
            _truncate_for_analysis(text),
            possible_multiple_documents=possible_multiple_documents,
        )
