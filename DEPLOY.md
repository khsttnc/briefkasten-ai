# Briefkasten AI — Production Deploy (briefkastenai.de)

Hedef sunucu: Hetzner CPX22, Ubuntu 24.04, IP `46.225.50.238`.

Bu doküman, sunucuya hiç dokunulmamış (Docker kurulu değil) bir Ubuntu
24.04 kurulumundan başlayarak `briefkastenai.de`'yi ayağa kaldırmayı
anlatır.

## 0. Ön koşul: DNS

Deploy'a başlamadan önce, domain sağlayıcında şu A kaydını oluştur (henüz
yapmadıysan):

```
briefkastenai.de.   A   46.225.50.238
```

Caddy, TLS sertifikasını (Let's Encrypt) otomatik alırken bu DNS kaydının
zaten yayılmış olmasını bekler. DNS yayılması birkaç dakika ile birkaç saat
sürebilir — 3. adıma geçmeden önce `dig briefkastenai.de +short` ile IP'nin
göründüğünü doğrula.

## 1. Sunucuya bağlan

```bash
ssh root@46.225.50.238
```

(Hetzner'ın verdiği kullanıcı/anahtar farklıysa ona göre uyarla.)

## 2. Sistemi güncelle

```bash
apt update && apt upgrade -y
```

## 3. Docker Engine + Compose plugin kur

Ubuntu 24.04 için resmi Docker apt deposu:

```bash
# Eski/çakışan paketleri kaldır (varsa)
for pkg in docker.io docker-doc docker-compose podman-docker containerd runc; do
  apt remove -y $pkg 2>/dev/null || true
done

apt install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Doğrula:

```bash
docker --version
docker compose version
```

## 4. Güvenlik duvarı (ufw)

Sadece SSH (22), HTTP (80) ve HTTPS (443) açık kalsın; başka her şey
kapalı olsun. **Sıra önemli** — önce SSH'ı izin listesine al, sonra
`enable` çalıştır; aksi halde bağlantın kopar ve sunucuya bir daha
giremezsin.

```bash
apt install -y ufw
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw default deny incoming
ufw default allow outgoing
ufw enable
```

`ufw enable` sırasında "This could disrupt existing ssh connections"
uyarısını `y` ile onayla — 22 zaten yukarıda izinli, mevcut SSH oturumun
kopmaz.

Doğrula:

```bash
ufw status verbose
```

Çıktıda sadece `22/tcp`, `80/tcp`, `443/tcp` ALLOW olarak görünmeli.
(SQLite tamamen dosya tabanlı ve container dışına hiçbir port açmıyor —
zaten dışarıdan erişilebilir bir veritabanı portu yok, ekstra bir kural
gerekmiyor.)

## 5. Repoyu çek

```bash
apt install -y git
git clone https://github.com/khsttnc/briefkasten-ai.git /opt/briefkasten-ai
cd /opt/briefkasten-ai
```

## 6. Production ortam değişkenlerini ayarla

```bash
cp .env.production.example backend/.env
cp .env.production.example .env
nano backend/.env   # gerçek backend değerlerini gir
nano .env           # sadece VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY'i gir
```

Doldurman gerekenler (bkz. dosyadaki açıklamalar):

- `NVIDIA_API_KEY` (AI_PROVIDER=nvidia zaten örnek dosyada varsayılan)
- `SUPABASE_JWT_SECRET`
- `STRIPE_WEBHOOK_SECRET` (webhook kullanılıyorsa)
- `FRONTEND_ORIGIN` zaten `https://briefkastenai.de` olarak dolu, dokunma
- `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` (Supabase Dashboard ->
  Project Settings -> API)

`DATABASE_URL` ve `UPLOAD_FOLDER` alanlarını **boş bırak** —
`docker-compose.yml` bunları zaten kalıcı volume'a göre otomatik
ayarlıyor, buradaki değer dikkate alınmaz.

İki ayrı dosyaya ihtiyaç var çünkü ikisinin okunma yolu farklı:
`backend/.env` container'a `env_file` ile çalışma zamanında enjekte
edilir, ama `VITE_SUPABASE_URL`/`VITE_SUPABASE_ANON_KEY` Vite tarafından
**build zamanında** koda gömülür - bu yüzden repo kökündeki `.env`
dosyasından `docker-compose.yml`'in `frontend.build.args` alanına
(`${VITE_SUPABASE_URL}` şeklinde) akmaları gerekiyor. `backend/.env`'e
yazmak yeterli değil, frontend build'i o dosyayı hiç görmüyor.

Ne `backend/.env` ne de kök `.env` asla commit'lenmeli; repo'nun
`.gitignore`'ında zaten hariç tutuluyorlar.

## 7. Build ve ayağa kaldır

```bash
docker compose build
docker compose up -d
```

İlk `up` sırasında backend container'ı önce `alembic upgrade head`
çalıştırıp veritabanı şemasını oluşturur/günceller, sonra uvicorn'u
başlatır (bkz. `backend/entrypoint.sh`).

## 8. Doğrula

```bash
docker compose ps
```

Üç servis de (`backend`, `frontend`, `caddy`) `running` olmalı; `backend`
birkaç saniye içinde `healthy` durumuna geçmeli (bkz. `docker-compose.yml`
healthcheck — `/health` endpoint'ini kontrol eder).

Dışarıdan uçtan uca test:

```bash
curl -i https://briefkastenai.de/api/health
# {"status":"ok"} dönmeli

curl -i https://briefkastenai.de/
# frontend'in index.html'i dönmeli
```

Caddy ilk istekte Let's Encrypt sertifikasını otomatik alır — `curl`
komutları birkaç saniye gecikebilir, `docker compose logs caddy` ile
sertifika alım sürecini izleyebilirsin.

## Loglar / sorun giderme

```bash
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f caddy
```

Backend ayağa kalkmıyorsa çoğunlukla `backend/.env` içinde eksik/yanlış
bir değer vardır (özellikle `NVIDIA_API_KEY` veya
`SUPABASE_JWT_SECRET`) — logda hata mesajı görünür.

## Güncelleme / yeniden deploy

```bash
cd /opt/briefkasten-ai
git pull
docker compose build
docker compose up -d
```

Alembic migration'ları her `up` çalıştığında otomatik uygulanır
(entrypoint.sh). Elle bir migration komutu çalıştırman gerekirse:

```bash
docker compose exec backend alembic upgrade head
```

## Geri alma (rollback)

Deploy sonrası bir şey bozulduysa:

```bash
docker compose down
git log --oneline -5      # önceki iyi commit'i bul
git checkout <önceki-commit-hash>
docker compose build
docker compose up -d
```

`db_data` ve `caddy_data`/`caddy_config` named volume'ları `docker
compose down` ile silinmez (veritabanı ve SSL sertifikaları kalıcı kalır)
— sadece `docker compose down -v` volume'ları da siler, bunu **kasıtlı
olarak istemediğin sürece çalıştırma**.

Eğer sorun sadece son build'deyse ve bir önceki image hâlâ diskte
duruyorsa, `git checkout` yapmadan da geri dönebilirsin:

```bash
docker compose down
docker image ls | grep briefkasten   # önceki image ID'sini bul
docker compose up -d --no-build      # mevcut (son build edilen) image'ı kullanır
```

Kalıcı bir geri dönüş için en güvenilir yol her zaman `git checkout` +
`docker compose build`'dır — image tag'leri compose tarafından otomatik
yönetildiği için elle image seçmek yalnızca en son build hâlâ diskteyken
işe yarar.
