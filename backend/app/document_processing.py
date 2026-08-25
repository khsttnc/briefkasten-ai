from typing import Optional

from .ai_service import AIAnalysisResult, AIService

# A document's extracted text beyond this length is not sent to the AI
# provider as-is. This pipeline's taxonomy (Bescheid/Mahnung/Kündigung/...)
# targets short official letters - the personalized signal it looks for
# (sender, dates, an actionable deadline) is almost always in the first few
# pages (the actual cover letter) or a short closing section, never buried
# in hundreds of pages of boilerplate terms (e.g. a 200-page insurance
# policy's Versicherungsbedingungen). Sending all of it is expensive and
# does not improve extraction quality. A single named constant so the
# budget is easy to retune later.
MAX_ANALYSIS_TEXT_CHARS = 20_000

# How MAX_ANALYSIS_TEXT_CHARS is split between the start and end of the
# document when it must be truncated. Weighted toward the head (cover
# letter, sender, key dates); a smaller tail share is kept in case a
# signature or closing notice carries something relevant instead. Must sum
# to MAX_ANALYSIS_TEXT_CHARS.
TRUNCATION_HEAD_CHARS = 14_000
TRUNCATION_TAIL_CHARS = 6_000

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


class DocumentProcessingOrchestrator:
    def __init__(self, provider):
        self.provider = provider
        self.ai_service = AIService(provider)

    def run(self, text: str) -> AIAnalysisResult:
        return self.ai_service.analyze(_truncate_for_analysis(text))
