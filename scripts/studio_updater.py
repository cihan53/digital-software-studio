#!/usr/bin/env python3
"""
scripts/studio_updater.py
Digital Software Studio — Framework Versiyon Takip & Güncelleme Scripti
=========================================================================

Kullanan projeler (örn. elektriklioto-gemini) bu scripti çalıştırarak
digital-software-studio framework'ünün güncel versiyonunu kontrol edebilir
ve yeni değişiklikleri kontrollü olarak uygulayabilir.

Kullanım:
  python3 scripts/studio_updater.py --durum       # Mevcut versiyon bilgisi
  python3 scripts/studio_updater.py --kontrol     # DS ile fark raporu (yazmaz)
  python3 scripts/studio_updater.py --uygula      # Güncellemeleri uygula
  python3 scripts/studio_updater.py --uygula --commit  # + otomatik git commit

Güncelleme Kuralları:
  - STUDIO:CUSTOM:BEGIN / STUDIO:CUSTOM:END blokları KORUNUR
  - Diğer içerik DS versiyonuyla güncellenir
  - .studio-version her güncellemeden sonra yazılır
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DS_LOCAL_PATHS = [
    Path("/Users/cihan/PROJECT/digital-software-studio"),
    ROOT.parent / "digital-software-studio",
]
DS_GITHUB_RAW = "https://raw.githubusercontent.com/cihan53/digital-software-studio/main"
LOCAL_VERSION_FILE = ROOT / ".studio-version"
DS_VERSION_FILE = "studio.version"

GREEN  = "\033[32m"; YELLOW = "\033[33m"; CYAN   = "\033[36m"
RED    = "\033[31m"; BOLD   = "\033[1m";  NC     = "\033[0m"


def ds_path_bul():
    for p in DS_LOCAL_PATHS:
        if (p / "studio.version").exists():
            return p
    return None


def ds_version_yukle(ds_path):
    if ds_path:
        vf = ds_path / DS_VERSION_FILE
        if vf.exists():
            try:
                return json.loads(vf.read_text(encoding="utf-8"))
            except Exception:
                pass
    try:
        import urllib.request
        url = f"{DS_GITHUB_RAW}/{DS_VERSION_FILE}"
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def local_version_yukle():
    if LOCAL_VERSION_FILE.exists():
        try:
            return json.loads(LOCAL_VERSION_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"version": "0.0.0", "updated": None}


def local_version_kaydet(versiyon, ds_path):
    data = {
        "version": versiyon,
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "ds_path": str(ds_path),
        "proje": ROOT.name
    }
    LOCAL_VERSION_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def custom_bloklari_cikart(icerik):
    bloklar = {}
    satirlar = icerik.split("\n")
    blok_idx = 0
    i = 0
    while i < len(satirlar):
        if "STUDIO:CUSTOM:BEGIN" in satirlar[i]:
            blok_satirlar = [satirlar[i]]
            i += 1
            while i < len(satirlar) and "STUDIO:CUSTOM:END" not in satirlar[i]:
                blok_satirlar.append(satirlar[i])
                i += 1
            if i < len(satirlar):
                blok_satirlar.append(satirlar[i])
            bloklar[blok_idx] = "\n".join(blok_satirlar)
            blok_idx += 1
        i += 1
    return bloklar


def custom_bloklari_uygula(yeni_icerik, eski_bloklar):
    if not eski_bloklar:
        return yeni_icerik
    satirlar = yeni_icerik.split("\n")
    sonuc = []
    blok_idx = 0
    i = 0
    while i < len(satirlar):
        if "STUDIO:CUSTOM:BEGIN" in satirlar[i] and blok_idx in eski_bloklar:
            sonuc.append(eski_bloklar[blok_idx])
            blok_idx += 1
            i += 1
            while i < len(satirlar) and "STUDIO:CUSTOM:END" not in satirlar[i]:
                i += 1
            i += 1
        else:
            sonuc.append(satirlar[i])
            i += 1
    return "\n".join(sonuc)


def normalize_custom(icerik):
    """CUSTOM blokları çıkararak normalize eder — fark karşılaştırması için."""
    satirlar = icerik.split("\n")
    filtreli = []
    atlaniyor = False
    for satir in satirlar:
        if "STUDIO:CUSTOM:BEGIN" in satir:
            atlaniyor = True
        if not atlaniyor:
            filtreli.append(satir)
        if "STUDIO:CUSTOM:END" in satir:
            atlaniyor = False
    return "\n".join(filtreli)


def dosya_fark_var_mi(proje_dosya, ds_dosya):
    if not proje_dosya.exists() or not ds_dosya.exists():
        return proje_dosya.exists() != ds_dosya.exists()
    p = normalize_custom(proje_dosya.read_text(encoding="utf-8", errors="replace"))
    d = normalize_custom(ds_dosya.read_text(encoding="utf-8", errors="replace"))
    return p != d


def dosya_guncelle(proje_dosya, ds_dosya):
    if not ds_dosya.exists():
        return False
    ds_icerik = ds_dosya.read_text(encoding="utf-8", errors="replace")
    eski_bloklar = {}
    if proje_dosya.exists():
        eski_bloklar = custom_bloklari_cikart(proje_dosya.read_text(encoding="utf-8", errors="replace"))
    yeni_icerik = custom_bloklari_uygula(ds_icerik, eski_bloklar)
    proje_dosya.parent.mkdir(parents=True, exist_ok=True)
    proje_dosya.write_text(yeni_icerik, encoding="utf-8")
    return True


def cmd_durum():
    local = local_version_yukle()
    ds_path = ds_path_bul()
    ds_ver = ds_version_yukle(ds_path)

    print(f"\n{BOLD}{CYAN}╔══════════════════════════════════════════════════╗")
    print(f"║  📦  Digital Software Studio — Versiyon Durumu  ║")
    print(f"╚══════════════════════════════════════════════════╝{NC}\n")
    print(f"  {BOLD}Bu Proje:{NC} {ROOT.name}")
    print(f"  {BOLD}Framework Versiyonu:{NC} {local.get('version', '?')}")
    print(f"  {BOLD}Son Güncelleme:{NC} {local.get('updated', 'Hiç güncellenmedi')}")
    print(f"  {BOLD}DS Kaynak:{NC} {str(ds_path) if ds_path else 'GitHub (local bulunamadı)'}")

    if ds_ver:
        print(f"\n  {BOLD}DS Son Sürümü:{NC} {ds_ver.get('version', '?')}  ({ds_ver.get('released', '?')})")
        if local.get("version") == ds_ver.get("version"):
            print(f"  {GREEN}✅  Güncel!{NC}")
        else:
            print(f"  {YELLOW}⚠️   Güncelleme mevcut: {local.get('version')} → {ds_ver.get('version')}{NC}")
            print(f"  {CYAN}ℹ️   Çalıştır: python3 scripts/studio_updater.py --kontrol{NC}")
    print()


def cmd_kontrol():
    ds_path = ds_path_bul()
    ds_ver = ds_version_yukle(ds_path)
    local = local_version_yukle()

    if not ds_ver:
        print(f"{RED}✗  DS studio.version alınamadı.{NC}")
        sys.exit(1)

    tracked = ds_ver.get("tracked_files", [])

    print(f"\n{BOLD}{CYAN}╔══════════════════════════════════════════════════╗")
    print(f"║  🔍  Framework Güncelleme Kontrol Raporu        ║")
    print(f"╚══════════════════════════════════════════════════╝{NC}\n")
    print(f"  Proje : {BOLD}{local.get('version', '0.0.0')}{NC}  →  DS : {BOLD}{ds_ver.get('version')}{NC}  ({ds_ver.get('released')})")
    print()

    farklar = []
    yeniler = []

    for rel_path in tracked:
        proje_dosya = ROOT / rel_path
        ds_dosya = (ds_path / rel_path) if ds_path else None
        if ds_dosya and not ds_dosya.exists():
            continue
        if not proje_dosya.exists():
            yeniler.append(rel_path)
        elif ds_dosya and dosya_fark_var_mi(proje_dosya, ds_dosya):
            farklar.append(rel_path)
        else:
            print(f"  {GREEN}✓{NC}  {rel_path}")

    if yeniler:
        print(f"\n  {CYAN}── Yeni Dosyalar ─────────────────────────────────{NC}")
        for f in yeniler:
            print(f"  {CYAN}+{NC}  {f}")

    if farklar:
        print(f"\n  {YELLOW}── Güncellenecek Dosyalar ────────────────────────{NC}")
        for f in farklar:
            print(f"  {YELLOW}~{NC}  {f}")
        print(f"\n  {BOLD}{len(farklar)} dosya güncellenebilir.{NC}")
        print(f"  {CYAN}Uygula: python3 scripts/studio_updater.py --uygula{NC}")
    elif not yeniler:
        print(f"\n  {GREEN}✅  Tüm dosyalar güncel!{NC}")

    if local.get("version") != ds_ver.get("version"):
        print(f"\n  {BOLD}── Değişiklikler ({ds_ver.get('version')}) ──────────────────{NC}")
        for entry in ds_ver.get("changelog", []):
            if entry.get("version") == ds_ver.get("version"):
                for c in entry.get("changes", []):
                    print(f"    • {c}")
    print()


def cmd_uygula(otomatik_commit=False):
    ds_path = ds_path_bul()
    ds_ver = ds_version_yukle(ds_path)

    if not ds_ver or not ds_path:
        print(f"{RED}✗  DS local path bulunamadı.{NC}")
        sys.exit(1)

    tracked = ds_ver.get("tracked_files", [])

    print(f"\n{BOLD}{CYAN}╔══════════════════════════════════════════════════╗")
    print(f"║  🚀  Framework Güncelleme Uygulanıyor           ║")
    print(f"╚══════════════════════════════════════════════════╝{NC}\n")

    guncellenenler = []
    eklenenler = []

    for rel_path in tracked:
        if rel_path == "studio.version":
            continue
        proje_dosya = ROOT / rel_path
        ds_dosya = ds_path / rel_path
        if not ds_dosya.exists():
            continue
        was_new = not proje_dosya.exists()
        if was_new or dosya_fark_var_mi(proje_dosya, ds_dosya):
            if dosya_guncelle(proje_dosya, ds_dosya):
                if was_new:
                    eklenenler.append(rel_path)
                    print(f"  {CYAN}+{NC}  {rel_path}  {CYAN}(yeni){NC}")
                else:
                    guncellenenler.append(rel_path)
                    print(f"  {GREEN}↑{NC}  {rel_path}  {GREEN}(güncellendi){NC}")
        else:
            print(f"  ·  {rel_path}  (değişiklik yok)")

    local_version_kaydet(ds_ver["version"], str(ds_path))
    print(f"\n  {GREEN}✓{NC}  .studio-version → v{ds_ver['version']}")

    toplam = len(guncellenenler) + len(eklenenler)
    if toplam == 0:
        print(f"  {GREEN}✅  Zaten güncel.{NC}")
    else:
        print(f"  {GREEN}✅  {toplam} dosya güncellendi.{NC}")

    if otomatik_commit and toplam > 0:
        dosyalar = guncellenenler + eklenenler + [".studio-version"]
        msg = (
            f"chore(studio): framework v{ds_ver['version']} güncellemesi uygulandı\n\n"
            + "\n".join(f"- {f}" for f in dosyalar)
        )
        try:
            subprocess.run(["git", "add"] + dosyalar, cwd=ROOT, check=True)
            status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
            if status.stdout.strip():
                subprocess.run(["git", "commit", "-m", msg], cwd=ROOT, check=True)
                subprocess.run(["git", "push", "origin", "HEAD"], cwd=ROOT, check=True)
                print(f"  {GREEN}✓{NC}  Commit + push tamamlandı.")
        except Exception as e:
            print(f"  {YELLOW}⚠{NC}  Git hatası: {e}")
    print()


def main():
    args = sys.argv[1:]
    if not args or "--yardim" in args or "--help" in args:
        print(f"""\n{BOLD}studio_updater.py{NC} — Digital Software Studio Framework Güncelleme Aracı

  --durum           Mevcut versiyon bilgisi
  --kontrol         DS ile fark raporu (değişiklik yapmaz)
  --uygula          Güncellemeleri projeye uygula
  --uygula --commit Uygula + otomatik git commit & push
""")
        return
    if "--durum" in args:
        cmd_durum()
    elif "--kontrol" in args:
        cmd_kontrol()
    elif "--uygula" in args:
        cmd_uygula(otomatik_commit="--commit" in args)
    else:
        print(f"{RED}Bilinmeyen komut.{NC}")
        sys.exit(1)


if __name__ == "__main__":
    main()
