#!/usr/bin/env python3
"""Mod 2 — Tahribatsız Mevcut Proje Analizi (Keşif & Sağlık Denetimi, issue #321).

Var olan bir projenin (`workspace/src`, git geçmişi, build/test çıktıları ve varsa
`workspace/studio.db`) mevcut durumunu SALT-OKUNUR şekilde inceler; eksik, hata (bug),
tutarsızlık ve iyileştirme fırsatlarını tespit eder.

Çıktılar:
  - workspace/docs/mevcut_proje_analizi.md   (okunabilir özet rapor)
  - workspace/docs/mevcut_proje_durumu.json  (yapılandırılmış bulgu ve envanter)

Kural: Mevcut çalışan koda, manuel müdahalelere ve `studio.db` geçmişine dokunmaz.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

YOKSAY_DIZIN = {".git", "node_modules", ".venv", "venv", "__pycache__", ".nuxt", "dist", "build", ".next", "coverage"}
KOD_UZANTILARI = {".py", ".ts", ".tsx", ".js", ".jsx", ".vue", ".go", ".rs", ".java", ".kt", ".swift", ".sql", ".sh"}


def _simdi() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _komut_calistir(cmd: list[str] | str, cwd: Path, timeout: int = 30, shell: bool = False) -> dict:
    try:
        r = subprocess.run(
            cmd,
            cwd=cwd,
            shell=shell,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        cikti = ((r.stdout or "") + ("\n" + r.stderr if r.stderr else "")).strip()
        return {"ok": r.returncode == 0, "kod": r.returncode, "cikti": cikti[:2000]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "kod": -1, "cikti": f"zaman aşımı ({timeout}s)"}
    except OSError as e:
        return {"ok": False, "kod": -1, "cikti": str(e)}


def src_envanteri(kok: Path = ROOT) -> dict:
    """`workspace/src` altındaki dosyaları ve teknoloji yığınını salt-okunur tarar."""
    src_dir = kok / "workspace" / "src"
    if not src_dir.is_dir():
        return {"var": False, "dosya_sayisi": 0, "uzantilar": {}, "bilesenler": [], "paket_yoneticileri": []}

    uzantilar: Counter[str] = Counter()
    dosya_sayisi = 0
    buyuk_dosyalar: list[dict] = []
    for p in src_dir.rglob("*"):
        if any(part in YOKSAY_DIZIN for part in p.parts):
            continue
        if not p.is_file():
            continue
        dosya_sayisi += 1
        ext = p.suffix.lower() or "(uzantısız)"
        uzantilar[ext] += 1
        if ext in KOD_UZANTILARI:
            try:
                satir = len(p.read_text(encoding="utf-8", errors="ignore").splitlines())
                if satir >= 500:
                    buyuk_dosyalar.append({"yol": str(p.relative_to(kok)), "satir": satir})
            except OSError:
                pass

    bilesenler = sorted(
        d.name for d in src_dir.iterdir()
        if d.is_dir() and d.name not in YOKSAY_DIZIN and not d.name.startswith(".")
    )

    paketler: list[dict] = []
    for manifest in ("package.json", "pyproject.toml", "requirements.txt", "go.mod", "Cargo.toml"):
        for mp in sorted(src_dir.rglob(manifest)):
            if any(part in YOKSAY_DIZIN for part in mp.parts):
                continue
            bilgi: dict = {"dosya": str(mp.relative_to(kok)), "tip": manifest}
            if manifest == "package.json":
                try:
                    pkg = json.loads(mp.read_text(encoding="utf-8"))
                    bilgi["ad"] = pkg.get("name", "")
                    bilgi["scripts"] = sorted((pkg.get("scripts") or {}).keys())
                    bilgi["bagimlilik_sayisi"] = len(pkg.get("dependencies") or {})
                except (OSError, ValueError):
                    bilgi["bozuk"] = True
            paketler.append(bilgi)

    buyuk_dosyalar.sort(key=lambda x: x["satir"], reverse=True)
    return {
        "var": True,
        "dosya_sayisi": dosya_sayisi,
        "uzantilar": dict(uzantilar.most_common(12)),
        "bilesenler": bilesenler,
        "paket_yoneticileri": paketler,
        "buyuk_dosyalar": buyuk_dosyalar[:10],
    }


def git_durumu(kok: Path = ROOT) -> dict:
    """Git çalışma ağacı ve son commit geçmişini salt-okunur okur."""
    if not (kok / ".git").exists():
        return {"git_repo": False, "dal": "", "kirli_dosyalar": [], "son_commitler": []}
    dal = _komut_calistir(["git", "rev-parse", "--abbrev-ref", "HEAD"], kok)["cikti"]
    st = _komut_calistir(["git", "status", "--porcelain"], kok)
    kirli = [line for line in st["cikti"].splitlines() if line.strip()]
    log = _komut_calistir(["git", "log", "-n", "10", "--oneline"], kok)
    commitler = [line for line in log["cikti"].splitlines() if line.strip()]
    return {
        "git_repo": True,
        "dal": dal,
        "kirli_sayisi": len(kirli),
        "kirli_dosyalar": kirli[:30],
        "son_commitler": commitler,
    }


def db_durumu(kok: Path = ROOT) -> dict:
    """Varsa `workspace/studio.db` içindeki pano, faz ve talep durumunu salt-okunur özetler."""
    db_path = kok / "workspace" / "studio.db"
    if not db_path.exists():
        return {"var": False}
    import sqlite3
    ozet: dict = {"var": True, "fazlar": [], "sprint_sayisi": 0, "gorev_durumlari": {}, "acik_talepler": []}
    conn = None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10.0)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        tablolar = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "fazlar" in tablolar:
            ozet["fazlar"] = [
                {"id": r["id"], "ad": r["ad"], "durum": r["durum"]}
                for r in cur.execute("SELECT id, ad, durum FROM fazlar").fetchall()
            ]
        if "sprintler" in tablolar:
            ozet["sprint_sayisi"] = cur.execute("SELECT COUNT(*) FROM sprintler").fetchone()[0]
        if "pano_gorevleri" in tablolar:
            durumlar: Counter[str] = Counter()
            sorunlu: list[dict] = []
            for r in cur.execute("SELECT id, title, status, note FROM pano_gorevleri").fetchall():
                durumlar[r["status"]] += 1
                if r["status"] in ("FAILED", "RUNNING"):
                    sorunlu.append({"id": r["id"], "title": r["title"], "status": r["status"], "note": (r["note"] or "")[:160]})
            ozet["gorev_durumlari"] = dict(durumlar)
            ozet["sorunlu_gorevler"] = sorunlu
        if "talepler" in tablolar:
            ozet["acik_talepler"] = [
                {"id": r["id"], "tur": r["tur"], "baslik": r["baslik"], "durum": r["durum"], "oncelik": r["oncelik"]}
                for r in cur.execute(
                    "SELECT id, tur, baslik, durum, oncelik FROM talepler WHERE durum NOT IN ('TAMAMLANDI', 'IPTAL', 'COZULDU')"
                ).fetchall()
            ]
    except sqlite3.Error as e:
        ozet["hata"] = str(e)
    finally:
        if conn:
            conn.close()
    return ozet


def kontrolleri_calistir(kok: Path = ROOT, hizli: bool = False) -> list[dict]:
    """`workspace/build_checklist.json` varsa tanımlı derleme/test kontrollerini çalıştırır."""
    if hizli:
        return []
    sonuclar: list[dict] = []
    bc = kok / "workspace" / "build_checklist.json"
    if bc.is_file():
        try:
            checks = json.loads(bc.read_text(encoding="utf-8")).get("checks") or []
        except (OSError, ValueError):
            checks = []
        for c in checks[:8]:
            cmd = c.get("command")
            if not cmd:
                continue
            cwd = kok / (c.get("cwd") or ".")
            if not cwd.is_dir():
                sonuclar.append({"ad": c.get("name", cmd), "ok": False, "cikti": f"dizin yok: {cwd}"})
                continue
            res = _komut_calistir(cmd, cwd, timeout=int(c.get("timeout_s") or 60), shell=True)
            sonuclar.append({"ad": c.get("name", cmd), **res})
    return sonuclar


def bulgulari_cikar(envanter: dict, git_b: dict, db_b: dict, kontroller: list[dict], kok: Path) -> list[dict]:
    """Toplanan verilerden deterministik eksik, bug, tutarsızlık ve iyileştirme listesi üretir."""
    bulgular: list[dict] = []
    sayac = 1

    def ekle(tip: str, siddet: str, baslik: str, detay: str, kaynak: str):
        nonlocal sayac
        bulgular.append({
            "id": f"B{sayac}",
            "tip": tip,          # bug | eksik | tutarsizlik | iyilestirme
            "siddet": siddet,    # yuksek | orta | dusuk
            "baslik": baslik,
            "detay": detay,
            "kaynak": kaynak,
        })
        sayac += 1

    if not envanter.get("var") or envanter.get("dosya_sayisi", 0) == 0:
        ekle("eksik", "yuksek", "workspace/src altında kaynak kod bulunamadı",
             "Mod 2 devralma için workspace/src içinde mevcut kod tabanı beklenir.", "src_envanteri")

    for k in kontroller:
        if not k.get("ok"):
            ekle("bug", "yuksek", f"Derleme/test kontrolü başarısız: {k['ad']}",
                 (k.get("cikti") or "")[:300], "build_checklist")

    for p in envanter.get("paket_yoneticileri", []):
        if p.get("bozuk"):
            ekle("bug", "yuksek", f"Geçersiz manifest dosyası: {p['dosya']}",
                 "JSON ayrıştırma hatası.", p["dosya"])

    if git_b.get("kirli_sayisi", 0) > 0:
        ekle("tutarsizlik", "orta", f"Commit edilmemiş manuel değişiklikler var ({git_b['kirli_sayisi']} dosya)",
             "Örnek: " + ", ".join(git_b.get("kirli_dosyalar", [])[:5]), "git")

    if db_b.get("var"):
        for g in db_b.get("sorunlu_gorevler", []):
            ekle("bug" if g["status"] == "FAILED" else "tutarsizlik", "yuksek",
                 f"Pano görevi sorunlu: {g['id']} ({g['status']})",
                 f"{g['title']} — {g['note']}", "studio.db")
        for t in db_b.get("acik_talepler", []):
            ekle("bug" if t["tur"] == "HATA" else "eksik", "orta",
                 f"Açık müşteri talebi: {t['id']} ({t['tur']})",
                 f"{t['baslik']} [durum={t['durum']}, öncelik={t['oncelik']}]", "studio.db")

    if not (kok / "workspace" / "docs" / "proje_kapsami.md").exists() and not (kok / "proje_kapsami.md").exists():
        ekle("eksik", "dusuk", "proje_kapsami.md bulunamadı",
             "Hedef kapsam ve iş kuralları için özet kapsam dokümanı oluşturulması önerilir.", "docs")

    for bd in envanter.get("buyuk_dosyalar", [])[:3]:
        ekle("iyilestirme", "dusuk", f"Büyük kaynak dosya ({bd['satir']} satır): {bd['yol']}",
             "Modülerleştirme ve bakım kolaylığı için bölünmesi değerlendirilebilir.", bd["yol"])

    return bulgular


def rapor_markdown(durum: dict) -> str:
    env = durum["envanter"]
    git_b = durum["git"]
    db_b = durum["studio_db"]
    bulgular = durum["bulgular"]

    satirlar = [
        "# Mevcut Proje Analizi (Mod 2 — Salt-Okunur Sağlık Denetimi)",
        "",
        f"> Üretim zamanı: `{durum['zaman']}` · Bu rapor mevcut koda ve `studio.db` geçmişine dokunmadan üretilmiştir.",
        "",
        "## 1. Kod Tabanı Özeti",
        f"- **workspace/src mevcut mu:** {'Evet' if env.get('var') else 'Hayır'}",
        f"- **Toplam dosya sayısı:** {env.get('dosya_sayisi', 0)}",
        f"- **Bileşenler:** {', '.join(env.get('bilesenler') or ['—'])}",
        f"- **Başlıca uzantılar:** {', '.join(f'{k} ({v})' for k, v in (env.get('uzantilar') or {}).items()) or '—'}",
        "",
        "## 2. Git Durumu",
        f"- **Dal:** `{git_b.get('dal') or '—'}` · **Commit edilmemiş değişiklik:** {git_b.get('kirli_sayisi', 0)} dosya",
    ]
    if git_b.get("son_commitler"):
        satirlar.append("- **Son commit'ler:**")
        satirlar.extend(f"  - `{c}`" for c in git_b["son_commitler"][:5])

    satirlar.extend(["", "## 3. Stüdyo Panosu (studio.db)"])
    if db_b.get("var"):
        satirlar.append(f"- **Sprint sayısı:** {db_b.get('sprint_sayisi', 0)}")
        satirlar.append(f"- **Görev durumları:** {db_b.get('gorev_durumlari') or '—'}")
        satirlar.append(f"- **Açık talep sayısı:** {len(db_b.get('acik_talepler') or [])}")
    else:
        satirlar.append("- `workspace/studio.db` henüz yok (dışarıdan mevcut kod tabanı olarak devralınacak).")

    if durum.get("kontroller"):
        satirlar.extend(["", "## 4. Derleme / Test Kontrolleri"])
        for k in durum["kontroller"]:
            ikon = "✓" if k["ok"] else "✗"
            satirlar.append(f"- {ikon} **{k['ad']}** (kod={k['kod']})")

    satirlar.extend(["", "## 5. Tespit Edilen Bulgular (Eksik / Hata / Tutarsızlık / İyileştirme)"])
    if not bulgular:
        satirlar.append("- Kritik bir eksik veya hata tespit edilmedi.")
    else:
        for b in bulgular:
            satirlar.append(f"- **[{b['id']}] ({b['tip'].upper()} / {b['siddet']}) {b['baslik']}** — {b['detay']} _(kaynak: {b['kaynak']})_")

    return "\n".join(satirlar) + "\n"


def analiz_calistir(kok: Path = ROOT, hizli: bool = False) -> dict:
    """Tam salt-okunur analizi çalıştırır ve `workspace/docs/mevcut_proje_*` dosyalarını yazar."""
    env = src_envanteri(kok)
    git_b = git_durumu(kok)
    db_b = db_durumu(kok)
    kontroller = kontrolleri_calistir(kok, hizli=hizli)
    bulgular = bulgulari_cikar(env, git_b, db_b, kontroller, kok)

    durum = {
        "zaman": _simdi(),
        "envanter": env,
        "git": git_b,
        "studio_db": db_b,
        "kontroller": kontroller,
        "bulgular": bulgular,
    }
    docs = kok / "workspace" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "mevcut_proje_durumu.json").write_text(
        json.dumps(durum, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (docs / "mevcut_proje_analizi.md").write_text(
        rapor_markdown(durum), encoding="utf-8"
    )
    return durum


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Mod 2 — Salt-okunur mevcut proje analizi")
    ap.add_argument("--hizli", action="store_true", help="build/test komutlarını çalıştırmadan hızlı envanter çıkar")
    args = ap.parse_args()
    d = analiz_calistir(ROOT, hizli=args.hizli)
    print(f"[✓] Analiz tamamlandı: {len(d['bulgular'])} bulgu.")
    print("    Rapor: workspace/docs/mevcut_proje_analizi.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
