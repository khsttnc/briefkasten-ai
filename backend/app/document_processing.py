from .ai_service import AIAnalysisResult, AIService
from .processors import ClassificationProcessor, ExtractionProcessor, ExplanationProcessor


class DocumentProcessingOrchestrator:
    def __init__(self, provider):
        self.provider = provider
        self.ai_service = AIService(provider)
        self.classification_processor = ClassificationProcessor()
        self.extraction_processor = ExtractionProcessor()
        self.explanation_processor = ExplanationProcessor()

    def run(self, text: str) -> AIAnalysisResult:
        classification_result = self.classification_processor.process(text, self.ai_service)
        if classification_result.error_message:
            return classification_result

        extraction_result = self.extraction_processor.process(text, self.ai_service)
        if extraction_result.error_message:
            return extraction_result

        explanation_result = self.explanation_processor.process(text, self.ai_service)
        if explanation_result.error_message:
            return explanation_result

        combined_raw = {
            "classification": classification_result.raw_response,
            "extraction": extraction_result.raw_response,
            "explanation": explanation_result.raw_response,
        }

        return AIAnalysisResult(
            document_type=classification_result.document_type,
            language=classification_result.language,
            summary=explanation_result.summary,
            turkish_explanation=explanation_result.turkish_explanation,
            important_dates=extraction_result.important_dates,
            extracted_entities=extraction_result.extracted_entities,
            raw_response=combined_raw,
        )
