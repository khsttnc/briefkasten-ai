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
          <div className="legal-draft-warning">
            <span className="legal-draft-warning-icon" aria-hidden="true">
              ⚠️
            </span>
            <span>
              WICHTIGER HINWEIS: Dies ist ein <u>Entwurf</u>, der versucht, den tatsächlichen
              technischen Ablauf der Anwendung so genau wie möglich zu beschreiben. Er wurde{' '}
              <u>nicht</u> durch einen Rechtsanwalt geprüft, stellt <u>keine Rechtsberatung</u>{' '}
              dar und ersetzt keine individuelle rechtliche Prüfung. Vor jeder öffentlichen
              Nutzung durch echte Kundinnen und Kunden muss dieser Text von einer
              Rechtsanwältin/einem Rechtsanwalt geprüft und freigegeben werden. Einzelne
              Angaben (insb. Serverstandorte, Auftragsverarbeitungsverträge) sind als
              [BESTÄTIGEN]-Platzhalter markiert und müssen vor Veröffentlichung final
              bestätigt werden.
            </span>
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
            Die Nutzung von Briefkasten AI setzt ein Benutzerkonto voraus. Je nach Nutzung
            werden folgende Daten verarbeitet:
          </p>
          <ul>
            <li>
              <strong>Konto- und Anmeldedaten:</strong> Zur Anmeldung wird der Dienst Supabase
              Auth eingesetzt (siehe Abschnitt 4). Dabei werden Ihre E-Mail-Adresse sowie eine
              von Supabase vergebene, eindeutige technische Nutzer-ID verarbeitet und in
              unserer eigenen Datenbank mit Ihrem Konto verknüpft (Erstellungsdatum des
              Kontos). Ein Passwort wird, falls Sie sich per Passwort anmelden, ausschließlich
              bei Supabase gespeichert und verwaltet - es erreicht unsere eigene
              Anwendung nicht.
            </li>
            <li>
              <strong>Anmelde-/Sitzungstoken im Browser:</strong> Nach der Anmeldung speichert
              die Supabase-Client-Bibliothek ein Sitzungs-Token (JSON Web Token) im{' '}
              <code>localStorage</code> Ihres Browsers, damit Sie beim erneuten Öffnen der
              Anwendung angemeldet bleiben. Es handelt sich dabei technisch{' '}
              <strong>nicht um ein Cookie</strong>, sondern um einen im Browser gespeicherten
              Datensatz, der ausschließlich von dieser Anwendung selbst (nicht von Dritten)
              ausgelesen wird und nicht für Tracking, Werbung oder Reichweitenmessung genutzt
              wird. Diese Speicherung ist zur Bereitstellung des von Ihnen ausdrücklich
              genutzten Dienstes (angemeldeter Zugang) technisch erforderlich und erfolgt
              daher auf Grundlage von § 25 Abs. 2 Nr. 2 TTDSG, ohne dass eine gesonderte
              Einwilligung erforderlich ist.
            </li>
            <li>
              <strong>Hochgeladene Dokumente:</strong> Die Datei, die Sie über die Upload-Funktion
              auswählen (PDF, PNG, JPG, JPEG oder TIFF). Die Datei wird auf dem Server unter einem
              zufällig generierten Dateinamen gespeichert, nicht unter dem Originalnamen, und
              Ihrem Konto zugeordnet.
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
              (Dokumenttyp, erkannte Sprache, türkische Erklärung, erkannte Daten/Fristen,
              erkannte Entitäten wie z. B. Namen, Aktenzeichen oder Versicherungsnummern,
              Absenderkategorie, Prioritätseinstufung) in der Datenbank gespeichert.
            </li>
            <li>
              <strong>Zahlungs-/Abonnementdaten:</strong> Falls Sie ein kostenpflichtiges
              Abonnement abschließen, wird die Zahlungsabwicklung über Stripe durchgeführt
              (siehe Abschnitt 4). In unserer eigenen Datenbank speichern wir dabei keine
              Zahlungs- bzw. Kartendaten, sondern lediglich technische Verknüpfungsdaten: die
              von Stripe vergebene Kunden- und Abonnement-ID, den gebuchten Tarif sowie den
              Abonnementstatus und das Ende der aktuellen Abrechnungsperiode.
            </li>
            <li>
              <strong>Technische Zugriffsdaten:</strong> Wie bei jedem Webserver-Betrieb können
              beim Aufruf der Anwendung technische Daten (z. B. IP-Adresse, Zeitpunkt, aufgerufene
              Adresse) im Server-Prozess bzw. beim vorgeschalteten Reverse Proxy (siehe Abschnitt
              6) anfallen. Die Anwendung selbst speichert diese Daten aktuell nicht dauerhaft in
              der Datenbank.
            </li>
            <li>
              <strong>Fehlerprotokolle:</strong> Bei unerwarteten technischen Fehlern wird ein
              Fehlerereignis serverseitig protokolliert, um die Ursache nachvollziehen zu können.
              Diese Protokolle werden nicht an Dritte weitergegeben.
            </li>
          </ul>
          <p>
            Über das im vorigen Absatz beschriebene technisch notwendige Anmelde-Token hinaus
            verwendet die Anwendung <strong>keine</strong> Cookies und <strong>keine</strong>{' '}
            Analyse- oder Tracking-Tools (z. B. Google Analytics) und keinen Newsletter.
          </p>

          <h2>3. Zweck der Verarbeitung</h2>
          <p>
            Die Verarbeitung dient der Bereitstellung Ihres Benutzerkontos sowie der von Ihnen
            angefragten Funktion: dem Auslesen des Textinhalts Ihres hochgeladenen Dokuments
            und, sofern von Ihnen angefordert, der KI-gestützten Analyse und Erklärung dieses
            Dokuments. Sofern Sie ein kostenpflichtiges Abonnement abschließen, dient die
            Verarbeitung zusätzlich der Abwicklung dieses Vertragsverhältnisses.
          </p>
          <p>
            Rechtsgrundlage ist in der Regel Art. 6 Abs. 1 lit. b DSGVO (Erfüllung des
            Nutzungsvertrags bzw. Durchführung vorvertraglicher Maßnahmen). Diese Einschätzung
            sollte im Rahmen der rechtlichen Prüfung final bestätigt werden.
          </p>

          <h2>4. Auftragsverarbeiter und Weitergabe an Dritte</h2>
          <p>
            Zur Erbringung des Dienstes werden folgende externe Anbieter eingesetzt:
          </p>
          <ul>
            <li>
              <strong>Supabase (Authentifizierung):</strong> Die Verwaltung von
              Benutzerkonten, Anmeldedaten und Sitzungen (siehe Abschnitt 2) erfolgt über den
              Dienst Supabase. Supabase erhält dabei Ihre E-Mail-Adresse sowie Ihre
              Anmeldeaktivität. Der genaue Serverstandort/die Region des verwendeten
              Supabase-Projekts ist [BESTÄTIGEN - im Supabase-Dashboard unter Project Settings
              → General → Region einsehbar]; sofern dieser außerhalb der EU/des EWR liegt,
              handelt es sich um eine Drittlandübermittlung, deren Rechtsgrundlage (z. B.
              EU-Standardvertragsklauseln) noch zu bestätigen ist. Mit Supabase ist ein
              Auftragsverarbeitungsvertrag abzuschließen bzw. dessen Bestehen zu bestätigen
              [BESTÄTIGEN].
            </li>
            <li>
              <strong>NVIDIA (build.nvidia.com, KI-Analyse):</strong> Der aktuell aktive
              KI-Anbieter dieser Anwendung ist NVIDIA (NVIDIA NIM API). Der aus Ihrem Dokument
              extrahierte Textinhalt wird zur Analyse an die NVIDIA-API übermittelt. NVIDIA
              Corporation ist ein US-amerikanischer Anbieter außerhalb der EU. Eine förmliche
              Auftragsverarbeitungsvereinbarung mit NVIDIA sowie eine abschließende Bewertung
              der Rechtsgrundlage für diese Drittlandübermittlung stehen noch aus und sollten
              vor einem öffentlichen Betrieb geklärt werden [BESTÄTIGEN].
            </li>
            <li>
              <strong>Claude API (Anthropic) - optionaler Anbieter:</strong> Die Anwendung
              unterstützt technisch auch die Analyse über die Claude API von Anthropic
              (ebenfalls ein US-amerikanischer Anbieter) als Alternative zu NVIDIA. Ob dieser
              Anbieter anstelle von NVIDIA aktiv ist, hängt von der Serverkonfiguration ab; im
              produktiven Betrieb ist derzeit NVIDIA aktiv.
            </li>
            <li>
              <strong>Ollama (lokaler Anbieter) - optionaler Anbieter:</strong> Alternativ kann
              die Anwendung so konfiguriert werden, dass die Analyse über eine selbst
              betriebene Ollama-Instanz erfolgt. In diesem Fall wird der Dokumenttext nicht an
              einen externen Dritten übertragen. Im produktiven Betrieb ist dieser Anbieter
              derzeit nicht aktiv.
            </li>
            <li>
              <strong>Stripe (Zahlungsabwicklung):</strong> Sofern Sie ein kostenpflichtiges
              Abonnement abschließen, erfolgt die Zahlungsabwicklung über Stripe. Ihre
              Zahlungsdaten (z. B. Kartendaten) werden dabei ausschließlich von Stripe erhoben
              und verarbeitet und erreichen unsere eigene Anwendung zu keinem Zeitpunkt
              vollständig - wir erhalten von Stripe lediglich die in Abschnitt 2 genannten
              Verknüpfungsdaten. Die für Ihr Stripe-Konto zuständige Stripe-Vertragspartei bzw.
              deren Sitz (z. B. Stripe Payments Europe, Ltd. für EWR-Kundinnen und -Kunden
              gegenüber Stripe, Inc. in den USA) ist [BESTÄTIGEN].
            </li>
            <li>
              <strong>Hetzner Online GmbH (Hosting):</strong> Die Anwendung wird auf einem
              Server der Hetzner Online GmbH betrieben (siehe Abschnitt 6). Mit Hetzner ist ein
              Auftragsverarbeitungsvertrag abzuschließen bzw. dessen Bestehen zu bestätigen
              [BESTÄTIGEN].
            </li>
          </ul>
          <p>
            Eine darüber hinausgehende Weitergabe Ihrer Daten an weitere Dritte findet nicht
            statt.
          </p>

          <h2>5. Speicherdauer und Löschung</h2>
          <p>
            Ihr Benutzerkonto sowie die damit verknüpften Dokumente, extrahierten Texte und
            KI-Analyseergebnisse verbleiben gespeichert, solange Ihr Konto besteht. Es ist
            aktuell <strong>kein automatisierter Selbstbedienungs-Löschmechanismus</strong> für
            Ihr Konto in der Anwendung implementiert; eine Löschung kann derzeit nur manuell
            durch den Verantwortlichen erfolgen, z. B. auf Ihre Anfrage hin (siehe Abschnitt 7).
            Eine Selbstbedienungsfunktion zur Kontolöschung ist in Planung; dieser Abschnitt
            wird aktualisiert, sobald sie verfügbar ist.
          </p>

          <h2>6. Hosting</h2>
          <p>
            Die Anwendung wird produktiv auf einem Server der Hetzner Online GmbH betrieben
            (Standort: Rechenzentrum [BESTÄTIGEN, laut interner Angabe Nürnberg], Deutschland).
            Die Auslieferung erfolgt über einen Reverse Proxy (Caddy) mit automatisch
            bezogenem TLS-Zertifikat (Let's Encrypt), sodass sämtlicher Datenverkehr zwischen
            Ihrem Browser und dem Server verschlüsselt ist.
          </p>

          <h2>7. Ihre Rechte</h2>
          <p>
            Ihnen stehen nach der DSGVO folgende Rechte zu: Auskunft (Art. 15), Berichtigung
            (Art. 16), Löschung (Art. 17), Einschränkung der Verarbeitung (Art. 18),
            Datenübertragbarkeit (Art. 20) sowie Widerspruch gegen die Verarbeitung (Art. 21).
          </p>
          <p>
            Da die Anwendung aktuell noch keine automatisierte Selbstbedienungsfunktion (z. B.
            einen Lösch-Button für Ihr Konto) für diese Rechte bietet, können entsprechende
            Anfragen formlos per E-Mail an{' '}
            <a href="mailto:khsttnc@gmail.com">khsttnc@gmail.com</a> gerichtet werden.
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
