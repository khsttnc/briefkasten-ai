const features = [
  {
    title: 'OCR desteği',
    description: 'Taranmış belgelerde bile metin otomatik olarak çıkarılır.',
  },
  {
    title: 'Türkçe açıklama',
    description: 'Belge içeriği ve özet Türkçe olarak sunulur.',
  },
  {
    title: 'Önemli tarih ve varlıklar',
    description: 'Belgedeki tarihler, kişi/kurum adları ve referans numaraları tespit edilir.',
  },
  {
    title: 'Esnek AI sağlayıcı',
    description: 'Claude veya yerel Ollama modelleriyle çalışabilir.',
  },
];

function Features() {
  return (
    <section className="landing-section">
      <div className="landing-container">
        <h2 className="landing-section-title">Özellikler</h2>
        <div className="landing-features-grid">
          {features.map((feature) => (
            <div className="card landing-feature-card" key={feature.title}>
              <h3>{feature.title}</h3>
              <p>{feature.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export default Features;
