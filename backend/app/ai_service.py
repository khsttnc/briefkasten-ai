from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class AIAnalysisResult:
    document_type: Optional[str] = None
    language: Optional[str] = None
    summary: Optional[str] = None
    turkish_explanation: Optional[str] = None
    important_dates: Optional[List[str]] = None
    extracted_entities: Optional[List[Dict[str, Any]]] = None
    raw_response: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None


class AIProvider(Protocol):
    provider_name: str
    model_name: str

    def analyze_document(self, text: str) -> AIAnalysisResult:
        ...


class BaseAIProvider(abc.ABC):
    @property
    @abc.abstractmethod
    def provider_name(self) -> str:
        ...

    @property
    @abc.abstractmethod
    def model_name(self) -> str:
        ...

    @abc.abstractmethod
    def analyze_document(self, text: str) -> AIAnalysisResult:
        ...


class AIService:
    def __init__(self, provider: AIProvider):
        self.provider = provider

    def analyze(self, text: str, task: Optional[str] = None) -> AIAnalysisResult:
        analyze_with_task = getattr(self.provider, "analyze_document_with_task", None)
        if task is not None and callable(analyze_with_task):
            return analyze_with_task(text, task)
        return self.provider.analyze_document(text)
