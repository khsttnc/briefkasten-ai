import { useMemo, useState } from 'react';
import {
  uploadDocument,
  analyzeDocumentById,
  analyzeDocumentAIById,
  AIAnalysisResponse,
  AnalyzeResponse,
  UploadResponse,
} from './api';

interface AppError {
  message: string;
}

function App() {
  const [file, setFile] = useState<File | null>(null);
  const [uploadResult, setUploadResult] = useState<UploadResponse | null>(null);
  const [analysisResult, setAnalysisResult] = useState<AnalyzeResponse | null>(null);
  const [aiResult, setAIResult] = useState<AIAnalysisResponse | null>(null);
  const [statusMessage, setStatusMessage] = useState<string>('');
  const [error, setError] = useState<AppError | null>(null);
  const [loading, setLoading] = useState(false);
  const [aiLoading, setAILoading] = useState(false);

  const documentId = useMemo(() => uploadResult?.id ?? null, [uploadResult]);

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
    <div className="app-shell">
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
      </main>
    </div>
  );
}

export default App;
