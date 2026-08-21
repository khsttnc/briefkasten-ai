import { useEffect, useMemo, useState } from 'react';
import {
  uploadDocument,
  analyzeDocumentById,
  analyzeDocumentAIById,
  fetchDocuments,
  fetchDocumentsSummary,
  AIAnalysisResponse,
  AnalyzeResponse,
  DocumentsSummaryCounts,
  DocumentSummary,
  PriorityLevel,
  UploadResponse,
} from './api';
import Hero from './components/landing/Hero';
import HowItWorks from './components/landing/HowItWorks';
import Features from './components/landing/Features';
import Security from './components/landing/Security';
import CTA from './components/landing/CTA';
import Footer from './components/landing/Footer';
import Impressum from './components/legal/Impressum';
import Datenschutz from './components/legal/Datenschutz';

const TOOL_SECTION_ID = 'analiz-araci';

interface AppError {
  message: string;
}

const PRIORITY_ORDER: PriorityLevel[] = ['critical', 'high', 'normal', 'low'];

const PRIORITY_LABELS: Record<PriorityLevel, string> = {
  critical: 'Kritik',
  high: 'Önemli',
  normal: 'Normal',
  low: 'Bilgi',
};

function MeineDokumente() {
  const [summary, setSummary] = useState<DocumentsSummaryCounts | null>(null);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [activeFilter, setActiveFilter] = useState<PriorityLevel | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadDocuments = async (priority: PriorityLevel | null) => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchDocuments(priority ?? undefined);
      setDocuments(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Belgeler yüklenemedi.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDocumentsSummary()
      .then(setSummary)
      .catch((err) => setError(err instanceof Error ? err.message : 'Özet yüklenemedi.'));
    loadDocuments(null);
    // Runs once on mount; loadDocuments(null) covers the initial (unfiltered) load.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleFilterClick = (level: PriorityLevel) => {
    const next = activeFilter === level ? null : level;
    setActiveFilter(next);
    loadDocuments(next);
  };

  return (
    <section className="card" id="meine-dokumente">
      <div className="card-header">
        <h2>Meine Dokumente</h2>
        <p>Önceliğe göre sıralanmış belgeleriniz.</p>
      </div>

      <div className="priority-counters">
        {PRIORITY_ORDER.map((level) => (
          <button
            key={level}
            type="button"
            className={`priority-counter priority-counter--${level}${
              activeFilter === level ? ' is-active' : ''
            }`}
            onClick={() => handleFilterClick(level)}
          >
            <span className="priority-counter-value">{summary ? summary[level] : '–'}</span>
            <span className="priority-counter-label">{PRIORITY_LABELS[level]}</span>
          </button>
        ))}
      </div>

      {error && <div className="error-banner">{error}</div>}
      {loading && <div className="status-banner">Belgeler yükleniyor...</div>}

      {!loading && !error && documents.length === 0 && (
        <div className="empty-state">
          {activeFilter
            ? 'Bu öncelikte belge bulunamadı.'
            : 'Henüz analiz edilmiş belge bulunamadı.'}
        </div>
      )}

      {!loading && documents.length > 0 && (
        <ul className="document-list">
          {documents.map((doc) => {
            const priorityKey = doc.priority_level ?? 'unclassified';
            return (
              <li key={doc.id} className={`document-list-item priority-${priorityKey}`}>
                <div className="document-list-item-header">
                  <span className={`priority-badge priority-badge--${priorityKey}`}>
                    {doc.priority_level ? PRIORITY_LABELS[doc.priority_level] : 'Analiz bekliyor'}
                  </span>
                  <span className="document-list-item-filename">{doc.filename}</span>
                </div>
                <div className="document-list-item-meta">
                  {doc.sender_institution && <span>{doc.sender_institution}</span>}
                  {doc.document_type && <span>{doc.document_type}</span>}
                  {doc.deadline_estimated_date && (
                    <span>
                      Son tarih: {doc.deadline_estimated_date.slice(0, 10)}
                      {doc.deadline_certainty === 'unknown_needs_review'
                        ? ' (belirsiz, kontrol edin)'
                        : ''}
                    </span>
                  )}
                </div>
                {doc.action_summary && <p className="document-list-item-action">{doc.action_summary}</p>}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function App() {
  const pathname = window.location.pathname.replace(/\/+$/, '') || '/';

  if (pathname === '/impressum') {
    return (
      <>
        <Impressum />
        <Footer />
      </>
    );
  }

  if (pathname === '/datenschutz') {
    return (
      <>
        <Datenschutz />
        <Footer />
      </>
    );
  }

  return <AppHome />;
}

function AppHome() {
  const [file, setFile] = useState<File | null>(null);
  const [uploadResult, setUploadResult] = useState<UploadResponse | null>(null);
  const [analysisResult, setAnalysisResult] = useState<AnalyzeResponse | null>(null);
  const [aiResult, setAIResult] = useState<AIAnalysisResponse | null>(null);
  const [statusMessage, setStatusMessage] = useState<string>('');
  const [error, setError] = useState<AppError | null>(null);
  const [loading, setLoading] = useState(false);
  const [aiLoading, setAILoading] = useState(false);

  const documentId = useMemo(() => uploadResult?.id ?? null, [uploadResult]);

  const scrollToTool = () => {
    document.getElementById(TOOL_SECTION_ID)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const resetState = () => {
    setError(null);
    setStatusMessage('');
    setAnalysisResult(null);
    setAIResult(null);
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    resetState();
    setFile(event.target.files?.[0] ?? null);
  };

  const handleUpload = async () => {
    if (!file) {
      setError({ message: 'Lütfen önce bir dosya seçin.' });
      return;
    }

    setError(null);
    setStatusMessage('Dosya yükleniyor...');
    setLoading(true);
    setUploadResult(null);
    setAnalysisResult(null);
    setAIResult(null);

    try {
      const response = await uploadDocument(file);
      setUploadResult(response);
      setStatusMessage('Yükleme başarılı. Belge ID alındı. Analiz sorgulanıyor...');
      const analyze = await analyzeDocumentById(response.id);
      setAnalysisResult(analyze);
      setStatusMessage('Belge analizi tamamlandı. OCR/Metin çıktısı hazır.');
    } catch (err) {
      setError({ message: err instanceof Error ? err.message : 'Bir hata oluştu.' });
      setStatusMessage('');
    } finally {
      setLoading(false);
    }
  };

  const handleAIAnalyze = async () => {
    if (!documentId) {
      setError({ message: 'Önce bir belge yükleyip analiz edin.' });
      return;
    }

    setError(null);
    setStatusMessage('AI analizi başlatılıyor...');
    setAILoading(true);

    try {
      const response = await analyzeDocumentAIById(documentId);
      setAIResult(response);
      setStatusMessage('AI analizi tamamlandı. Sonuçlar aşağıda gösteriliyor.');
    } catch (err) {
      setError({ message: err instanceof Error ? err.message : 'AI analizi sırasında bir hata oluştu.' });
      setStatusMessage('');
    } finally {
      setAILoading(false);
    }
  };

  return (
    <>
      <Hero onCtaClick={scrollToTool} />
      <HowItWorks />
      <Features />
      <Security />
      <CTA onCtaClick={scrollToTool} />

      <div className="app-shell" id={TOOL_SECTION_ID}>
      <header className="app-header">
        <div>
          <p className="eyebrow">Briefkasten AI</p>
          <h1>Alman resmi belge analiz platformu</h1>
          <p className="subtitle">PDF veya doküman yükleyin, OCR metnini inceleyin ve AI analizine hazır olun.</p>
        </div>
      </header>

      <main className="app-content">
        <section className="card">
          <div className="card-header">
            <h2>Belge yükleme</h2>
            <p>PDF veya doküman yükleyerek süreci başlatın.</p>
          </div>

          <div className="form-row">
            <label className="file-input-label">
              <input type="file" accept=".pdf,.png,.jpg,.jpeg,.tiff" onChange={handleFileChange} />
              <span>{file ? file.name : 'Dosya seçin'}</span>
            </label>
            <button onClick={handleUpload} disabled={loading || !file} className="primary-button">
              {loading ? 'Yükleniyor...' : 'Yükle ve Analiz Et'}
            </button>
          </div>

          {statusMessage && <div className="status-banner">{statusMessage}</div>}
          {error && <div className="error-banner">{error.message}</div>}

          {!uploadResult && !loading && !error && (
            <div className="empty-state">Henüz belge yüklemediniz. Başlamak için dosya seçin.</div>
          )}
        </section>

        {uploadResult && (
          <section className="card">
            <div className="card-header">
              <h2>Belge durumu</h2>
              <p>Belge ID ve analiz bilgileri.</p>
            </div>

            <div className="info-grid">
              <div>
                <label>Belge ID</label>
                <p>{uploadResult.id}</p>
              </div>
              <div>
                <label>Dosya Adı</label>
                <p>{uploadResult.filename}</p>
              </div>
              <div>
                <label>Yükleme Durumu</label>
                <p>{uploadResult.status}</p>
              </div>
            </div>
          </section>
        )}

        {analysisResult && (
          <section className="card">
            <div className="card-header">
              <h2>OCR / Metin Çıktısı</h2>
              <p>Belgeden çıkartılan metin burada görüntülenir.</p>
            </div>
            <div className="analysis-block">
              <p className="small-label">Karakter sayısı</p>
              <p>{analysisResult.characters}</p>
            </div>
            <div className="text-block">
              <pre>{analysisResult.text || 'Belgeden metin çıkarılamadı.'}</pre>
            </div>
          </section>
        )}

        <section className="card">
          <div className="card-header">
            <h2>AI Analiz Paneli</h2>
            <p>AI analizini başlatmak için butona tıklayın.</p>
          </div>

          <div className="form-row">
            <button onClick={handleAIAnalyze} disabled={!documentId || aiLoading} className="secondary-button">
              {aiLoading ? 'AI analizi çalışıyor...' : 'AI ile analiz et'}
            </button>
            {!documentId && <p className="muted-text">Önce bir belge yükleyip analiz edin.</p>}
          </div>

          {aiResult && (
            <div className="ai-results">
              <div className="analysis-block">
                <p className="small-label">AI Durumu</p>
                <p>{aiResult.status}</p>
              </div>
              {aiResult.error_message && <div className="error-banner">AI Hatası: {aiResult.error_message}</div>}
              {aiResult.summary && (
                <div className="text-block">
                  <h3>Özet</h3>
                  <p>{aiResult.summary}</p>
                </div>
              )}
              {aiResult.turkish_explanation && (
                <div className="text-block">
                  <h3>Açıklama</h3>
                  <p>{aiResult.turkish_explanation}</p>
                </div>
              )}
              {aiResult.document_type && (
                <div className="info-grid">
                  <div>
                    <label>Belge Tipi</label>
                    <p>{aiResult.document_type}</p>
                  </div>
                  <div>
                    <label>Dil</label>
                    <p>{aiResult.language || 'Bilinmiyor'}</p>
                  </div>
                </div>
              )}
            </div>
          )}

          {!aiResult && !aiLoading && documentId && (
            <div className="empty-state">AI analizi için butona basın. AI kullanılabilir değilse burada açıklama görünecek.</div>
          )}
        </section>

        <MeineDokumente />
      </main>
      </div>

      <Footer />
    </>
  );
}

export default App;
