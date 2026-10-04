#!/usr/bin/env python3
"""Gezgin ham bulgularından (_ham/*.json) şablonlu birim analiz dosyaları üretir (issue #132).

LLM'siz ve deterministiktir: her alan gözlenen veriden türer ve `[kaynak: ...]` işareti taşır;
gözlenmeyen alanlar `bilinmiyor` kalır (uydurma yok). Kelime tavanı aşılırsa listeler kısaltılır.
Kullanım: python3 scripts/kesif_yaz.py [--ham dizin] [--temizle]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as C  # noqa: E402
import analiz_dogrula as A  # noqa: E402

DURUM_RX = re.compile(r"(no [\w ]{3,40}(?:found|available|defined|installed|yet)|loading\.\.\.|failed|error|not active|not configured|empty)", re.I)
FILTRE_BTN = re.compile(r"(clear filters|last \d+ days|daily|weekly|monthly|all (teams|members|repositories|types?))", re.I)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "kok"


def liste(x, n):
    x = [str(i) for i in (x or []) if str(i).strip()]
    return ", ".join(x[:n]) + (f" (+{len(x) - n})" if len(x) > n else "")


def alanlar(r: dict, n: int) -> dict[str, str]:
    src = f"{r['url']}"
    fl = []
    if r.get("inp"):
        fl.append("arama/girdi: " + liste(r["inp"], n))
    fb = [b for b in r.get("btn", []) if FILTRE_BTN.search(b)]
    if fb:
        fl.append("seçiciler: " + liste(fb, n))
    if r.get("sel") or r.get("pick"):
        fl.append(f"{r.get('sel', 0)} açılır seçim, {r.get('pick', 0)} tarih seçici")
    wd = []
    if r.get("wid"):
        wd.append("widget id: " + liste(r["wid"], n))
    if r.get("h"):
        wd.append("başlıklar: " + liste(r["h"], n))
    if r.get("tabs"):
        wd.append("sekmeler: " + liste(r["tabs"], n))
    if r.get("th"):
        wd.append("tablo kolonları: " + liste(r["th"], n))
    if r.get("cv"):
        wd.append(f"{r['cv']} grafik (canvas)")
    md = []
    for m in r.get("modals", []):
        if m.get("acildi"):
            parca = f"'{m['label']}' → {m.get('tur', 'modal')} '{m.get('baslik', '')}'"
            if m.get("alanlar"):
                parca += "; alanlar: " + liste(m["alanlar"], n)
            elif m.get("metin"):
                parca += "; içerik: " + m["metin"][:90]
            if m.get("butonlar"):
                parca += "; butonlar: " + liste(m["butonlar"], 5)
            md.append(parca)
        elif m.get("sayfaya_gitti"):
            md.append(f"'{m['label']}' → sayfaya gider: {m['sayfaya_gitti']}")
        elif m.get("atlandi"):
            md.append(f"'{m['label']}' tıklanmadı ({m['atlandi']})")
        else:
            md.append(f"'{m['label']}' → modal/çekmece açılmadı")
    st = sorted({m.group(0).lower() for m in DURUM_RX.finditer(r.get("txt", ""))})
    rk = []
    if r.get("post_istekleri"):
        rk.append("yükleme sırasında GET dışı istek: " + liste(r["post_istekleri"], 4))
    for m in r.get("modals", []):
        if m.get("mutating_istek"):
            rk.append(f"'{m['label']}' tıklaması yazma isteği tetikledi: " + liste(m["mutating_istek"], 3))
    out = {
        "amaç": (r.get("desc") or "bilinmiyor") + (f" ({r['birim']} → {r['yonlendirme']} yönlendirir)" if r.get("yonlendirme") and r.get("desc") else ""),
        "roller": "bilinmiyor",
        "filtreler": "; ".join(fl) or "bilinmiyor",
        "widgetlar": "; ".join(wd) or "bilinmiyor",
        "modal ve çekmeceler": "; ".join(md) or "bilinmiyor",
        "durumlar": liste(st, n) or "bilinmiyor",
        "api uçları": liste(r.get("api"), n) or "bilinmiyor",
        "riskler": "; ".join(rk) or "bilinmiyor",
    }
    return {k: (v if v == "bilinmiyor" else f"{v} [kaynak: {src}]") for k, v in out.items()}


def render(r: dict, template: list[str], cap: int) -> str:
    for n in (12, 8, 6, 4, 3, 2):
        al = alanlar(r, n)
        body = [f"# {(r.get('h') or [r['birim']])[0]} ({r['birim']})", "Seviye: L1", f"URL: `{r['birim']}`", ""]
        for t in template:
            body += [f"## {t}", al.get(t, "bilinmiyor"), ""]
        text = "\n".join(body)
        if A.words(text) <= cap:
            return text
    return text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ham", default=None)
    ap.add_argument("--temizle", action="store_true", help="üretmeden önce <küme>/*.md dosyalarını sil")
    a = ap.parse_args(argv)
    cfg = C.load_config()
    if not cfg:
        print("[HATA] studio.config.json yok", file=sys.stderr)
        return 1
    out = C.ROOT / cfg["analysis"]["output_dir"]
    ham = Path(a.ham) if a.ham else out / "_ham"
    tpl = cfg["analysis"]["template"]
    cap = cfg["analysis"]["max_words_l1"]
    if a.temizle:
        for p in out.rglob("*.md"):
            if not p.name.startswith("_"):
                p.unlink()
    n = atlanan = 0
    for f in sorted(ham.glob("*.json")):
        if f.name.startswith("_"):
            continue
        r = json.loads(f.read_text(encoding="utf-8"))
        if r.get("durum") != "tamam":
            atlanan += 1
            continue
        kume = (r["birim"].strip("/").split("/")[0] or "kok").replace(":", "")
        d = out / kume
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{slug(r['birim'])}.md").write_text(render(r, tpl, cap), encoding="utf-8")
        n += 1
    print(f"{n} birim yazıldı, {atlanan} birim atlandı (hata/engelli/örnek yok)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
