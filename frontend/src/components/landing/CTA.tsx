interface CTAProps {
  onCtaClick: () => void;
}

function CTA({ onCtaClick }: CTAProps) {
  return (
    <section className="landing-cta">
      <div className="landing-container landing-cta-content">
        <p className="landing-cta-eyebrow">Hazır mısınız?</p>
        <button className="primary-button landing-cta-button" onClick={onCtaClick}>
          Belgenizi Şimdi Analiz Edin
        </button>
      </div>
    </section>
  );
}

export default CTA;
