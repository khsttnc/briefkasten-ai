# TODO

## BURADAN DEVAM ET

Son güncelleme: **2026-08-27**, son commit **`710dd49`**. Kullanıcı
2026-08-27'den itibaren ~20 gün (tahmini dönüş ~2026-09-16) uzakta
olacak. Bu bölüm o dönüşte sıfırdan bağlam kurmak için yazıldı.

**Sıradaki iş:** C ve D maddelerine (aşağıda) karar vermek. İkisi de
aynı gerçek production belgesinden (ADAC Autoversicherung
Widerrufsbestätigung, 1350 karakter) çıktı ve henüz kod yazılmadı -
sadece teşhis/tartışma yapıldı.

**Neden:** Bu belge `Kündigung` olarak yanlış sınıflandırıldı (aslında
kullanıcının kendi cayma talebinin onayı, ADAC'ın feshi değil) ve
`requires_action`/`action_summary` metinde gerçekten var olan riski
(ADAC, Zulassungsbehörde'deki sigorta teyidini geri çekecek - zamanında
yeni teyit sunulmazsa araç ruhsatı iptal riski) net biçimde
söylemiyordu. Aynı oturumda ayrı bir hata olarak, bu belgede olmayan
14 günlük bir süre de uydurulmuştu - o **düzeltildi** (bkz. commit
`710dd49`), C ve D **düzeltilmedi**.

**İlgili dosyalar:** `backend/app/providers/ollama_provider.py`
(taksonomi enum'u `CLASSIFIED_DOCUMENT_TYPE_KEY` civarı, satır ~272),
`backend/app/document_intelligence.py` (yeni taksonomi değeri işlemesi
gerekirse), `backend/app/priority_engine.py` (yeni kategori önceliğe
nasıl yansımalı).

**İlk yapılacak:** aşağıdaki "Çoklu belge bölme" ve "Prod bilgileri"
bölümlerini oku - dönüşte önce prod'da deploy'un gerçekten yapılıp
yapılmadığını ve `multi_document_heuristic` log satırlarını kontrol et,
sonra C/D'ye geç.

---

## Açık tasarım kararları (henüz kod yazılmadı)

### C) Taksonomi eksiği: Widerrufsbestätigung/Bestätigung kategorisi yok

`classified_document_type` enum'u (`ollama_provider.py`'da
`CLASSIFIED_DOCUMENT_TYPE_KEY` talimatı): Mahnbescheid, Anhörung,
Änderungsbescheid, Steuerbescheid, Bescheid, Mahnung, Kündigung,
Rechnung, Formular, Information. **Bir onay/teyit mektubu kategorisi
yok.** Model bu yüzden ADAC'ın Widerrufsbestätigung'unu (kullanıcının
KENDİ cayma talebini onaylayan mektup) `Kündigung`'a (bir tarafın
sözleşmeyi feshettiği mektup) zorladı - yön tamamen ters: biri
kullanıcının kendi isteğinin onayı, diğeri karşı tarafın feshi.

Konuşulan yön (karar verilmedi): enum'a ayrı bir `Bestätigung` (veya
`Widerrufsbestätigung`) değeri eklemek. Açık sorular: bu yeni kategori
`priority_engine.py`'da nasıl puanlanmalı (muhtemelen düşük - kullanıcı
zaten istediği şeyi almış), ve TODO'daki "contract/terms" şema
önerisiyle (aşağıda, "Diğer açık maddeler" altında) ne kadar örtüşüyor
- o öneri "sözleşme vs. resmi mektup" ekseninde, bu ise "resmi mektup
kendi içinde: fesih vs. onay" ekseninde - farklı ama ilişkili eksenler.

### D) Süre belirtilmemiş ama gerçek risk taşıyan belgeler

Aynı ADAC belgesinde **hiçbir Frist/son tarih yok**, ama metnin
içinde gerçek bir risk var: ADAC, Zulassungsbehörde'deki sigorta
teyidini geri çekecek; kullanıcı başka bir sigortacıdan zamanında yeni
teyit sunmazsa aracın ruhsatı iptal edilebilir. Sistem bunu
`requires_action`/`action_summary` alanlarında net söylemedi.

Bu, "süre yok → düşük öncelik" varsayımının her zaman doğru olmadığını
gösteriyor - **açık, çözülmemiş bir tasarım sorusu:** böyle "süre
belirtilmemiş ama sonucu ciddi" durumları nasıl yakalamalı? Olası
yönler (tartışılmadı, sadece ilk akla gelenler):
- Prompt'a "süre olmasa bile önemli bir sonuç/risk var mı" diye ayrı
  bir soru eklemek (yeni bir boolean signal key, örn.
  `has_consequence_without_deadline`).
- `priority_engine.py`'ye "Frist yok ama requires_action=true ve belirli
  anahtar kelimeler (widerrufen, zurückziehen, entziehen) var" gibi
  deterministik bir kural eklemek.

### Çoklu belge bölme (faz b) - faz (a) yayında, doğrulama bekleniyor

Faz (a) (commit `0ff7407`, prod'a push edildi - deploy'un gerçekten
çalıştığı DOĞRULANMADI, aşağıdaki "Prod bilgileri"ne bak) şunu yaptı:
- Sayfa ayracı düzeltmesi (native PDF çıkarma artık sayfalar arasında
  ayraç koyuyor - eskiden hiç yoktu, kelimeler birbirine yapışabiliyordu).
- Ucuz sezgisel tespit: `document_processing.detect_possible_multiple_documents`
  - sayfa sınırı + tekrarlayan Almanca belge-türü damgaları + tekrarlayan
    IBAN, en az 2/3 sinyal gerekiyor. Gerçek örnek (Crawford formu + 4
    Advanzia ekstresi) üzerinde test edildi, doğru tespit etti.
- Tespit edilirse: prompt'a sinyal + mevcut `important_dates` dizisi/
  `multiple_deadlines_detected` alanları üzerinden kısmi bilgi + kullanıcıya
  deterministik bir uyarı notu (`action_summary`'ye ekleniyor).

**Bekleyen:** gerçek kullanıcı belgeleriyle tespitin isabet oranını
ölçmek (`docker compose logs backend | grep multi_document_heuristic`).
İsabet iyiyse faz (b)'ye (her tespit edilen alt-belge için ayrı
`Document` satırı - bkz. sohbet geçmişindeki tam mimari analiz) geçmeyi
düşün. Faz (b) N kat LLM çağrısı demek - **rate limiting'e dikkat**
(`AI_ANALYZE_RATE_LIMIT`, hesap başına 10/dakika, `config.py`) ve
paralel çağrı + gecikme yönetimi gerekir.

### Yapılandırılmış açıklama şeması

`turkish_explanation`'ı tek paragraf yerine sabit alanlara (ne/ne
yapmalı/vade) bölme fikri (bkz. aşağıdaki "Diğer açık maddeler"deki
free-text-determinism maddesinin sonu). Çoklu belge bölmeyle **birlikte
tasarlanması ZORUNLU değil** - farklı katmanlar (biri kayıt sayısı,
diğeri tek kaydın alan yapısı). Not: faz (b) (gerçek bölme) yapılırsa
her alt-belge zaten tek/temiz bir konuya sahip olacağı için bu işin
aciliyeti azalır.

Bu şema, `entity_validation.py`'deki ödeme iddiası tespitini de
gereksizleştirebilir: `_drop_if_unverifiable_payment_narrative`/
`_drop_if_unevidenced_payment_claim` şu an serbest metinde Türkçe "öde"
kökünü arayıp kaynak metinde tutar/fiil kanıtı bakıyor - 2026-08-27
itibarıyla bu kontrolün **4. kalibrasyonu** yapıldı (her seferinde bir
yanlış-pozitif düzeltilirken başka bir yanlış-negatif riski taşıdı; bkz.
`test_entity_validation.py`'deki `PaymentEvidenceTighteningTestCase`,
`PaymentInformationVsDemandRegressionTestCase`,
`NegatedPaymentClaimRegressionTestCase`). Eğer `payment_requested`
zaten yapılandırılmış bir alan olarak tutar/son tarihi ayrı taşırsa
(şemanın "ne yapmalı/vade" alanları), serbest metinde kelime arayarak
ödeme iddiası uydurmaya çalışmanın bir anlamı kalmaz - LLM zaten ayrı
bir alana tutar/tarih yazmak zorunda kalır, doğrulama o alan üzerinden
yapılır, serbest metin kontrolüne hiç gerek kalmayabilir.

---

## Bilinen sorunlar

- **2 önceden var olan test hatası** (yeni değil, regresyon değil):
  `test_document_intelligence.py`'deki `EngineFailureIsolationTestCase`
  (`test_deadline_engine_exception_falls_back_to_safe_defaults`,
  `test_priority_engine_exception_falls_back_to_safe_defaults`) -
  `@patch("app.document_intelligence...")` yanlış dotted path
  kullanıyor (`-s backend/app -t .` invocation'ıyla uyuşmuyor). Test
  komutu: `python -m unittest discover -s backend/app -p "test_*.py" -t .`
  Tam olarak bu 2 test başarısız oluyorsa endişelenme, bilinen durum.
- **nemotron-3-nano-30b-a3b ~%20 tekrar-döngüsü** (bir kelimeyi
  binlerce kez tekrarlayıp `max_tokens`'a çarpıyor). Ölçüldü: 10 gerçek
  15K-karakter denemesinden 2'si başarısız. **Tek retry ile hafifletildi**
  (commit `ce52d80`, `nvidia_provider.py`'daki
  `REPETITION_LOOP_MIN_RUN`/`_has_repetition_loop`). Retry sonrası hâlâ
  başarısızsa kullanıcı temiz bir hata görüyor.
- **Model ölçüm tablosu** (2026-08-27, gerçek API çağrılarıyla,
  2K/5K/15K karakterlik belgelerde):

  | Model | 2K | 5K | 15K | Karar |
  |---|---|---|---|---|
  | gpt-oss-120b (eski varsayılan) | 40.7s | >120s TIMEOUT | 9.1s | **ELENDİ** - süre boyutla ilişkisiz, öngörülemez |
  | **nemotron-3-nano-30b-a3b (mevcut varsayılan)** | 3.5s | 4.9s | 3.7-34.5s (~%20 tekrar döngüsü) | **SEÇİLDİ** + tek retry |
  | llama-3.3-70b-instruct | - | - | - | **KULLANILAMIYOR** - NVIDIA API'de HTTP 410, 2026-08-26'da EOL |
  | mistral-nemotron | 2x TIMEOUT | 16.7-17.7s | 14.6-15.6s | test edilmedi - 2K'daki çifte timeout soğuk-başlangıç şüphesi, doğrulanmadı |
  | nemotron-3.5-lightning-30b-a3b | 18.4-28.3s | 12.4-55.9s | 31.1-32.6s | tutarsız, elendi |
  | gemma-4-31b-it | TIMEOUT | TIMEOUT | TIMEOUT | 6/6 yanıtsız, bu testte işlevsiz |

  Karar kriteri: 15 saniye altı + tutarlı süre + geçerli JSON. Detaylı
  metodoloji sohbet geçmişinde (bu dosyada değil).

---

## Prod bilgileri

- **Sunucu:** `root@46.225.50.238` (Hetzner). SSH ile Claude Code'un bu
  ortamdan erişimi **YOK** (private key yok) - deploy/sunucu
  komutlarını kullanıcının kendisinin çalıştırması gerekiyor.
- **Deploy:**
  ```bash
  cd /opt/briefkasten-ai
  git pull
  docker compose build
  docker compose up -d
  ```
  Alembic migration'ları her `up`'ta otomatik uygulanıyor
  (`entrypoint.sh`). **DİKKAT:** `0ff7407` ve `710dd49` commit'lerinin
  gerçekten sunucuda deploy edildiği bu oturumda doğrulanamadı (SSH
  erişimi yok) - dönüşte ilk iş bunu kontrol etmek.
- **Loglar:** `docker compose logs -f backend|frontend|caddy`
- **`.env`:** sunucuda `backend/.env` (repo'ya commit edilmiyor).
  Önemli değişkenler: `AI_PROVIDER=nvidia`, `NVIDIA_API_KEY`,
  `NVIDIA_MODEL` (şu an ayarlı değilse `config.py`'deki varsayılan
  `nvidia/nemotron-3-nano-30b-a3b` kullanılır), `SUPABASE_URL`,
  `SUPABASE_SERVICE_ROLE_KEY`, `STRIPE_WEBHOOK_SECRET`,
  `STRIPE_SECRET_KEY`, `FRONTEND_ORIGIN`.
- **Yedek:** `backend/scripts/backup.sh` (restic, sadece yerel repo -
  aşağıdaki "off-server backup" maddesine bak). Cron'a eklendiği ve
  gerçekten çalıştığı bu oturumda **doğrulanmadı** - kullanıcının kendi
  notuna göre kontrol edilmesi gerekiyor (`crontab -l`,
  `ls -la /var/backups/briefkasten-restic`).
- **Yerel dev DB notu** (sadece `backend/briefkasten.db`, prod'u
  etkilemiyor): `f373e59e4fe9` migration'ı yerelde uygulanmamış -
  `alembic upgrade head` çalıştırılmalı. Veritabanına dokunulmadı.

---

## Diğer açık maddeler (önceden not edilmiş, hâlâ geçerli)

- **429 rate-limit response shows slowapi's raw English message to the user** (confirmed in production: hitting the `/upload` limit returns body text like `"Rate limit exceeded: 10 per 1 minute"`, unmodified). Needs a proper 429 exception handler (see `_rate_limit_exceeded_handler`'s registration in `main.py`) that returns a clear, user-facing Turkish message instead - e.g. "Çok fazla istek gönderdiniz, lütfen bir dakika bekleyin." Frontend (`App.tsx`'s AI-analyze/upload error handling) should also be checked so it actually surfaces that message rather than a generic error banner.
- **Backup has no off-server (remote) target yet - must be added before real user data exists.** `backend/scripts/backup.sh` takes a daily Restic backup of the SQLite DB + `uploads/`, but only to a *local* repository (`/var/backups/briefkasten-restic`, on the same disk as the data it backs up) - the Hetzner Storage Box purchase was deliberately deferred (no real users yet, avoiding the cost until it's needed). This local-only backup protects against accidental deletion or application-level corruption, but provides **zero protection against disk failure or loss of the server itself** - both the data and its backup would be lost together. See DEPLOY.md section 9.4 ("Uzak hedef ekleme") for the one-file setup that adds off-server backup with no code changes required - `backup.sh` already supports it, it just isn't configured yet. Do this before onboarding the first real user.
- **Option B for deadline extraction** (Document Intelligence layer): replace the single `deadline_raw_text` field with a list of extracted deadlines, so `priority_engine` can pick the most urgent/legally significant one deterministically instead of relying on the LLM to pick one phrase via prompt instructions (current Option A). Requires a schema change. See the `multiple_deadlines_detected` fix (commit `f80c8c9`) for why: qwen3:8b did not reliably follow the Option A prompt rule in manual testing.
- **Free-text output (`summary`/`turkish_explanation`/`action_summary`) is not word-for-word deterministic, even at `temperature=0`/`top_p=0.1`+seed** (confirmed in production on the previous default model, nvidia/nemotron-3-nano-30b-a3b: the same document analyzed 3 times produced 3 different explanations, one with an outright content error - an inverted attachment instruction). Measured 2026-08-26 against the live API with a fixed multi-signal document: nemotron produced 5/5 unique `turkish_explanation` wordings at `temperature=0.2` (avg pairwise similarity 0.28, plus an inconsistent `classified_document_type` - null on one call) and still 5/5 unique at `temperature=0`/`top_p=0.1` (avg similarity 0.22 - no better), and a fixed `seed=42` on top made no further difference (still 3/3 unique, avg similarity 0.18) - generation parameters alone do not make this model's long-form output word-for-word deterministic on this API, likely inherent to the serving stack (MoE routing / batched-inference floating-point non-associativity are common causes of server-side non-determinism even at temperature=0 for mixture-of-experts models). Also removed the "Yeniden analiz et" (re-analyze) button from the user-facing UI (`App.tsx`) so a regular user can never trigger a second, possibly different analysis of the same document - the backend's `force=true` cache-bypass still exists for a developer to use directly after a taxonomy/prompt change. Still open: word-for-word consistency itself, and whether a subtler content error could still slip through - `entity_validation.validate_explanatory_text` only catches fabricated dates/payment claims, not arbitrary meaning inversions. The "structured explanation schema" idea above (splitting the explanation into fixed short fields) was discussed as a good independent fix, not started.
- **NVIDIA response can be cut off by `max_tokens` on a genuinely huge/complex document.** `finish_reason == "length"` is now treated as a hard failure (never parses the possibly-truncated content) - see the repetition-loop retry (Bilinen sorunlar above) for the mitigation now in place for nemotron specifically. A real 2,000,000-character test document hit this before `MAX_ANALYSIS_TEXT_CHARS` was capped at 500,000 - unlikely to recur at the new ceiling.
- **Ollama's response format was not checked for an equivalent to NVIDIA's `finish_reason == "length"`.** `providers/ollama_provider.py` has its own completion cap (`DEFAULT_NUM_PREDICT`) with the same theoretical truncated-response risk, but Ollama isn't the active production provider and its `/api/generate` response shape (`done_reason`, if present, depends on the Ollama version) wasn't verified against a real server before writing this note - needs the same real-test-not-guess treatment before adding a matching check.
- **Contract/terms documents need a different analysis schema than official letters** (real finding: a Mietvertrag/Arbeitsvertrag/insurance terms document has no `Frist` the reader must act on, but the current taxonomy - Bescheid/Mahnung/Kündigung/Änderungsbescheid/etc - and its single `deadline_raw_text`/`priority_level` output only make sense for "letter that arrived and may require a response"). Proposed approach (agreed direction, not started - stabilize current bugs first; see also "C) Taksonomi eksiği" above, a related but distinct axis within the official-letter case):
  - Add a `document_class` pre-classification step, LLM-determined: `"official_letter"` (today's existing flow, unchanged) vs. `"contract_or_terms"`.
  - For `contract_or_terms`, use a **separate prompt and output schema** instead of forcing Bescheid/Mahnung/Kündigung classification onto it. Proposed fields (naming to match the existing `_KEY` constant convention in `document_intelligence.py`):
    - `contract_type`: Mietvertrag, Arbeitsvertrag, Versicherungsvertrag, AGB/Nutzungsbedingungen, Darlehensvertrag, Sonstiger Vertrag, or null.
    - `counterparty_name`: the other contracting party (landlord, employer, insurer, ...).
    - `contract_start_date` / `contract_duration_raw_text`: when it begins and its stated term (e.g. "unbefristet", "24 Monate Mindestlaufzeit").
    - `auto_renewal`: boolean - does the contract automatically extend if not cancelled in time.
    - `notice_period_raw_text`: the verbatim notice-period/termination-conditions phrase (e.g. "mit einer Frist von drei Monaten zum Quartalsende kündbar") - this is the contract-domain equivalent of `deadline_raw_text`, but it describes an ongoing right/obligation to terminate, not a one-time response deadline, so it should not be forced into the existing deadline engine's absolute/relative date model.
    - `key_obligations`: short list of what the signing party must do or pay (rent amount, work hours, premium amount, ...).
    - `concerning_clauses`: array of short flagged-clause summaries for anything a layperson should specifically scrutinize (penalty/Vertragsstrafe clauses, automatic renewal, liability waivers, binding arbitration, unusually one-sided termination rights, etc.) - this is the concrete answer to "aleyhime madde var mı?" and is the main net-new value of this schema; needs real example contracts to calibrate what actually gets flagged vs. is normal boilerplate.
  - Needs its own priority/urgency model too - "should the reader worry about this contract" is a different question from `priority_engine.py`'s letter-focused scoring (sender category, Mahnbescheid/Anhörung floor, etc.), which should stay as-is for the official-letter path.
  - Schema/migration impact: likely a second results table or a nullable JSON-ish column set on `Document`, kept separate from the existing deadline/priority columns rather than overloading them.
- **Multi-language output support** (requested for later, not implemented yet). The AI-provider prompts (`ollama_provider.py`, `claude_provider.py`) now read the target output language from a single constant, `document_intelligence.OUTPUT_LANGUAGE_NAME` (currently hardcoded to `"Turkish"`), instead of the literal word being repeated in every prompt string - done specifically so this is easy to extend. To actually offer Arabic/Russian/English/etc, still needed:
  - Make `OUTPUT_LANGUAGE_NAME` a per-request/per-user value (e.g. from a `User.preferred_language` column) instead of a module-level constant.
  - The JSON field name `turkish_explanation` is hardcoded throughout (prompts, `DocumentAIAnalysis.turkish_explanation` column, `services.py`, `frontend/src/api.ts`, `App.tsx`) - a real multi-language feature should rename this to a language-neutral key (e.g. `explanation`), which is a schema + API + frontend change, not just a prompt change.
  - The German-insurance-term-to-Turkish glossary in `ollama_provider.py`'s prompt (Kfz-Haftpflichtversicherung, kasko, Widerruf, etc.) is Turkish-specific domain knowledge; each additional language would need its own glossary, not just a translated instruction.
- **Free-text fields (`action_summary`, `turkish_explanation`) still aren't checked for fabricated dates.** `entity_validation.validate_intelligence_signals`/`validate_important_dates` now verify `document_date`, `effective_date`, `deadline_raw_text` (including relative-duration phrases as of commit `710dd49`), and `important_dates` against the source text, but a hallucinated date embedded inside the free-form Turkish summary/explanation sentences is not caught - those fields are left untouched. Technically feasible: extract DD.MM.YYYY-shaped substrings from `action_summary`/`turkish_explanation` with the same regex `deadline_engine.find_all_dates_in_text` already uses, and drop the whole field (same fail-closed pattern as elsewhere) if it contains a date not found anywhere in the source. Not done yet because it only catches the numeric-digit date form (not written-out day/month names in Turkish, and not fabricated amounts/numbers in general) and wasn't today's priority - worth adding once there's time to calibrate false-positive risk on real documents.
