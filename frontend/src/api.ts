import { supabase } from './supabaseClient';

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
  // Document Intelligence fields (priority/deadline engines) - see
  // services.py's _serialize_document_intelligence. classified_document_type
  // is the deterministic taxonomy value, distinct from the free-form
  // document_type above.
  sender_category?: string | null;
  sender_institution?: string | null;
  classified_document_type?: string | null;
  priority_level?: PriorityLevel | null;
  priority_reasoning?: string | null;
  deadline_raw_text?: string | null;
  deadline_type?: string | null;
  deadline_estimated_date?: string | null;
  deadline_certainty?: string | null;
  requires_action?: boolean | null;
  action_summary?: string | null;
}

export type PriorityLevel = 'critical' | 'high' | 'normal' | 'low';

export interface DocumentSummary {
  id: number;
  filename: string;
  uploaded_at: string | null;
  status: string;
  sender_category: string | null;
  sender_institution: string | null;
  document_type: string | null;
  priority_level: PriorityLevel | null;
  priority_reasoning: string | null;
  deadline_type: string | null;
  deadline_estimated_date: string | null;
  deadline_certainty: string | null;
  requires_action: boolean;
  action_summary: string | null;
}

export interface DocumentsSummaryCounts {
  critical: number;
  high: number;
  normal: number;
  low: number;
  unclassified: number;
  total: number;
}

const apiBase = import.meta.env.VITE_API_BASE ?? '/api';

async function authHeaders(): Promise<HeadersInit> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function parseJsonResponse(response: Response) {
  const data = await response.json().catch(() => ({ message: 'Sunucu geçerli JSON döndürmedi.' }));
  if (!response.ok) {
    if (response.status === 401) {
      supabase.auth.signOut();
      throw new Error('Oturumunuz sona ermiş. Lütfen tekrar giriş yapın.');
    }
    throw new Error(data.detail || data.error || data.message || 'Sunucu hatası oluştu.');
  }
  return data;
}

export async function uploadDocument(file: File): Promise<UploadResponse> {
  const body = new FormData();
  body.append('file', file);

  const response = await fetch(`${apiBase}/upload`, {
    method: 'POST',
    headers: await authHeaders(),
    body,
  });

  return parseJsonResponse(response);
}

export async function analyzeDocumentById(documentId: number): Promise<AnalyzeResponse> {
  const response = await fetch(`${apiBase}/analyze/id/${documentId}`, {
    headers: await authHeaders(),
  });
  return parseJsonResponse(response);
}

export async function analyzeDocumentAIById(documentId: number): Promise<AIAnalysisResponse> {
  const response = await fetch(`${apiBase}/analyze/id/${documentId}/ai`, {
    method: 'POST',
    headers: await authHeaders(),
  });
  return parseJsonResponse(response);
}

export async function fetchDocumentsSummary(): Promise<DocumentsSummaryCounts> {
  const response = await fetch(`${apiBase}/documents/summary`, {
    headers: await authHeaders(),
  });
  return parseJsonResponse(response);
}

export async function fetchDocuments(priority?: PriorityLevel): Promise<DocumentSummary[]> {
  const url = priority
    ? `${apiBase}/documents?priority=${encodeURIComponent(priority)}`
    : `${apiBase}/documents`;
  const response = await fetch(url, {
    headers: await authHeaders(),
  });
  return parseJsonResponse(response);
}
