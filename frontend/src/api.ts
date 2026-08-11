export interface UploadResponse {
  id: number;
  filename: string;
  status: string;
}

export interface AnalyzeResponse {
  filename: string;
  characters: number;
  text: string;
}

export interface AIAnalysisResponse {
  analysis_id: number;
  document_id: number;
  provider: string;
  model: string;
  status: string;
  document_type?: string;
  language?: string;
  summary?: string;
  turkish_explanation?: string;
  important_dates?: Array<unknown>;
  extracted_entities?: Array<unknown>;
  error_message?: string;
}

const apiBase = import.meta.env.VITE_API_BASE ?? '/api';

async function parseJsonResponse(response: Response) {
  const data = await response.json().catch(() => ({ message: 'Sunucu geçerli JSON döndürmedi.' }));
  if (!response.ok) {
    throw new Error(data.detail || data.error || data.message || 'Sunucu hatası oluştu.');
  }
  return data;
}

export async function uploadDocument(file: File): Promise<UploadResponse> {
  const body = new FormData();
  body.append('file', file);

  const response = await fetch(`${apiBase}/upload`, {
    method: 'POST',
    body,
  });

  return parseJsonResponse(response);
}

export async function analyzeDocumentById(documentId: number): Promise<AnalyzeResponse> {
  const response = await fetch(`${apiBase}/analyze/id/${documentId}`);
  return parseJsonResponse(response);
}

export async function analyzeDocumentAIById(documentId: number): Promise<AIAnalysisResponse> {
  const response = await fetch(`${apiBase}/analyze/id/${documentId}/ai`, {
    method: 'POST',
  });
  return parseJsonResponse(response);
}
