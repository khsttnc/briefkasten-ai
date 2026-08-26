import { beforeEach, describe, expect, test, vi } from 'vitest';
import '@testing-library/jest-dom';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import * as api from './api';

// AuthGate normally gates all of this behind a Supabase session; these
// tests are about the AI-analyze request/response flow inside AppHome,
// not authentication, so it's replaced with a passthrough.
vi.mock('./auth/AuthGate', () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof api>('./api');
  return {
    ...actual,
    uploadDocument: vi.fn(),
    analyzeDocumentById: vi.fn(),
    analyzeDocumentAIById: vi.fn(),
    fetchDocuments: vi.fn(),
    fetchDocumentsSummary: vi.fn(),
  };
});

const mockedApi = vi.mocked(api);

async function uploadAndReachAnalyzeButton() {
  mockedApi.uploadDocument.mockResolvedValue({ id: 1, filename: 'test.pdf', status: 'uploaded' });
  mockedApi.analyzeDocumentById.mockResolvedValue({ filename: 'test.pdf', characters: 10, text: 'Test metni' });
  mockedApi.fetchDocuments.mockResolvedValue([]);
  mockedApi.fetchDocumentsSummary.mockResolvedValue({
    critical: 0,
    high: 0,
    normal: 0,
    low: 0,
    unclassified: 0,
    total: 0,
  });

  const user = userEvent.setup();
  render(<App />);

  const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
  const file = new File(['dummy'], 'test.pdf', { type: 'application/pdf' });
  await user.upload(fileInput, file);
  await user.click(screen.getByText('Yükle ve Analiz Et'));

  return user;
}

describe('AI analyze request handling', () => {
  beforeEach(() => {
    mockedApi.uploadDocument.mockReset();
    mockedApi.analyzeDocumentById.mockReset();
    mockedApi.analyzeDocumentAIById.mockReset();
    mockedApi.fetchDocuments.mockReset();
    mockedApi.fetchDocumentsSummary.mockReset();
  });

  test('a successful response clears the loading state and shows the result', async () => {
    mockedApi.analyzeDocumentAIById.mockResolvedValue({
      analysis_id: 1,
      document_id: 1,
      provider: 'nvidia',
      model: 'openai/gpt-oss-120b',
      status: 'completed',
      turkish_explanation: 'Test açıklaması.',
    });

    const user = await uploadAndReachAnalyzeButton();
    await user.click(await screen.findByText('AI ile analiz et'));

    // Regression guard for the reported production bug: a completed
    // backend response (mocked here exactly like the real 200 case) must
    // actually clear the loading/status message and render the result -
    // it must not stay stuck on "çalışıyor...".
    await waitFor(() => expect(screen.getByText('AI ile analiz et')).not.toBeDisabled());
    expect(screen.queryByText(/çalışıyor/)).not.toBeInTheDocument();
    expect(await screen.findByText('Test açıklaması.')).toBeInTheDocument();
    expect(screen.getByText('AI analizi tamamlandı. Sonuçlar aşağıda gösteriliyor.')).toBeInTheDocument();
  });

  test('a timed-out request surfaces a visible, recoverable error instead of staying stuck', async () => {
    // Exercises the error-handling code path that AI_ANALYZE_TIMEOUT_MS's
    // setTimeout->controller.abort() produces, without waiting out the
    // real 60s (or fighting fake-timer/userEvent interaction) - the
    // AbortController firing after 60s of real elapsed time is standard
    // browser timer behavior, not application logic worth re-verifying
    // here. What matters, and is the actual regression this guards
    // against, is that an aborted/never-settling request (the exact
    // reported symptom: backend logged 200, browser never reflected it)
    // ends in a visible, actionable error and a reset, clickable button -
    // not an indefinite "çalışıyor..." with no way out.
    mockedApi.analyzeDocumentAIById.mockRejectedValue(
      new DOMException('The operation was aborted.', 'AbortError')
    );

    const user = await uploadAndReachAnalyzeButton();
    await user.click(await screen.findByText('AI ile analiz et'));

    expect(
      await screen.findByText('AI analizi çok uzun sürdü ve zaman aşımına uğradı. Lütfen tekrar deneyin.')
    ).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('AI ile analiz et')).not.toBeDisabled());
    expect(screen.queryByText(/çalışıyor/)).not.toBeInTheDocument();
  });
});
