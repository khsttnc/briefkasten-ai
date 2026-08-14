const steps = [
  {
    title: '1. Belgeyi yükleyin',
    description: 'PDF, PNG, JPG veya TIFF formatındaki belgenizi sisteme yükleyin.',
  },
  {
    title: '2. Metin çıkarılır',
    description: 'Belge metni otomatik olarak çıkarılır; gerekirse OCR devreye girer.',
  },
  {
    title: '3. Yapay zekâ analiz eder',
    description: 'Belge türü, önemli tarihler ve içerik tek bir AI analiziyle Türkçe olarak özetlenir.',
  },
];

function HowItWorks() {
  return (
    <section className="landing-section">
      <div className="landing-container">
        <h2 className="landing-section-title">Nasıl çalışır?</h2>
        <div className="landing-steps-grid">
          {steps.map((step) => (
            <div className="landing-step-card" key={step.title}>
              <h3>{step.title}</h3>
              <p>{step.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export default HowItWorks;
