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
- `SUPABASE_URL` (backend/.env'de - JWKS doğrulaması için proje URL'i,
  paylaşılan bir secret değil)
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

## 9. Yedekleme (Backup) kurulumu

Test edilmemiş bir yedek, yedek değildir - bu yüzden bu bölümdeki kurulumu
tamamladıktan sonra **mutlaka** en alttaki "Restore" prosedürünü bir kez
gerçekten çalıştırıp doğrula.

Yedekleme günlük olarak SQLite veritabanının WAL-güvenli online kopyasını
ve `uploads/` klasörünü alır, [Restic](https://restic.net/) ile bir
repository'ye şifreli ve rotasyonlu şekilde gönderir. Restic client-side
(istemci tarafında) şifreliyor - repository'yi nerede tutarsan tut,
içeriği asla düz görünmez.

**⚠️ ÖNEMLİ - yerel yedek neyi korur, neyi korumaz:** Aşağıdaki 9.1-9.3
adımları sadece bu sunucunun kendi diskinde (`/var/backups/briefkasten-restic`)
bir repository kurar. Bu, **yanlışlıkla dosya silme veya uygulama
seviyesinde bozulmaya karşı** koruma sağlar (ör. `docker compose down -v`
çalıştırmak, bir migration'ın veriyi bozması). Ama yedek asıl veriyle
**aynı diskte/sunucuda** olduğu için, **disk arızasına veya sunucunun
tamamen kaybına karşı hiçbir koruma sağlamaz** - disk giderse ikisi de
birden gider. **İlk gerçek kullanıcıdan önce**, 9.4'teki opsiyonel uzak
hedef (Hetzner Storage Box veya benzeri) mutlaka kurulmalı. Bu proje henüz
gerçek kullanıcı verisi barındırmadığı için uzak hedef şimdilik bilinçli
olarak ertelendi (bkz. TODO.md).

### 9.1 Araçları kur

```bash
apt install -y restic sqlite3
mkdir -p /var/backups/briefkasten-restic
```

### 9.2 Yerel repository parolası

```bash
openssl rand -base64 32 > /root/.restic-password-local
chmod 600 /root/.restic-password-local
```

**Bu parolayı KAYBEDERSEN yerel yedekler kalıcı olarak kurtarılamaz hale
gelir** (Restic'te "arka kapı" yok). Bir kopyasını sunucu dışında (ör. bir
şifre yöneticisinde) da sakla - aksi halde "yerel yedek" + "kaybolan
parola" = hiç yedek yok demek.

```bash
cat > /root/.restic-env <<'EOF'
export RESTIC_LOCAL_REPOSITORY="/var/backups/briefkasten-restic"
export RESTIC_LOCAL_PASSWORD_FILE="/root/.restic-password-local"
EOF
chmod 600 /root/.restic-env
```

Repository'i script ilk çalıştığında otomatik başlatıyor (`backup.sh`
içindeki `_restic_ensure_initialized`), elle `restic init` gerekmiyor.

### 9.3 Script'i çalıştırılabilir yap ve cron'a ekle

```bash
chmod +x /opt/briefkasten-ai/backend/scripts/backup.sh
crontab -e
```

Aşağıdaki satırı ekle (her gece 03:00'te çalışır, çıktısını loglar):

```
0 3 * * * /opt/briefkasten-ai/backend/scripts/backup.sh >> /var/log/briefkasten-backup.log 2>&1
```

Elle bir kez deneyerek doğrula:

```bash
/opt/briefkasten-ai/backend/scripts/backup.sh
source /root/.restic-env
RESTIC_REPOSITORY="$RESTIC_LOCAL_REPOSITORY" RESTIC_PASSWORD_FILE="$RESTIC_LOCAL_PASSWORD_FILE" restic snapshots
```

Uzak hedef henüz kurulmadığı için çıktıda şu uyarı görünmeli - bu normal,
hata değil:

```
WARNING: no remote backup target configured (/root/.restic-env-remote not found).
WARNING: backups exist ONLY on this server and do NOT survive disk/server loss.
WARNING: set up an off-server target before real user data exists - see DEPLOY.md 'Yedekleme'.
```

### 9.4 Uzak hedef ekleme (Storage Box) - ilk gerçek kullanıcıdan ÖNCE yapılmalı

Bir Hetzner Storage Box satın alınca (SFTP kullanıcı adı/host Hetzner
Robot panelinde görünür), `backup.sh` kodunda hiçbir değişiklik
gerekmiyor - sadece aşağıdaki dosyayı oluşturmak yeterli, script bir
sonraki çalışmasında otomatik olarak hem yerel hem uzak yedek almaya
başlar:

```bash
ssh-keygen -t ed25519 -f /root/.ssh/storagebox -N ""
cat /root/.ssh/storagebox.pub
# Çıkan public key'i Hetzner Robot panelinde Storage Box'ın
# "SSH-Keys" bölümüne ekle, sonra doğrula:
ssh -i /root/.ssh/storagebox -p 23 u123456@u123456.your-storagebox.de

openssl rand -base64 32 > /root/.restic-password-remote
chmod 600 /root/.restic-password-remote

cat > /root/.restic-env-remote <<'EOF'
export RESTIC_REMOTE_REPOSITORY="sftp://u123456@u123456.your-storagebox.de:23//home/briefkasten-backup"
export RESTIC_REMOTE_PASSWORD_FILE="/root/.restic-password-remote"
export RESTIC_SFTP_COMMAND="ssh -i /root/.ssh/storagebox -p 23 u123456@u123456.your-storagebox.de -s sftp"
EOF
chmod 600 /root/.restic-env-remote
```

(`u123456`, host adı ve hedef path'i kendi Storage Box bilgilerinle
değiştir.) Elle bir kez çalıştırıp doğrula:

```bash
/opt/briefkasten-ai/backend/scripts/backup.sh
source /root/.restic-env-remote
RESTIC_REPOSITORY="$RESTIC_REMOTE_REPOSITORY" RESTIC_PASSWORD_FILE="$RESTIC_REMOTE_PASSWORD_FILE" restic snapshots
```

Bu sefer "no remote backup target configured" uyarısı **görünmemeli** ve
"Remote backup completed" satırı çıkmalı.

### 9.5 Yedeği kendi bilgisayarına indirme

Yerel repository tek bir dizin (`/var/backups/briefkasten-restic`) - şifreli
olduğu için parolasız hiçbir işe yaramaz, dolayısıyla olduğu gibi kendi
bilgisayarına kopyalamak güvenlidir. `rsync` (kesintiye dayanıklı, sadece
değişeni indirir) önerilir:

```bash
rsync -avz -e ssh root@46.225.50.238:/var/backups/briefkasten-restic/ ./briefkasten-backup/
```

`scp` ile tam kopya (daha basit, ama her seferinde her şeyi yeniden indirir):

```bash
scp -r root@46.225.50.238:/var/backups/briefkasten-restic ./briefkasten-backup
```

İndirdikten sonra kendi bilgisayarında da açabilirsin (restic parolan
lazım):

```bash
export RESTIC_REPOSITORY=./briefkasten-backup
export RESTIC_PASSWORD_FILE=/path/to/restic-password-local  # sunucudan ayrı güvenli bir yerden al
restic snapshots
```

## Loglar / sorun giderme

```bash
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f caddy
```

Backend ayağa kalkmıyorsa çoğunlukla `backend/.env` içinde eksik/yanlış
bir değer vardır (özellikle `NVIDIA_API_KEY` veya `SUPABASE_URL`) — logda
hata mesajı görünür.

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

## Restore (yedekten geri yükleme)

Bu, kod geri alma (yukarıdaki rollback) değil - veritabanı/dosya
**veri kaybı** durumunda (disk arızası, yanlışlıkla silme, `docker compose
down -v`) kullanılan felaket kurtarma prosedürüdür. **Geri yükleme mevcut
canlı veriyi kalıcı olarak üzerine yazar** - sadece gerçekten gerektiğinde
çalıştır.

**Hangi repository'den restore edileceğine dikkat et:** disk arızası veya
sunucunun tamamen kaybı gibi bir senaryoda yerel repository de veriyle
birlikte gitmiş olur - o durumda tek seçenek uzak (remote) repository'dir
(kurulmuşsa). Yanlışlıkla silme gibi sunucunun kendisi sağlam kaldığı
durumlarda yerel repository yeterlidir.

```bash
# 1. Uygulamayı durdur - restore sırasında hem eski hem yeni veriye aynı
#    anda yazılmasını önlemek için.
cd /opt/briefkasten-ai
docker compose down

# 2. Hangi repository'den restore edeceğine karar ver, RESTIC_REPOSITORY
#    ve RESTIC_PASSWORD_FILE'ı ona göre ayarla. Yerel için:
source /root/.restic-env
export RESTIC_REPOSITORY="$RESTIC_LOCAL_REPOSITORY"
export RESTIC_PASSWORD_FILE="$RESTIC_LOCAL_PASSWORD_FILE"
# ...ya da uzak için (sunucu/disk kaybı senaryosu - yeni bir sunucuda
# /root/.restic-env-remote'u elle yeniden oluşturup onu kullan):
#   source /root/.restic-env-remote
#   export RESTIC_REPOSITORY="$RESTIC_REMOTE_REPOSITORY"
#   export RESTIC_PASSWORD_FILE="$RESTIC_REMOTE_PASSWORD_FILE"

# Hangi snapshot'ın geri yükleneceğini belirle.
restic snapshots

# 3. Seçilen snapshot'ı geçici bir klasöre geri yükle (doğrudan volume'un
#    üzerine değil - önce içeriği gözden geçirmek için).
restic restore <snapshot-id> --target /root/briefkasten-restore

# 4. Restore edilen dosyaları gerçek volume konumuna kopyala. Volume'un
#    host'taki gerçek yolunu bul:
VOLUME_MOUNTPOINT="$(docker volume inspect -f '{{ .Mountpoint }}' \
    "$(docker volume ls -q --filter label=com.docker.compose.project=briefkasten-ai --filter label=com.docker.compose.volume=db_data)")"

cp /root/briefkasten-restore/root/briefkasten-backup-staging/briefkasten.db "$VOLUME_MOUNTPOINT/briefkasten.db"
rm -rf "$VOLUME_MOUNTPOINT/uploads"
cp -a /root/briefkasten-restore/root/briefkasten-backup-staging/uploads "$VOLUME_MOUNTPOINT/uploads"

# 5. Uygulamayı yeniden başlat ve doğrula.
docker compose up -d
curl -i https://briefkastenai.de/api/health
# Ardından tarayıcıdan giriş yapıp bilinen bir belgenin göründüğünü kontrol et.
```

**Bu prosedürü şimdi, gerçek bir acil durum olmadan, bir kez baştan sona
gerçekten çalıştır** - hem doğru çalıştığını kanıtlar hem de bir sonraki
sefer panik anında değil, sakin kafayla öğrenilmiş olur. Ayrıca periyodik
olarak (ör. üç ayda bir) tekrar dene; restic/Storage Box tarafında sessizce
bozulan bir şey olup olmadığını sadece gerçek bir restore denemesi ortaya
çıkarır.
