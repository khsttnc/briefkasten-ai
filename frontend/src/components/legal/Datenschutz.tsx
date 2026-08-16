function Datenschutz() {
  return (
    <div className="app-shell legal-page">
      <a className="legal-back-link" href="/">
        ← Ana sayfaya dön
      </a>

      <header className="app-header">
        <div>
          <p className="eyebrow">Briefkasten AI</p>
          <h1>Datenschutzerklärung</h1>
          <p className="subtitle">
            Informationen zur Verarbeitung personenbezogener Daten gemäß Art. 13 DSGVO.
          </p>
        </div>
      </header>

      <main className="app-content">
        <section className="card legal-content">
          <div className="status-banner">
            Hinweis: Dies ist ein Entwurf, der den tatsächlichen technischen Ablauf der
            Anwendung so genau wie möglich beschreibt. Er wurde nicht durch einen Rechtsanwalt
            geprüft, stellt keine Rechtsberatung dar und sollte vor einer öffentlichen
            Veröffentlichung rechtlich geprüft werden.
          </div>

          <h2>1. Verantwortlicher</h2>
          <p>
            Verantwortlich für die Datenverarbeitung im Sinne der DSGVO ist:
          </p>
          <address>
            Kubilay Tütüncü
            <br />
            Eichendorffstraße 35
            <br />
            59269 Beckum
            <br />
            Deutschland
            <br />
            E-Mail: <a href="mailto:khsttnc@gmail.com">khsttnc@gmail.com</a>
          </address>
          <p>
            Briefkasten AI ist derzeit ein privates Einzelprojekt ohne Unternehmen bzw. Firma.
          </p>

          <h2>2. Welche Daten verarbeitet werden</h2>
          <p>
            Wenn Sie diese Anwendung nutzen, werden je nach Nutzung folgende Daten verarbeitet:
          </p>
          <ul>
            <li>
              <strong>Hochgeladene Dokumente:</strong> Die Datei, die Sie über die Upload-Funktion
              auswählen (PDF, PNG, JPG, JPEG oder TIFF). Die Datei wird auf dem Server unter einem
              zufällig generierten Dateinamen gespeichert, nicht unter dem Originalnamen.
            </li>
            <li>
              <strong>Ursprünglicher Dateiname:</strong> Der von Ihnen hochgeladene Originaldateiname
              wird (in bereinigter Form) zusätzlich in der Datenbank als Metadatum gespeichert.
            </li>
            <li>
              <strong>Aus dem Dokument extrahierter Text:</strong> Der Textinhalt Ihres Dokuments
              wird automatisch extrahiert (per PyMuPDF bzw., falls kein Text direkt auslesbar ist,
              per optischer Zeichenerkennung/OCR mit Tesseract) und vollständig in der Datenbank
              gespeichert.
            </li>
            <li>
              <strong>KI-Analyseergebnisse:</strong> Wenn Sie die KI-Analyse aktiv starten, werden
              der extrahierte Dokumenttext sowie die daraus erzeugten Analyseergebnisse
              (Dokumenttyp, erkannte Sprache, Zusammenfassung, türkische Erklärung, erkannte
              Daten/Fristen, erkannte Entitäten) in der Datenbank gespeichert.
            </li>
            <li>
              <strong>Technische Zugriffsdaten:</strong> Wie bei jedem Webserver-Betrieb können
              beim Aufruf der Anwendung technische Daten (z. B. IP-Adresse, Zeitpunkt, aufgerufene
              Adresse) im Server-Prozess anfallen. Die Anwendung selbst speichert diese Daten
              aktuell nicht dauerhaft in der Datenbank.
            </li>
            <li>
              <strong>Fehlerprotokolle:</strong> Bei unerwarteten technischen Fehlern wird ein
              Fehlerereignis serverseitig protokolliert, um die Ursache nachvollziehen zu können.
              Diese Protokolle werden nicht an Dritte weitergegeben.
            </li>
          </ul>
          <p>
            Es findet <strong>keine</strong> Registrierung, kein Login und keine Erstellung von
            Nutzerkonten statt. Die Anwendung verwendet <strong>keine</strong> Cookies, kein
            Tracking, keine Analyse-Tools (z. B. Google Analytics) und keinen Newsletter.
          </p>

          <h2>3. Zweck der Verarbeitung</h2>
          <p>
            Die Verarbeitung dient ausschließlich der von Ihnen angefragten Funktion: dem
            Auslesen des Textinhalts Ihres hochgeladenen Dokuments und, sofern von Ihnen
            angefordert, der KI-gestützten Analyse und Erklärung dieses Dokuments.
          </p>
          <p>
            Rechtsgrundlage ist in der Regel Art. 6 Abs. 1 lit. b DSGVO (Verarbeitung zur
            Durchführung der von Ihnen gewünschten Analyse). Diese Einschätzung sollte im Rahmen
            der rechtlichen Prüfung final bestätigt werden.
          </p>

          <h2>4. Weitergabe an Dritte</h2>
          <p>
            <strong>Claude API (Anthropic):</strong> Sofern die Anwendung mit dem
            Standard-KI-Anbieter konfiguriert ist (Claude von Anthropic), wird der aus Ihrem
            Dokument extrahierte Textinhalt zur Analyse an die Claude API von Anthropic
            übermittelt. Dies ist ein externer, US-amerikanischer Anbieter außerhalb der EU. Eine
            förmliche Auftragsverarbeitungsvereinbarung mit Anthropic sowie eine abschließende
            Bewertung der Rechtsgrundlage für diese Drittlandübermittlung stehen noch aus und
            sollten vor einem öffentlichen Betrieb geklärt werden.
          </p>
          <p>
            <strong>Ollama (lokaler Anbieter):</strong> Alternativ kann die Anwendung so
            konfiguriert werden, dass die Analyse über Ollama erfolgt. In diesem Fall wird der
            Dokumenttext an eine lokal betriebene Ollama-Instanz verarbeitet und nicht an einen
            externen Dritten übertragen. Welcher der beiden Anbieter aktiv ist, hängt von der
            Serverkonfiguration ab.
          </p>
          <p>
            Eine darüber hinausgehende Weitergabe Ihrer Daten an weitere Dritte findet nicht
            statt.
          </p>

          <h2>5. Speicherdauer und Löschung</h2>
          <p>
            Aktuell ist <strong>kein automatischer Löschmechanismus und keine feste
            Aufbewahrungsfrist</strong> in der Anwendung implementiert. Hochgeladene Dokumente,
            extrahierter Text und KI-Analyseergebnisse verbleiben bis auf Weiteres in der
            Datenbank bzw. im Dateispeicher des Servers. Eine Löschung kann derzeit nur manuell
            durch den Verantwortlichen erfolgen, z. B. auf Ihre Anfrage hin (siehe Abschnitt 7).
          </p>

          <h2>6. Hosting</h2>
          <p>
            Die Anwendung befindet sich aktuell in der lokalen Entwicklung und wird nicht
            öffentlich betrieben. Es existiert derzeit keine produktive Hosting-Infrastruktur
            (z. B. kein dediziertes Hosting, kein Nginx, kein Docker-Deployment). Sobald ein
            öffentlicher Betrieb erfolgt, wird diese Erklärung um die dann tatsächlich genutzte
            Hosting-Infrastruktur ergänzt.
          </p>

          <h2>7. Ihre Rechte</h2>
          <p>
            Ihnen stehen nach der DSGVO folgende Rechte zu: Auskunft (Art. 15), Berichtigung
            (Art. 16), Löschung (Art. 17), Einschränkung der Verarbeitung (Art. 18),
            Datenübertragbarkeit (Art. 20) sowie Widerspruch gegen die Verarbeitung (Art. 21).
          </p>
          <p>
            Da die Anwendung aktuell keine automatisierte Selbstbedienungsfunktion (z. B. einen
            Lösch-Button) für diese Rechte bietet, können entsprechende Anfragen formlos per
            E-Mail an <a href="mailto:khsttnc@gmail.com">khsttnc@gmail.com</a> gerichtet werden.
          </p>
          <p>
            Außerdem haben Sie das Recht, sich bei einer Datenschutz-Aufsichtsbehörde zu
            beschweren. Zuständig für Nordrhein-Westfalen ist in der Regel die Landesbeauftragte
            für Datenschutz und Informationsfreiheit Nordrhein-Westfalen (LDI NRW).
          </p>

          <h2>8. Kontakt für Datenschutzanfragen</h2>
          <p>
            Bei Fragen zum Datenschutz wenden Sie sich bitte an:{' '}
            <a href="mailto:khsttnc@gmail.com">khsttnc@gmail.com</a>.
          </p>
        </section>
      </main>
    </div>
  );
}

export default Datenschutz;
