interface HeroProps {
  onCtaClick: () => void;
}

function Hero({ onCtaClick }: HeroProps) {
  return (
    <section className="landing-hero">
      <div className="landing-container">
        <p className="eyebrow">AI destekli belge analizi</p>
        <h1 className="landing-hero-title">Alman resmi belgelerinizi saniyeler içinde anlayın</h1>
        <p className="landing-hero-subtitle">
          PDF veya taranmış belgelerinizi yükleyin; metni çıkaralım, yapay zekâ ile belge
          türünü, önemli tarihleri ve içeriği Türkçe olarak özetleyelim.
        </p>
        <div className="landing-hero-actions">
          <button className="primary-button" onClick={onCtaClick}>
            Hemen Analiz Et
          </button>
        </div>
      </div>
    </section>
  );
}

export default Hero;
