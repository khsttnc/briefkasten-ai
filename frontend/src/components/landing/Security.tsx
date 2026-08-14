const points = [
  {
    title: 'Belgeleriniz yalnızca analiz için kullanılır',
    description: 'Yüklenen belgeler yalnızca metin çıkarma ve AI analizi amacıyla işlenir.',
  },
  {
    title: 'Sunucu taraflı işleme',
    description: 'OCR ve analiz işlemleri kendi backend altyapımızda gerçekleştirilir.',
  },
  {
    title: 'Kontrol sizde',
    description: 'Hangi AI sağlayıcısının (Claude veya yerel Ollama) kullanılacağını yapılandırabilirsiniz.',
  },
];

function Security() {
  return (
    <section className="landing-section landing-section-muted">
      <div className="landing-container">
        <h2 className="landing-section-title">Güvenlik ve Veri Gizliliği</h2>
        <div className="landing-security-grid">
          {points.map((point) => (
            <div className="card" key={point.title}>
              <h3>{point.title}</h3>
              <p>{point.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export default Security;
