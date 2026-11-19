#!/usr/bin/env python3
"""
scripts/mobil_yonetici.py
Digital Software Studio — Mobil Canlı Önizleme, Emülatör Yönetimi ve UAT Ekran Yakalama

Android Virtual Device (AVD) emülatörlerini yönetir, ekran görüntüsü (screencap)
alır ve UAT kanıtı olarak workspace/docs/uat_kanitlari/ altına kaydeder.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT / "workspace"
DOCS_DIR = WORKSPACE / "docs"
UAT_KANIT_DIR = DOCS_DIR / "uat_kanitlari"
LOGS_DIR = WORKSPACE / "logs"


# ==============================================================================
# Android SDK Araçlarını Bulma
# ==============================================================================

def _olasi_sdk_dizinleri() -> list[Path]:
    yollar = []
    for env_var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        val = os.getenv(env_var)
        if val:
            yollar.append(Path(val))
    # macOS varsayılanları
    ev = Path.home()
    yollar.append(ev / "Library" / "Android" / "sdk")
    # Linux varsayılanları
    yollar.append(ev / "Android" / "Sdk")
    return [p for p in yollar if p.is_dir()]


def bul_adb() -> str | None:
    """Sistemde veya Android SDK dizininde adb yolunu bulur."""
    adb_which = shutil.which("adb")
    if adb_which:
        return adb_which
    for sdk in _olasi_sdk_dizinleri():
        p = sdk / "platform-tools" / "adb"
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return None


def bul_emulator() -> str | None:
    """Sistemde veya Android SDK dizininde emulator yolunu bulur."""
    emu_which = shutil.which("emulator")
    if emu_which:
        return emu_which
    for sdk in _olasi_sdk_dizinleri():
        p = sdk / "emulator" / "emulator"
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return None


def bul_flutter() -> str | None:
    """Sistemde veya bilinen dizinlerde flutter CLI yolunu bulur."""
    fl_which = shutil.which("flutter")
    if fl_which:
        return fl_which
    ev = Path.home()
    olasi = [
        ev / "development" / "flutter" / "bin" / "flutter",
        ev / "flutter" / "bin" / "flutter",
        Path("/opt/homebrew/bin/flutter"),
        ev / ".local" / "bin" / "flutter",
    ]
    for p in olasi:
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return None


# ==============================================================================
# AVD ve Cihaz Durumları
# ==============================================================================

def avd_listesi() -> list[str]:
    """Sistemde tanımlı Android Virtual Device (AVD) listesini döndürür."""
    emu = bul_emulator()
    if not emu:
        return []
    try:
        c = subprocess.run([emu, "-list-avds"], capture_output=True, text=True, timeout=10)
        if c.returncode == 0:
            return [satir.strip() for satir in c.stdout.splitlines() if satir.strip()]
    except Exception as e:
        print(f"[!] avd_listesi hatası: {e}", file=sys.stderr)
    return []


def calisan_cihazlar() -> list[dict]:
    """ADB ile bağlı aktif cihaz ve emülatörleri listeler."""
    adb = bul_adb()
    if not adb:
        return []
    try:
        c = subprocess.run([adb, "devices", "-l"], capture_output=True, text=True, timeout=10)
        if c.returncode != 0:
            return []
        satirlar = c.stdout.splitlines()
        cihazlar = []
        for s in satirlar[1:]:
            s = s.strip()
            if not s:
                continue
            parcalar = s.split()
            if len(parcalar) >= 2:
                cid = parcalar[0]
                durum = parcalar[1]
                ozellikler = {}
                for p in parcalar[2:]:
                    if ":" in p:
                        k, v = p.split(":", 1)
                        ozellikler[k] = v
                model = ozellikler.get("model", ozellikler.get("device", cid))
                cihazlar.append({
                    "id": cid,
                    "durum": durum,
                    "model": model,
                    "ozellikler": ozellikler,
                    "emulatore_mi": cid.startswith("emulator-")
                })
        return cihazlar
    except Exception as e:
        print(f"[!] calisan_cihazlar hatası: {e}", file=sys.stderr)
    return []


# ==============================================================================
# Emülatör Başlatma / Durdurma
# ==============================================================================

def emulatore_baslat(avd_adi: str = "Galaxy_S24", basliksiz: bool = False) -> tuple[bool, str]:
    """Android emülatörünü arka planda başlatır.

    basliksiz=False ise macOS üzerinde pencere görünür ve kullanıcı masaüstünde
    canlı mobil arayüzü birebir görüp tıklayabilir.
    """
    emu = bul_emulator()
    if not emu:
        return False, "Android emülatör aracı ('emulator') bulunamadı."

    mevcut_avdler = avd_listesi()
    if not mevcut_avdler:
        return False, "Sistemde kurulu Android Sanal Cihazı (AVD) bulunamadı."

    if avd_adi not in mevcut_avdler:
        avd_adi = mevcut_avdler[0]

    # Zaten çalışıyor mu kontrol et
    cihazlar = calisan_cihazlar()
    for c in cihazlar:
        if c["emulatore_mi"] and c["durum"] == "device":
            return True, f"Emülatör zaten çalışıyor: {c['id']} ({c['model']})"

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_dosyasi = LOGS_DIR / "emulator.log"
    komut = [emu, "-avd", avd_adi]
    if basliksiz:
        komut.append("-no-window")
    # Hızlı açılış parametreleri
    komut.extend(["-no-boot-anim", "-no-audio"])

    try:
        with open(log_dosyasi, "a", encoding="utf-8") as out:
            out.write(f"\n--- Emülatör Başlatılıyor: {avd_adi} ({datetime.now().isoformat()}) ---\n")
            proc = subprocess.Popen(
                komut,
                stdout=out,
                stderr=out,
                start_new_session=True,
                stdin=subprocess.DEVNULL
            )
        return True, f"'{avd_adi}' emülatörü başlatıldı (PID: {proc.pid})."
    except Exception as e:
        return False, f"Emülatör başlatma hatası: {e}"


def emulatore_durdur(cihaz_id: str = None) -> tuple[bool, str]:
    """Çalışan emülatörü kapatır."""
    adb = bul_adb()
    if not adb:
        return False, "ADB aracı bulunamadı."

    cihazlar = calisan_cihazlar()
    if not cihazlar:
        return False, "Kapatılacak çalışan cihaz/emülatör bulunamadı."

    hedef_id = cihaz_id
    if not hedef_id:
        for c in cihazlar:
            if c["emulatore_mi"]:
                hedef_id = c["id"]
                break
    if not hedef_id and cihazlar:
        hedef_id = cihazlar[0]["id"]

    try:
        c = subprocess.run([adb, "-s", hedef_id, "emu", "kill"], capture_output=True, text=True, timeout=10)
        if c.returncode == 0 or "OK" in c.stdout or "OK" in c.stderr:
            return True, f"{hedef_id} emülatörü kapatıldı."
        return True, f"{hedef_id} kapatma komutu iletildi: {c.stdout.strip() or c.stderr.strip()}"
    except Exception as e:
        return False, f"Emülatör kapatma hatası: {e}"


# ==============================================================================
# Ekran Görüntüsü Alma & UAT Kanıtı Kaydetme
# ==============================================================================

def _proje_koku() -> Path:
    cwd = Path.cwd()
    if (cwd / "workspace").is_dir() or (cwd / ".git").is_dir() or (cwd / "basla.sh").is_file():
        return cwd
    return Path(__file__).resolve().parent.parent


def mobil_proje_dizini() -> Path | None:
    """Projedeki mobil uygulama kök dizinini (pubspec.yaml içeren) bulur."""
    kokler = [_proje_koku(), Path.cwd(), ROOT]
    for k in kokler:
        for base in (k / "workspace", k):
            for sub in ("src/mobile", "mobile", "src/frontend"):
                p = base / sub
                if (p / "pubspec.yaml").is_file():
                    return p
    return None


def mobil_kaynak_son_degisiklik_zamani() -> float:
    """Mobil kaynak kodların (lib, pubspec, android) en son değiştirilme zamanını döndürür."""
    mdir = mobil_proje_dizini()
    if not mdir:
        return 0.0
    son_zaman = 0.0
    for p in mdir.rglob("*"):
        if p.is_file() and not any(ign in str(p) for ign in [".git", ".dart_tool", "build", ".gradle", ".idea", ".history"]):
            try:
                t = p.stat().st_mtime
                if t > son_zaman:
                    son_zaman = t
            except OSError:
                pass
    return son_zaman


def pubspec_versiyon_bilgisi() -> tuple[str, int]:
    """pubspec.yaml dosyasından versionName ve versionCode'u okur."""
    mdir = mobil_proje_dizini()
    if not mdir:
        return "1.0.0", 1
    pubspec = mdir / "pubspec.yaml"
    if pubspec.is_file():
        try:
            m = re.search(r"^version:\s*([0-9\.]+)\+?(\d+)?", pubspec.read_text(encoding="utf-8"), re.MULTILINE)
            if m:
                vn = m.group(1)
                vc = int(m.group(2)) if m.group(2) else 1
                return vn, vc
        except Exception:
            pass
    return "1.0.0", 1


def cihazdaki_paket_bilgisi(cihaz_id: str = None) -> dict:
    """Emülatör/cihazda kurulu uygulamanın sürüm ve güncelleme tarihlerini döndürür."""
    adb = bul_adb()
    if not adb:
        return {}
    paket = mobil_uygulama_paket_bul()
    if not paket:
        return {}
    cihazlar = [c for c in calisan_cihazlar() if c["durum"] == "device"]
    if not cihazlar:
        return {}
    hedef_id = cihaz_id or cihazlar[0]["id"]
    try:
        out = subprocess.run([adb, "-s", hedef_id, "shell", "dumpsys", "package", paket],
                             capture_output=True, text=True, timeout=10).stdout
        if "Unable to find package" in out or not out.strip():
            return {"kurulu": False, "paket": paket, "cihaz_id": hedef_id}
        info = {"kurulu": True, "paket": paket, "cihaz_id": hedef_id}
        m_vc = re.search(r"versionCode=(\d+)", out)
        if m_vc:
            info["versionCode"] = int(m_vc.group(1))
        m_vn = re.search(r"versionName=([^\s]+)", out)
        if m_vn:
            info["versionName"] = m_vn.group(1)
        m_lut = re.search(r"lastUpdateTime=([^\r\n]+)", out)
        if m_lut:
            info["lastUpdateTime"] = m_lut.group(1).strip()
            try:
                dt = datetime.strptime(info["lastUpdateTime"][:19], "%Y-%m-%d %H:%M:%S")
                info["lastUpdateTs"] = dt.timestamp()
            except Exception:
                info["lastUpdateTs"] = 0.0
        return info
    except Exception as e:
        print(f"[!] cihazdaki_paket_bilgisi hatası: {e}", file=sys.stderr)
        return {}


def apk_guncel_mi(cihaz_id: str = None) -> tuple[bool, str]:
    """Cihazdaki uygulamanın güncel kaynak kodları yansıtıp yansıtmadığını doğrular."""
    info = cihazdaki_paket_bilgisi(cihaz_id)
    if not info:
        return False, "Cihaz veya paket bilgisi alınamadı."
    if not info.get("kurulu"):
        return False, f"'{info.get('paket', '')}' uygulaması cihazda kurulu değil."

    pub_vn, pub_vc = pubspec_versiyon_bilgisi()
    dev_vc = info.get("versionCode", 0)
    dev_vn = info.get("versionName", "")

    if dev_vc < pub_vc:
        return False, f"Cihazdaki sürüm kodu (v{dev_vn}+{dev_vc}), pubspec sürüm kodundan (v{pub_vn}+{pub_vc}) eski."

    # Git commit kontrolü: son yüklenen APK'nın commit'i ile aktif HEAD'i karşılaştır
    root = _proje_koku()
    commit_f = root / "workspace" / ".last_apk_commit"
    if commit_f.is_file():
        try:
            last_commit = commit_f.read_text(encoding="utf-8").strip()
            c_git = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=root)
            if c_git.returncode == 0:
                current_commit = c_git.stdout.strip()
                if last_commit and current_commit and last_commit != current_commit:
                    return False, f"Git commit değişti (cihazdaki: {last_commit[:7]}, güncel: {current_commit[:7]})."
        except Exception:
            pass

    kaynak_ts = mobil_kaynak_son_degisiklik_zamani()
    dev_ts = info.get("lastUpdateTs", 0.0)
    # Kaynak kod cihazdaki güncelleme tarihinden 5 saniyeden daha yeniyse bayattır
    if kaynak_ts > (dev_ts + 5.0):
        t_str = datetime.fromtimestamp(kaynak_ts).strftime("%Y-%m-%d %H:%M:%S")
        lut_str = info.get("lastUpdateTime", "bilinmiyor")
        return False, f"Mobil kodlar ({t_str}) emülatördeki yükleme tarihinden ({lut_str}) daha yeni."

    return True, f"Cihazdaki uygulama güncel (v{dev_vn}+{dev_vc})."


def mobil_uygulama_derle_ve_yukle(cihaz_id: str = None, zorla: bool = False) -> tuple[bool, str]:
    """Mobil uygulamayı derleyip (flutter build apk --debug) bağlı cihaza yükler."""
    if not zorla:
        guncel, msg = apk_guncel_mi(cihaz_id)
        if guncel:
            return True, f"Derleme gerekmiyor: {msg}"

    mdir = mobil_proje_dizini()
    if not mdir:
        return False, "workspace/src/mobile dizini bulunamadı."

    flutter_bin = bul_flutter()
    if not flutter_bin:
        return False, "Flutter SDK ('flutter') bulunamadı."

    adb = bul_adb()
    if not adb:
        return False, "ADB aracı bulunamadı."

    cihazlar = [c for c in calisan_cihazlar() if c["durum"] == "device"]
    if not cihazlar:
        return False, "Uygulamanın yüklenebileceği aktif cihaz/emülatör bulunamadı."
    hedef_id = cihaz_id or cihazlar[0]["id"]

    print(f"   🔨 [MOBİL DERLEME] Flutter debug APK derleniyor ({mdir})...", flush=True)
    try:
        build_proc = subprocess.run([flutter_bin, "build", "apk", "--debug"],
                                    cwd=mdir, capture_output=True, text=True, timeout=240)
        if build_proc.returncode != 0:
            err = (build_proc.stderr or build_proc.stdout).strip().splitlines()[-5:]
            return False, f"Flutter derleme hatası: {' '.join(err)}"
    except subprocess.TimeoutExpired:
        return False, "Flutter derleme işlemi zaman aşımına uğradı (240s)."
    except Exception as e:
        return False, f"Flutter derleme çalıştırılamadı: {e}"

    # Üretilen APK'yı bul
    apk_yollari = [
        mdir / "build" / "app" / "outputs" / "flutter-apk" / "app-debug.apk",
        mdir / "build" / "app" / "outputs" / "apk" / "debug" / "app-debug.apk",
        mdir / "build" / "app" / "outputs" / "flutter-apk" / "app-release.apk",
    ]
    apk_path = None
    for p in apk_yollari:
        if p.is_file():
            apk_path = p
            break

    if not apk_path:
        return False, "Derleme sonrası APK dosyası bulunamadı."

    print(f"   📲 [MOBİL YÜKLEME] APK emülatöre yükleniyor: {apk_path.name} -> {hedef_id}...", flush=True)
    # Önleyici temizlik: /data/local/tmp altındaki geçici dosyaları temizle
    try:
        subprocess.run([adb, "-s", hedef_id, "shell", "rm -rf /data/local/tmp/*"],
                       capture_output=True, timeout=10)
    except Exception:
        pass

    try:
        install_proc = subprocess.run([adb, "-s", hedef_id, "install", "-r", str(apk_path)],
                                      capture_output=True, text=True, timeout=90)
        output_txt = (install_proc.stdout or "") + " " + (install_proc.stderr or "")

        # Yetersiz depolama alanı hatası durumunda otomatik kurtarma
        if "INSTALL_FAILED_INSUFFICIENT_STORAGE" in output_txt:
            print("   ⚠️  [MOBİL DEPOLAMA UYARISI] Emülatör depolama alanı yetersiz; eski paket kaldırılarak alan açılıyor...", flush=True)
            pkg = mobil_uygulama_paket_bul()
            if pkg:
                subprocess.run([adb, "-s", hedef_id, "uninstall", pkg], capture_output=True, timeout=30)
            subprocess.run([adb, "-s", hedef_id, "shell", "rm -rf /data/local/tmp/*"], capture_output=True, timeout=10)
            # İkinci deneme
            install_proc = subprocess.run([adb, "-s", hedef_id, "install", "-r", str(apk_path)],
                                          capture_output=True, text=True, timeout=90)
            output_txt = (install_proc.stdout or "") + " " + (install_proc.stderr or "")

        if install_proc.returncode == 0 or "Success" in output_txt:
            info = cihazdaki_paket_bilgisi(hedef_id)
            root = _proje_koku()
            try:
                c_git = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=root)
                if c_git.returncode == 0 and c_git.stdout.strip():
                    commit_f = root / "workspace" / ".last_apk_commit"
                    commit_f.parent.mkdir(parents=True, exist_ok=True)
                    commit_f.write_text(c_git.stdout.strip(), encoding="utf-8")
            except Exception:
                pass
            return True, f"APK başarıyla yüklendi: v{info.get('versionName', '?')}+{info.get('versionCode', '?')}"
        else:
            return False, f"ADB yükleme hatası: {output_txt.strip()}"
    except Exception as e:
        return False, f"ADB yükleme çalıştırılamadı: {e}"


def mobil_uygulama_paket_bul() -> str:
    """Projedeki mobil uygulamanın paket adını bulur."""
    mdir = mobil_proje_dizini()
    if mdir:
        gradle_dosya = mdir / "android" / "app" / "build.gradle"
        if not gradle_dosya.is_file():
            gradle_dosya = mdir / "android" / "app" / "build.gradle.kts"
        if gradle_dosya.is_file():
            try:
                txt = gradle_dosya.read_text(encoding="utf-8")
                m = re.search(r'applicationId\s*=?\s*["\']([^"\']+)["\']', txt)
                if m:
                    return m.group(1)
                m_ns = re.search(r'namespace\s*=?\s*["\']([^"\']+)["\']', txt)
                if m_ns:
                    return m_ns.group(1)
            except Exception:
                pass
        manifest_dosya = mdir / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
        if manifest_dosya.is_file():
            try:
                m = re.search(r'package\s*=\s*["\']([^"\']+)["\']', manifest_dosya.read_text(encoding="utf-8"))
                if m:
                    return m.group(1)
            except Exception:
                pass
    return "com.example.app"


def mobil_uygulama_baslat(cihaz_id: str = None) -> bool:
    """Emülatörde projeye ait mobil uygulamayı ön plana getirir/başlatır."""
    adb = bul_adb()
    if not adb:
        return False
    paket = mobil_uygulama_paket_bul()
    if not paket:
        return False
    cihazlar = [c for c in calisan_cihazlar() if c["durum"] == "device"]
    if not cihazlar:
        return False
    hedef_id = cihaz_id or cihazlar[0]["id"]
    try:
        res = subprocess.run([adb, "-s", hedef_id, "shell", "cmd", "package", "resolve-activity", "--brief", paket],
                             capture_output=True, text=True, timeout=5)
        act = f"{paket}/.MainActivity"
        for line in res.stdout.splitlines():
            line = line.strip()
            if "/" in line and paket in line:
                act = line
                break
        subprocess.run([adb, "-s", hedef_id, "shell", "am", "start", "-n", act],
                       capture_output=True, text=True, timeout=10)
        time.sleep(2)
        return True
    except Exception as e:
        print(f"[!] mobil_uygulama_baslat hatası: {e}", file=sys.stderr)
        return False


def ekran_goruntusu_al(cihaz_id: str = None, talep_id: str = None, gorev_id: str = None,
                       otomatik_baslat: bool = True, otomatik_guncelle: bool = True) -> tuple[bool, str, str]:
    """Çalışan cihazdan ekran görüntüsü alır ve workspace/docs/uat_kanitlari/ altına yazar.

    otomatik_baslat=True ise ve çalışan emülatör yoksa önce emülatörü başlatıp bekler.
    otomatik_guncelle=True ise cihazdaki APK bayatsa veya kaynak kod daha yeniyse derleyip yükler.
    Ekran görüntüsü öncesinde projeye ait mobil uygulama ön plana getirilir.
    Döndürür: (basarili, goreceli_dosya_yolu, mesaj)
    """
    adb = bul_adb()
    if not adb:
        return False, "", "ADB aracı bulunamadı."

    cihazlar = calisan_cihazlar()
    if not cihazlar:
        if otomatik_baslat:
            ok_baslat, msg_baslat = emulatore_baslat()
            if not ok_baslat:
                return False, "", f"Emülatör otomatik başlatılamadı: {msg_baslat}"
            # Cihazın hazır olması için bekle (azami 30sn)
            for _ in range(30):
                time.sleep(1)
                cihazlar = [c for c in calisan_cihazlar() if c["durum"] == "device"]
                if cihazlar:
                    break
        if not cihazlar:
            return False, "", "Ekran görüntüsü alınacak çalışan cihaz veya emülatör bulunamadı."

    hedef_id = cihaz_id
    if not hedef_id:
        for c in cihazlar:
            if c["emulatore_mi"] and c["durum"] == "device":
                hedef_id = c["id"]
                break
    if not hedef_id:
        hedef_id = cihazlar[0]["id"]

    # Otomatik APK güncelleme: kod değiştiyse veya cihazdaki APK bayatsa derle ve yükle
    if otomatik_guncelle:
        guncel, neden = apk_guncel_mi(hedef_id)
        if not guncel:
            print(f"   📱 [MOBİL APK GÜNCELLEME] Emülatördeki uygulama eski ({neden}); yeniden derlenip yükleniyor...", flush=True)
            ok_up, msg_up = mobil_uygulama_derle_ve_yukle(cihaz_id=hedef_id)
            if ok_up:
                print(f"   ✓ [MOBİL APK YÜKLENDİ] {msg_up}", flush=True)
            else:
                print(f"   ⚠️  [MOBİL APK UYARI] {msg_up} (Mevcut APK ile devam ediliyor)", flush=True)

    # Ekran görüntüsü öncesi uygulamanın kendisini ön plana getir
    mobil_uygulama_baslat(hedef_id)

    UAT_KANIT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    etiket = ""
    if talep_id:
        etiket += f"_{talep_id}"
    if gorev_id:
        etiket += f"_{gorev_id}"

    dosya_adi = f"mobil{etiket}_{ts}.png"
    tam_yol = UAT_KANIT_DIR / dosya_adi
    rel_yol = f"workspace/docs/uat_kanitlari/{dosya_adi}"

    try:
        with open(tam_yol, "wb") as f:
            proc = subprocess.run([adb, "-s", hedef_id, "exec-out", "screencap", "-p"],
                                  stdout=f, stderr=subprocess.PIPE, timeout=15)
        if proc.returncode != 0:
            tam_yol.unlink(missing_ok=True)
            return False, "", f"Ekran görüntüsü alınamadı: {proc.stderr.decode('utf-8', errors='ignore')}"

        if not tam_yol.is_file() or tam_yol.stat().st_size == 0:
            tam_yol.unlink(missing_ok=True)
            return False, "", "Ekran görüntüsü boş üretildi (cihaz hazır olmayabilir)."

        info = cihazdaki_paket_bilgisi(hedef_id)
        sürüm_str = f"v{info.get('versionName', '?')}+{info.get('versionCode', '?')}"
        lut_str = info.get("lastUpdateTime", "")
        return True, rel_yol, f"Ekran görüntüsü kaydedildi: {dosya_adi} [{sürüm_str} - {lut_str}]"
    except Exception as e:
        tam_yol.unlink(missing_ok=True)
        return False, "", f"Ekran yakalama hatası: {e}"


def uat_kanit_gorselleri(limit: int = 30) -> list[dict]:
    """workspace/docs/uat_kanitlari/ altındaki ekran görüntülerini tarihe göre sıralı döndürür."""
    if not UAT_KANIT_DIR.is_dir():
        return []
    dosyalar = []
    for f in UAT_KANIT_DIR.glob("*.png"):
        try:
            stat = f.stat()
            dosyalar.append({
                "ad": f.name,
                "yol": f"workspace/docs/uat_kanitlari/{f.name}",
                "boyut_bayt": stat.st_size,
                "zaman": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            })
        except OSError:
            continue
    dosyalar.sort(key=lambda x: x["zaman"], reverse=True)
    return dosyalar[:limit]


def genel_mobil_durum() -> dict:
    """Tüm mobil durumunu (SDK, AVD'ler, bağlı cihazlar ve son kanıtlar) özetler."""
    adb = bul_adb()
    emu = bul_emulator()
    avdler = avd_listesi()
    cihazlar = calisan_cihazlar()
    kanitlar = uat_kanit_gorselleri(limit=10)

    return {
        "ok": True,
        "adb_var": bool(adb),
        "adb_yolu": adb,
        "emulator_var": bool(emu),
        "emulator_yolu": emu,
        "avd_listesi": avdler,
        "cihazlar": cihazlar,
        "aktif_cihaz_sayisi": len(cihazlar),
        "son_kanitlar": kanitlar
    }


# ==============================================================================
# CLI
# ==============================================================================

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Mobil Önizleme ve UAT Yönetici")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("durum", help="Mobil durum özetini JSON olarak yazdırır")
    sub.add_parser("avd-liste", help="Mevcut AVD sanal cihazlarını listeler")
    sub.add_parser("cihazlar", help="Bağlı cihaz ve emülatörleri listeler")

    p_bas = sub.add_parser("baslat", help="Emülatörü başlatır")
    p_bas.add_argument("avd", nargs="?", default="Galaxy_S24", help="AVD adı")
    p_bas.add_argument("--basliksiz", action="store_true", help="Penceresiz (headless) başlat")

    p_dur = sub.add_parser("durdur", help="Emülatörü kapatır")
    p_dur.add_argument("cihaz_id", nargs="?", help="Cihaz/emülatör ID (örn. emulator-5554)")

    p_ss = sub.add_parser("screencap", help="Ekran görüntüsü alır")
    p_ss.add_argument("--cihaz", help="Cihaz ID")
    p_ss.add_argument("--talep", help="İlişkili talep ID")
    p_ss.add_argument("--gorev", help="İlişkili görev ID")
    p_ss.add_argument("--no-build", action="store_true", help="Otomatik APK güncellemesini atla")

    p_dy = sub.add_parser("derle-yukle", help="Mobil uygulamayı derleyip emülatöre yükler")
    p_dy.add_argument("--cihaz", help="Cihaz ID")
    p_dy.add_argument("--force", action="store_true", help="Güncel olsa bile zorla derle")

    p_gm = sub.add_parser("guncel-mi", help="Cihazdaki uygulamanın güncelliğini kontrol eder")
    p_gm.add_argument("--cihaz", help="Cihaz ID")

    p_pb = sub.add_parser("paket-bilgi", help="Cihazdaki uygulamanın paket ve sürüm detayını gösterir")
    p_pb.add_argument("--cihaz", help="Cihaz ID")

    args = ap.parse_args()

    if args.cmd == "durum" or not args.cmd:
        print(json.dumps(genel_mobil_durum(), indent=2, ensure_ascii=False))
    elif args.cmd == "avd-liste":
        for a in avd_listesi():
            print(" -", a)
    elif args.cmd == "cihazlar":
        for c in calisan_cihazlar():
            print(f" - {c['id']} ({c['durum']}) model={c['model']}")
    elif args.cmd == "baslat":
        ok, msg = emulatore_baslat(args.avd, basliksiz=args.basliksiz)
        print(("✓ " if ok else "✗ ") + msg)
    elif args.cmd == "durdur":
        ok, msg = emulatore_durdur(args.cihaz_id)
        print(("✓ " if ok else "✗ ") + msg)
    elif args.cmd == "guncel-mi":
        ok, msg = apk_guncel_mi(args.cihaz)
        print(("✓ " if ok else "✗ ") + msg)
    elif args.cmd == "paket-bilgi":
        print(json.dumps(cihazdaki_paket_bilgisi(args.cihaz), indent=2, ensure_ascii=False))
    elif args.cmd == "derle-yukle":
        ok, msg = mobil_uygulama_derle_ve_yukle(args.cihaz, zorla=args.force)
        print(("✓ " if ok else "✗ ") + msg)
    elif args.cmd == "screencap":
        ok, yol, msg = ekran_goruntusu_al(cihaz_id=args.cihaz, talep_id=args.talep, gorev_id=args.gorev, otomatik_guncelle=not args.no_build)
        if ok:
            print(f"✓ {msg} -> {yol}")
        else:
            print(f"✗ {msg}")
