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

def mobil_uygulama_paket_bul() -> str:
    """Projedeki mobil uygulamanın paket adını bulur."""
    gradle_dosya = WORKSPACE / "src" / "mobile" / "android" / "app" / "build.gradle"
    if gradle_dosya.is_file():
        try:
            m = re.search(r'applicationId\s*=?\s*["\']([^"\']+)["\']', gradle_dosya.read_text(encoding="utf-8"))
            if m:
                return m.group(1)
        except Exception:
            pass
    manifest_dosya = ROOT / "workspace/src/mobile/android/app/src/main/AndroidManifest.xml"
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


def ekran_goruntusu_al(cihaz_id: str = None, talep_id: str = None, gorev_id: str = None, otomatik_baslat: bool = True) -> tuple[bool, str, str]:
    """Çalışan cihazdan ekran görüntüsü alır ve workspace/docs/uat_kanitlari/ altına yazar.

    otomatik_baslat=True ise ve çalışan emülatör yoksa önce emülatörü başlatıp bekler.
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

        return True, rel_yol, f"Ekran görüntüsü kaydedildi: {dosya_adi}"
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
    elif args.cmd == "screencap":
        ok, yol, msg = ekran_goruntusu_al(cihaz_id=args.cihaz, talep_id=args.talep, gorev_id=args.gorev)
        if ok:
            print(f"✓ {msg} -> {yol}")
        else:
            print(f"✗ {msg}")
