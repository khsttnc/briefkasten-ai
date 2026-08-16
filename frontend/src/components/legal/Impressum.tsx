function Impressum() {
  return (
    <div className="app-shell legal-page">
      <a className="legal-back-link" href="/">
        ← Ana sayfaya dön
      </a>

      <header className="app-header">
        <div>
          <p className="eyebrow">Briefkasten AI</p>
          <h1>Impressum</h1>
          <p className="subtitle">Angaben gemäß § 5 DDG.</p>
        </div>
      </header>

      <main className="app-content">
        <section className="card legal-content">
          <div className="status-banner">
            Hinweis: Dies ist ein Entwurf. Der Inhalt dieser Seite wurde nicht durch einen
            Rechtsanwalt geprüft und stellt keine Rechtsberatung dar. Vor einer öffentlichen
            Veröffentlichung sollte eine rechtliche Prüfung erfolgen.
          </div>

          <h2>Angaben gemäß § 5 DDG</h2>
          <address>
            Kubilay Tütüncü
            <br />
            Eichendorffstraße 35
            <br />
            59269 Beckum
            <br />
            Deutschland
          </address>

          <h2>Kontakt</h2>
          <p>
            E-Mail: <a href="mailto:khsttnc@gmail.com">khsttnc@gmail.com</a>
          </p>
          <p className="muted-text">
            Eine Telefonnummer wird bewusst nicht angegeben.
          </p>

          <h2>Unternehmensangaben</h2>
          <p>
            Es handelt sich derzeit um kein Unternehmen bzw. keine Firma. Briefkasten AI wird
            aktuell als privates Einzelprojekt unter dem oben genannten Namen betrieben. Es
            liegen keine Handelsregisternummer, keine Umsatzsteuer-Identifikationsnummer und
            keine Geschäftsführung vor, da kein Unternehmen existiert.
          </p>

          <h2>Verantwortlich für den Inhalt</h2>
          <p>Kubilay Tütüncü (Anschrift siehe oben).</p>

          <h2>Haftung für Inhalte</h2>
          <p>
            Als Diensteanbieter ist der Betreiber dieser Seite für eigene Inhalte auf diesen
            Seiten nach den allgemeinen Gesetzen verantwortlich. Die Verantwortlichkeit für
            fremde Inhalte richtet sich nach Art. 4 bis 8 der Verordnung (EU) 2022/2065 (Digital
            Services Act) in Verbindung mit §§ 7 f. DDG; danach ist der Betreiber als
            Diensteanbieter nicht verpflichtet, übermittelte oder gespeicherte fremde
            Informationen zu überwachen oder nach Umständen zu forschen, die auf eine
            rechtswidrige Tätigkeit hinweisen.
          </p>

          <h2>Haftung für Links</h2>
          <p>
            Diese Website enthält gegebenenfalls Links zu externen Websites Dritter, auf deren
            Inhalte der Betreiber keinen Einfluss hat. Für die Inhalte der verlinkten Seiten ist
            stets der jeweilige Anbieter oder Betreiber der Seiten verantwortlich.
          </p>

          <h2>Urheberrecht</h2>
          <p>
            Die durch den Seitenbetreiber erstellten Inhalte und Werke auf diesen Seiten
            unterliegen dem deutschen Urheberrecht. Beiträge Dritter sind als solche
            gekennzeichnet.
          </p>
        </section>
      </main>
    </div>
  );
}

export default Impressum;
