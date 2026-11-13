#!/usr/bin/env python3
"""
scripts/github_issue_bridge.py
Digital Software Studio — GitHub Issues & Project Management Entegrasyonu

Müşterinin (proje sahibi) açtığı her talep ve hata bildirimi için
bağlı GitHub deposunda otomatik GitHub Issue açar, çözüm planlarını
yoruma ekler, tamamlandığında issue'yu kapatır ve depodaki açık
issue/PR'ları tarayarak stüdyo iş listesine aktarılmasını sağlar.
"""

import argparse
import json
import os
import re
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


def github_issue_olustur(talep: dict, cwd: Path | None = None) -> tuple[int, str] | None:
    """Verilen müşteri talebi için GitHub'da yeni bir Issue açar."""
    if not gh_mevcut_mu():
        return None

    work_dir = cwd or ROOT
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

    for lbl in labels:
        cmd.extend(["--label", lbl])

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(work_dir), timeout=15)
        if res.returncode != 0 and "label" in res.stderr.lower():
            cmd_no_labels = ["gh", "issue", "create", "--title", issue_title, "--body", body]
            res = subprocess.run(cmd_no_labels, capture_output=True, text=True, cwd=str(work_dir), timeout=15)

        if res.returncode == 0:
            url = res.stdout.strip()
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


def github_issue_yorum_ekle(issue_ref: str | int, yorum: str, cwd: Path | None = None) -> bool:
    """Açılmış bir GitHub Issue'suna yorum (örn. Studio Yetkilisi Çözüm Planı) ekler."""
    if not gh_mevcut_mu() or not issue_ref:
        return False
    work_dir = cwd or ROOT
    cmd = ["gh", "issue", "comment", str(issue_ref), "--body", yorum]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(work_dir), timeout=15)
        return res.returncode == 0
    except Exception as e:
        print(f"  [!] Issue yorum ekleme hatası: {e}", file=sys.stderr)
        return False


def github_issue_kapat(issue_ref: str | int, kapanis_notu: str = "", cwd: Path | None = None) -> bool:
    """Çözülen talebin GitHub Issue'sunu kapatır."""
    if not gh_mevcut_mu() or not issue_ref:
        return False
    work_dir = cwd or ROOT
    cmd = ["gh", "issue", "close", str(issue_ref)]
    if kapanis_notu:
        cmd.extend(["--comment", kapanis_notu])
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(work_dir), timeout=15)
        return res.returncode == 0
    except Exception as e:
        print(f"  [!] Issue kapatma hatası: {e}", file=sys.stderr)
        return False


# ==============================================================================
# Inbound Discovery: GitHub'daki Açık Issue ve PR'ları Tarama & İçe Aktarma
# ==============================================================================

def github_acik_isleri_tara(cwd: Path | None = None) -> list[dict]:
    """GitHub üzerindeki açık Issue ve PR'ları listeler."""
    if not gh_mevcut_mu():
        return []
    work_dir = cwd or ROOT
    items = []

    # 1. Açık Issue'ları getir
    try:
        res = subprocess.run(
            ["gh", "issue", "list", "--state", "open", "--limit", "50",
             "--json", "number,title,body,url,labels"],
            capture_output=True, text=True, cwd=str(work_dir), timeout=15
        )
        if res.returncode == 0 and res.stdout.strip():
            for issue in json.loads(res.stdout):
                issue["is_pr"] = False
                items.append(issue)
    except Exception as e:
        print(f"  [!] GitHub açık issue tarama hatası: {e}", file=sys.stderr)

    # 2. Açık PR'ları getir
    try:
        res = subprocess.run(
            ["gh", "pr", "list", "--state", "open", "--limit", "50",
             "--json", "number,title,body,url,labels,headRefName"],
            capture_output=True, text=True, cwd=str(work_dir), timeout=15
        )
        if res.returncode == 0 and res.stdout.strip():
            for pr in json.loads(res.stdout):
                pr["is_pr"] = True
                items.append(pr)
    except Exception as e:
        print(f"  [!] GitHub açık PR tarama hatası: {e}", file=sys.stderr)

    return items


def eslenmemis_github_islerini_bul(cwd: Path | None = None) -> list[dict]:
    """Stüdyo talepleri (musteri_talepleri.md / DB) ile henüz eşleşmemiş açık GitHub issue ve PR'larını döner."""
    acik_isler = github_acik_isleri_tara(cwd)
    if not acik_isler:
        return []

    work_dir = cwd or ROOT
    bilinen_issue_nolar = set()
    bilinen_talep_kodlari = set()

    try:
        scripts_dir = str(work_dir / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import musteri_talepleri as MT
        data = MT.load_data()
        for t in data.get("talepler", []):
            if t.get("github_issue_number"):
                bilinen_issue_nolar.add(int(t["github_issue_number"]))
            if t.get("id"):
                bilinen_talep_kodlari.add(t["id"].upper())
            if t.get("github_issue_url"):
                m = re.search(r"/(?:issues|pull)/(\d+)", t["github_issue_url"])
                if m:
                    bilinen_issue_nolar.add(int(m.group(1)))
            m_t = re.findall(r"TALEP-\d+", f"{t.get('baslik', '')} {t.get('aciklama', '')}")
            for tid in m_t:
                bilinen_talep_kodlari.add(tid.upper())
    except Exception:
        pass

    eslenmemis = []
    for item in acik_isler:
        num = item.get("number")
        if num in bilinen_issue_nolar:
            continue
        title = item.get("title", "")
        m_title = re.search(r"\[?(TALEP-\d+)\]?", title, re.IGNORECASE)
        if m_title and m_title.group(1).upper() in bilinen_talep_kodlari:
            continue
        eslenmemis.append(item)

    return eslenmemis


def github_isini_talebe_aktar(item: dict, cwd: Path | None = None) -> dict | None:
    """Verilen GitHub Issue veya PR'ı yeni bir TALEP olarak stüdyoya kaydeder."""
    work_dir = cwd or ROOT
    scripts_dir = str(work_dir / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import musteri_talepleri as MT
    from datetime import datetime

    num = item.get("number")
    title = item.get("title", f"GitHub Issue #{num}")
    body = item.get("body", "") or "GitHub üzerinden aktarıldı."
    url = item.get("url", "")
    is_pr = item.get("is_pr", False)

    # Etiketlerden tür ve öncelik tespiti
    labels = []
    for l in item.get("labels", []):
        if isinstance(l, dict):
            labels.append(l.get("name", "").lower())
        else:
            labels.append(str(l).lower())

    tur = "HATA"
    if is_pr or any(l in labels for l in ["enhancement", "feature", "istek", "özellik"]):
        tur = "ISTEK"
    elif any(l in labels for l in ["bug", "hata"]):
        tur = "HATA"
    elif any(l in labels for l in ["design", "ux", "tasarım"]):
        tur = "UX"
    elif any(l in labels for l in ["data", "veri"]):
        tur = "VERI"

    oncelik = "NORMAL"
    if any(l in labels for l in ["p1", "p1-kritik", "critical", "kritik"]):
        oncelik = "KRITIK"
    elif any(l in labels for l in ["p2", "p2-yuksek", "high", "yuksek"]):
        oncelik = "YUKSEK"

    # Başlığı temizle
    temiz_baslik = re.sub(r"^\[TALEP-\d+\]\s*", "", title, flags=re.IGNORECASE)
    temiz_baslik = re.sub(r"^\[(HATA|ISTEK|UX|VERI|PERFORMANS)\]\s*", "", temiz_baslik, flags=re.IGNORECASE).strip()

    data = MT.load_data()
    talep_id = f"TALEP-{MT._sonraki_talep_no():03d}"

    yeni = {
        "id": talep_id,
        "tarih": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "tur": tur,
        "oncelik": oncelik,
        "baslik": temiz_baslik,
        "aciklama": f"{body}\n\n*Kaynak: GitHub {'PR' if is_pr else 'Issue'} #{num} ({url})*",
        "sayfa_url": "/",
        "durum": "BEKLEMEDE",
        "gorevli_rol": None,
        "studio_notu": f"GitHub #{num} üzerinden içe aktarıldı.",
        "cozum_plani": None,
        "github_issue_number": num,
        "github_issue_url": url,
        "gecmis": [
            {
                "zaman": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "eylem": f"GitHub {'PR' if is_pr else 'Issue'} #{num} üzerinden stüdyoya aktarıldı",
                "durum": "BEKLEMEDE"
            }
        ]
    }

    data.setdefault("talepler", []).append(yeni)
    MT.save_data(data)
    print(f"  [✓] GitHub #{num} -> {talep_id} olarak stüdyoya aktarıldı: {temiz_baslik}")
    return yeni


def interaktif_github_senkronizasyonu(cwd: Path | None = None) -> int:
    """Kullanıcıya eşleşmemiş açık GitHub issue/PR'larını sorup onaylananları stüdyoya aktarır."""
    eslenmemis = eslenmemis_github_islerini_bul(cwd)
    if not eslenmemis:
        print("  [i] GitHub üzerinde stüdyoya aktarılmamış açık issue veya PR bulunamadı.")
        return 0

    print(f"\n  🐙 GitHub üzerinde stüdyoya henüz dahil edilmemiş {len(eslenmemis)} açık iş tespit edildi:")
    print("  " + "─" * 60)
    aktarilan = 0
    for item in eslenmemis:
        tur_etiketi = "PR" if item.get("is_pr") else "Issue"
        num = item.get("number")
        title = item.get("title", "")
        print(f"\n  📌 #{num} [{tur_etiketi}] {title}")
        print(f"     URL: {item.get('url')}")
        
        try:
            cevap = input("     Bu iş stüdyo iş listesine (backlog) alınıp yapılsın mı? [E/h]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  [!] Senkronizasyon kullanıcı tarafından iptal edildi.")
            break

        if cevap in ("", "e", "evet", "y", "yes"):
            github_isini_talebe_aktar(item, cwd)
            aktarilan += 1
        else:
            print(f"     [–] #{num} atlandı.")

    print(f"\n  [✓] Toplam {aktarilan} adet GitHub görevi stüdyoya başarıyla aktarıldı.\n")
    return aktarilan


def main():
    parser = argparse.ArgumentParser(description="Digital Software Studio — GitHub Issues Bridge")
    parser.add_argument("--scan", action="store_true", help="GitHub'daki eşleşmemiş açık issue/PR'ları listeler")
    parser.add_argument("--interactive", "--sync", action="store_true", help="Açık issue/PR'ları kullanıcıya sorarak stüdyoya aktarır")
    parser.add_argument("--auto-all", action="store_true", help="Tüm açık issue/PR'ları sormadan otomatik aktarır")
    args = parser.parse_args()

    if args.scan:
        items = eslenmemis_github_islerini_bul()
        print(json.dumps(items, ensure_ascii=False, indent=2))
        sys.exit(0)

    if args.interactive:
        interaktif_github_senkronizasyonu()
        sys.exit(0)

    if args.auto_all:
        items = eslenmemis_github_islerini_bul()
        count = 0
        for item in items:
            if github_isini_talebe_aktar(item):
                count += 1
        print(f"  [✓] {count} iş otomatik aktarıldı.")
        sys.exit(0)

    parser.print_help()


if __name__ == "__main__":
    main()
