#!/usr/bin/env python3
"""Korumalı keşif: sözleşme kontrolü + ziyaret günlüğü sapma denetçisi (issue #130).

İki kullanım:
  1) Ziyaret ÖNCESİ:  izin(url, eylem_sinifi, eylem, contract) -> (ok, neden)
  2) Koşu SONRASI:    python3 scripts/kesif_denetle.py [--config yol] [--log yol] [--json]
     Günlük (JSONL) satırı: {"birim","url","soru_id","eylem_sinifi","eylem","sonuc","derinlik","yeni_bulgu"}

İhlaller (çıkış kodu 1): izinsiz host/path, yasak path/eylem, mutating eylem,
bilinmeyen/eksik soru_id, birim başına eylem tavanı, toplam birim tavanı,
derinlik tavanı, envanter dışı ziyaret oranı > limits.max_off_inventory_pct.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as C  # noqa: E402

ACTION_CLASSES = ("read", "reversible", "mutating")


def _rx_any(patterns: list[str], s: str) -> bool:
    return any(re.search(p, s, re.I) for p in patterns)


def izin(url: str, eylem_sinifi: str, eylem: str, d: dict) -> tuple[bool, str]:
    """Tek bir ziyaret/eylem sözleşmeye uyuyor mu?"""
    u = urlparse(url)
    hosts = d["allow"]["hosts"]
    if u.netloc and u.netloc.lower() not in [h.lower() for h in hosts]:
        return False, f"izinsiz host: {u.netloc}"
    path = u.path or "/"
    ap = d["allow"].get("paths") or []
    if ap and not _rx_any(ap, path):
        return False, f"izinli path deseni dışında: {path}"
    if _rx_any(d["deny"].get("paths") or [], path):
        return False, f"yasak path: {path}"
    if eylem_sinifi not in ACTION_CLASSES:
        return False, f"bilinmeyen eylem sınıfı: {eylem_sinifi}"
    if eylem_sinifi == "mutating":
        return False, "mutating eylem yasak (read_only mod)"
    if eylem and eylem.lower() in [x.lower() for x in d["deny"].get("actions") or []]:
        return False, f"yasak eylem: {eylem}"
    for lab in d["deny"].get("labels") or []:
        if eylem and re.search(rf"\b{re.escape(lab)}\b", eylem, re.I):
            return False, f"yasak etiket: {eylem} ({lab})"
    return True, "ok"


def sunucu(d: dict) -> None:
    """stdin'den JSON satırı ({url,sinif,eylem}) okur, stdout'a {ok,neden} yazar.
    Gezginin tek süreçle izin sorgulaması içindir (kural kaynağı tek: izin())."""
    for ln in sys.stdin:
        ln = ln.strip()
        if not ln:
            continue
        q = json.loads(ln)
        ok, neden = izin(q.get("url", ""), q.get("sinif", "read"), q.get("eylem", ""), d)
        print(json.dumps({"ok": ok, "neden": neden}, ensure_ascii=False), flush=True)


def load_inventory(path: Path) -> list[re.Pattern] | None:
    """Envanter: JSON liste veya satır başına bir URL path deseni (`:param` = tek segment).
    Dosya yoksa None (envanter oranı denetlenmez)."""
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8").strip()
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        items = [ln.split("\t")[0].strip() for ln in raw.splitlines()]
    pats = []
    for it in items:
        it = str(it).strip()
        if not it or it.startswith("#"):
            continue
        rx = re.sub(r":[A-Za-z0-9_]+", "[^/]+", re.escape(it).replace(r"\:", ":"))
        rx = rx.replace(r"\*\*", ".*")
        pats.append(re.compile(rf"^{rx}/?$"))
    return pats


def in_inventory(url: str, pats: list[re.Pattern]) -> bool:
    return any(p.match(urlparse(url).path or "/") for p in pats)


def read_log(path: Path) -> list[dict]:
    rows = []
    if path.exists():
        for i, ln in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if ln.strip():
                try:
                    rows.append(json.loads(ln))
                except json.JSONDecodeError:
                    rows.append({"_bozuk_satir": i})
    return rows


def denetle(rows: list[dict], d: dict, inventory: list[re.Pattern] | None = None) -> dict:
    lim = d["limits"]
    qn = len(d.get("questions") or [])
    viol: list[str] = []
    per_unit: dict[str, int] = defaultdict(int)
    off = 0
    sampling = 0
    for i, r in enumerate(rows, 1):
        if "_bozuk_satir" in r:
            viol.append(f"satır {r['_bozuk_satir']}: geçersiz JSON")
            continue
        ok, why = izin(r.get("url", ""), r.get("eylem_sinifi", ""), r.get("eylem", ""), d)
        if not ok:
            viol.append(f"satır {i} {r.get('url','?')}: {why}")
        sid = str(r.get("soru_id", "")).strip()
        m = re.fullmatch(r"Q?(\d+)", sid, re.I)
        if not m or not (1 <= int(m.group(1)) <= max(qn, 1)):
            viol.append(f"satır {i}: soru_id eksik/bilinmeyen ('{sid}')")
        if int(r.get("derinlik", 0) or 0) > lim["max_depth"]:
            viol.append(f"satır {i}: derinlik {r.get('derinlik')} > {lim['max_depth']}")
        if str(r.get("birim", "")).startswith("~"):      # örnekleme yardımcı satırları birim sayılmaz
            sampling += 1
        else:
            per_unit[r.get("birim", "?")] += 1
        if inventory is not None and not in_inventory(r.get("url", ""), inventory):
            off += 1
    for b, n in per_unit.items():
        if n > lim["max_actions_per_unit"]:
            viol.append(f"birim '{b}': {n} eylem > tavan {lim['max_actions_per_unit']}")
    if sampling > lim.get("max_sampling_actions", 300):
        viol.append(f"örnekleme eylemi {sampling} > tavan {lim.get('max_sampling_actions', 300)}")
    if len(per_unit) > lim["max_units"]:
        viol.append(f"{len(per_unit)} birim > tavan {lim['max_units']}")
    off_pct = round(100 * off / len(rows), 1) if rows and inventory is not None else 0.0
    if inventory is not None and off_pct > lim.get("max_off_inventory_pct", 10):
        viol.append(f"envanter dışı ziyaret %{off_pct} > %{lim.get('max_off_inventory_pct', 10)}")
    return {"adim": len(rows), "birim": len(per_unit), "envanter_disi_pct": off_pct,
            "ihlaller": viol}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", default=None)
    ap.add_argument("--log", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--sunucu", action="store_true", help="stdin'den izin sorguları yanıtla")
    a = ap.parse_args(argv)
    cfg = C.load_config(Path(a.config) if a.config else None)
    if not cfg:
        print("[HATA] workspace/studio.config.json yok: keşif sözleşmesi tanımlı değil.", file=sys.stderr)
        return 1
    errs = C.validate_discovery(cfg)
    if errs:
        print("\n".join(f"[sözleşme] {e}" for e in errs), file=sys.stderr)
        return 1
    d = cfg["discovery"]
    if a.sunucu:
        sunucu(d)
        return 0
    inv = load_inventory(C.ROOT / d["inventory"])
    rep = denetle(read_log(Path(a.log) if a.log else C.ROOT / d["log"]), d, inv)
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        print(f"{rep['adim']} adım, {rep['birim']} birim, envanter dışı %{rep['envanter_disi_pct']}, "
              f"ihlal={len(rep['ihlaller'])}")
        for v in rep["ihlaller"]:
            print(f"  ✗ {v}")
    return 1 if rep["ihlaller"] else 0


if __name__ == "__main__":
    sys.exit(main())
