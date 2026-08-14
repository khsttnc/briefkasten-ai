from .ai_service import AIAnalysisResult, AIService


class DocumentProcessingOrchestrator:
    def __init__(self, provider):
        self.provider = provider
        self.ai_service = AIService(provider)

    def run(self, text: str) -> AIAnalysisResult:
        return self.ai_service.analyze(text)
