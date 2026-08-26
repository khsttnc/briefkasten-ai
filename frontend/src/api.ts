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
  // Informational only (e.g. a Kündigung's employment end date) - never
  // an action deadline. Kept separate from deadline_estimated_date.
  effective_date?: string | null;
  // True when the document's text was too long to send to the AI provider
  // in full (see backend document_processing.MAX_ANALYSIS_TEXT_CHARS) and
  // was cut to a head+tail excerpt instead - deadline_certainty is never
  // "exact" in that case, only "estimated" or "unknown_needs_review".
  text_truncated?: boolean;
  original_character_count?: number | null;
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
  effective_date: string | null;
  text_truncated: boolean;
  original_character_count: number | null;
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

export async function analyzeDocumentAIById(
  documentId: number,
  options?: { force?: boolean; signal?: AbortSignal }
): Promise<AIAnalysisResponse> {
  const url = options?.force
    ? `${apiBase}/analyze/id/${documentId}/ai?force=true`
    : `${apiBase}/analyze/id/${documentId}/ai`;
  const response = await fetch(url, {
    method: 'POST',
    headers: await authHeaders(),
    signal: options?.signal,
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

export interface AccountDeletionPreview {
  document_count: number;
  has_active_subscription: boolean;
  subscription_plan: string | null;
}

export async function fetchAccountDeletionPreview(): Promise<AccountDeletionPreview> {
  const response = await fetch(`${apiBase}/account/deletion-preview`, {
    headers: await authHeaders(),
  });
  return parseJsonResponse(response);
}

export async function deleteAccount(confirmationEmail: string): Promise<{ status: string }> {
  const response = await fetch(`${apiBase}/account`, {
    method: 'DELETE',
    headers: {
      ...(await authHeaders()),
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ confirmation_email: confirmationEmail }),
  });
  return parseJsonResponse(response);
}
