#!/usr/bin/env python3
"""
scripts/github_issue_bridge.py
Digital Software Studio — GitHub Issues & Project Management Entegrasyonu

Müşterinin (proje sahibi) açtığı her talep ve hata bildirimi için
bağlı GitHub deposunda otomatik GitHub Issue açar, çözüm planlarını
yoruma ekler ve tamamlandığında issue'yu kapatır.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def gh_mevcut_mu() -> bool:
    """GitHub CLI (gh) kurulu ve oturum açılmış mı kontrol eder."""
    if not shutil.which("gh"):
        return False
    try:
        res = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=4
        )
        return res.returncode == 0
    except Exception:
        return False


def etiket_hazirla(tur: str, oncelik: str) -> list[str]:
    """Mevcut GitHub label standartlarına uygun etiketler üretir."""
    etiketler = ["musteri-talebi"]
    tur_map = {
        "HATA": "bug",
        "ISTEK": "enhancement",
        "UX": "design",
        "VERI": "data",
        "PERFORMANS": "performance"
    }
    if tur.upper() in tur_map:
        etiketler.append(tur_map[tur.upper()])

    oncelik_map = {
        "KRITIK": "p1-kritik",
        "YUKSEK": "p2-yuksek",
        "NORMAL": "p3-normal",
        "DUSUK": "p4-dusuk"
    }
    if oncelik.upper() in oncelik_map:
        etiketler.append(oncelik_map[oncelik.upper()])

    return etiketler


def github_issue_olustur(talep: dict) -> tuple[int, str] | None:
    """Verilen müşteri talebi için GitHub'da yeni bir Issue açar."""
    if not gh_mevcut_mu():
        return None

    tid = talep.get("id", "TALEP")
    tur = talep.get("tur", "HATA")
    baslik = talep.get("baslik", "İsimsiz Talep")
    issue_title = f"[{tid}] [{tur}] {baslik}"

    body = f"""## ⚡ Müşteri Denetim & Geri Bildirim Kaydı

| Alan | Bilgi |
|---|---|
| **Talep ID** | `{tid}` |
| **Bildiren** | Proje Sahibi (Müşteri Denetçisi) |
| **Tarih** | {talep.get('tarih')} |
| **Tür** | {tur} |
| **Öncelik** | {talep.get('oncelik')} |
| **Ekran / URL** | `{talep.get('sayfa_url', '/')}` |

### 📝 Müşteri Açıklaması & Hata Adımları
> {talep.get('aciklama', 'Açıklama belirtilmedi.')}

---
*Bu Issue `musteri.sh` CLI ve Digital Software Studio yönetim motoru tarafından otomatik oluşturulmuştur.*
"""

    labels = etiket_hazirla(tur, talep.get("oncelik", "NORMAL"))
    cmd = ["gh", "issue", "create", "--title", issue_title, "--body", body]

    # Etiketleri ekle (eğer depo etiketleri destekliyorsa)
    for lbl in labels:
        cmd.extend(["--label", lbl])

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), timeout=15)
        # Eğer etiket yoksa etiketler olmadan tekrar dene
        if res.returncode != 0 and "label" in res.stderr.lower():
            cmd_no_labels = ["gh", "issue", "create", "--title", issue_title, "--body", body]
            res = subprocess.run(cmd_no_labels, capture_output=True, text=True, cwd=str(ROOT), timeout=15)

        if res.returncode == 0:
            url = res.stdout.strip()
            # URL formatı: https://github.com/org/repo/issues/1
            try:
                num = int(url.rstrip("/").split("/")[-1])
            except Exception:
                num = None
            return num, url
        else:
            print(f"  [!] GitHub Issue oluşturulamadı: {res.stderr.strip()}", file=sys.stderr)
            return None
    except Exception as e:
        print(f"  [!] GitHub CLI çağrısında hata: {e}", file=sys.stderr)
        return None


def github_issue_yorum_ekle(issue_ref: str | int, yorum: str) -> bool:
    """Açılmış bir GitHub Issue'suna yorum (örn. Studio Yetkilisi Çözüm Planı) ekler."""
    if not gh_mevcut_mu() or not issue_ref:
        return False
    cmd = ["gh", "issue", "comment", str(issue_ref), "--body", yorum]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), timeout=15)
        return res.returncode == 0
    except Exception as e:
        print(f"  [!] Issue yorum ekleme hatası: {e}", file=sys.stderr)
        return False


def github_issue_kapat(issue_ref: str | int, kapanis_notu: str = "") -> bool:
    """Çözülen talebin GitHub Issue'sunu kapatır."""
    if not gh_mevcut_mu() or not issue_ref:
        return False
    cmd = ["gh", "issue", "close", str(issue_ref)]
    if kapanis_notu:
        cmd.extend(["--comment", kapanis_notu])
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), timeout=15)
        return res.returncode == 0
    except Exception as e:
        print(f"  [!] Issue kapatma hatası: {e}", file=sys.stderr)
        return False
