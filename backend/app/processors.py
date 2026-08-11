from .ai_service import AIAnalysisResult, AIService


class ClassificationProcessor:
    def process(self, text: str, ai_service: AIService) -> AIAnalysisResult:
        return ai_service.analyze(text, task="classification")


class ExtractionProcessor:
    def process(self, text: str, ai_service: AIService) -> AIAnalysisResult:
        return ai_service.analyze(text, task="extraction")


class ExplanationProcessor:
    def process(self, text: str, ai_service: AIService) -> AIAnalysisResult:
        return ai_service.analyze(text, task="explanation")
