#!/usr/bin/env python3
"""Birim analiz dosyaları için deterministik (LLM'siz) doğrulayıcı (issue #130).

Denetler (studio.config.json → analysis):
  - her birim dosyası şablon alanlarının hepsini içerir (## <alan>)
  - `Seviye: L1|L2` başlığı var; kelime tavanı seviyeye göre aşılmamış
  - dolu her alan `[kaynak: ...]` işareti taşır veya değeri `bilinmiyor`
  - L2 dosya sayısı kotayı (%pct, max) aşmıyor
  - birbirine çok benzeyen dosyalar (≥%80 satır örtüşmesi) için "kalıba topla" uyarısı
  - `_` ile başlayan dosyalar (indeks/envanter) kontrol dışı, indeks ≤ 400 kelime

Kullanım: python3 scripts/analiz_dogrula.py [dizin] [--config yol] [--json]
Çıkış kodu: 1 = hata var, 0 = temiz (uyarılar çıkışı etkilemez).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as C  # noqa: E402

LEVEL_RE = re.compile(r"^\s*Seviye:\s*(L[12])\s*$", re.M | re.I)
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)
SOURCE_RE = re.compile(r"\[kaynak:\s*[^\]\s][^\]]*\]", re.I)
INDEX_MAX_WORDS = 400
SIMILARITY = 0.8


def words(text: str) -> int:
    return len(re.findall(r"\S+", text))


def sections(text: str) -> dict[str, str]:
    marks = list(SECTION_RE.finditer(text))
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out[m.group(1).strip().lower()] = text[m.end():end].strip()
    return out


def check_file(path: Path, acfg: dict) -> tuple[list[str], str | None]:
    """(hatalar, seviye) döndürür."""
    errs: list[str] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    lv = LEVEL_RE.search(text)
    level = lv.group(1).upper() if lv else None
    if not level:
        errs.append("'Seviye: L1|L2' satırı yok")
    cap = acfg["max_words_l2"] if level == "L2" else acfg["max_words_l1"]
    n = words(text)
    if n > cap:
        errs.append(f"{n} kelime > tavan {cap} ({level or 'L1'})")
    secs = sections(text)
    for field in acfg["template"]:
        body = secs.get(field.lower())
        if body is None:
            errs.append(f"şablon alanı eksik: '## {field}'")
            continue
        clean = body.strip().strip("`*_ ").lower()
        if not clean:
            errs.append(f"alan boş: '{field}' (değer yoksa 'bilinmiyor' yazılmalı)")
        elif clean != "bilinmiyor" and not SOURCE_RE.search(body):
            errs.append(f"kanıtsız alan: '{field}' ([kaynak: ...] işareti yok, 'bilinmiyor' da değil)")
    return errs, level


def _lines(text: str) -> set[str]:
    return {ln.strip().lower() for ln in text.splitlines()
            if len(ln.strip()) > 12 and not ln.lstrip().startswith(("#", "Seviye:"))}


def similar_pairs(files: dict[Path, str]) -> list[tuple[Path, Path, float]]:
    ls = {p: _lines(t) for p, t in files.items()}
    paths = list(ls)
    out = []
    for i, a in enumerate(paths):
        for b in paths[i + 1:]:
            if a.parent != b.parent:
                continue
            u = ls[a] | ls[b]
            if len(u) < 6:
                continue
            j = len(ls[a] & ls[b]) / len(u)
            if j >= SIMILARITY:
                out.append((a, b, round(j, 2)))
    return out


def validate_dir(root: Path, acfg: dict) -> dict:
    files = sorted(p for p in root.rglob("*.md") if not p.name.startswith("_"))
    report = {"files": len(files), "errors": {}, "warnings": [], "levels": {"L1": 0, "L2": 0}}
    texts = {}
    for p in files:
        errs, level = check_file(p, acfg)
        texts[p] = p.read_text(encoding="utf-8", errors="replace")
        if level in report["levels"]:
            report["levels"][level] += 1
        if errs:
            report["errors"][str(p.relative_to(root))] = errs
    l2 = report["levels"]["L2"]
    quota = min(acfg["l2_quota_max"], max(1, int(len(files) * acfg["l2_quota_pct"] / 100))) if files else 0
    if l2 > quota:
        report["errors"]["_kota"] = [f"L2 dosya sayısı {l2} > kota {quota} "
                                     f"(%{acfg['l2_quota_pct']}, max {acfg['l2_quota_max']})"]
    for a, b, j in similar_pairs(texts):
        report["warnings"].append(f"{a.name} ≈ {b.name} (benzerlik {j}): ortak kalıp dokümanına topla")
    idx = root / "_indeks.md"
    if idx.exists() and words(idx.read_text(encoding="utf-8", errors="replace")) > INDEX_MAX_WORDS:
        report["errors"]["_indeks.md"] = [f"indeks > {INDEX_MAX_WORDS} kelime"]
    return report


def marjinal_durak(yeni_bulgu_sayilari: list[int], k: int) -> bool:
    """Son k birimin hiçbirinde yeni bulgu yoksa True (derinleştirme durur)."""
    return k > 0 and len(yeni_bulgu_sayilari) >= k and not any(yeni_bulgu_sayilari[-k:])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dizin", nargs="?", default=None)
    ap.add_argument("--config", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    cfg = C.load_config(Path(a.config) if a.config else None) or C._merge(C.DEFAULTS, {})
    errs = C.validate_config(cfg)
    if errs:
        print("\n".join(f"[config] {e}" for e in errs), file=sys.stderr)
        return 1
    root = Path(a.dizin or (C.ROOT / cfg["analysis"]["output_dir"]))
    if not root.exists():
        print(f"[HATA] dizin yok: {root}", file=sys.stderr)
        return 1
    rep = validate_dir(root, cfg["analysis"])
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        print(f"{rep['files']} dosya, L1={rep['levels']['L1']} L2={rep['levels']['L2']}, "
              f"hatalı={len(rep['errors'])}, uyarı={len(rep['warnings'])}")
        for f, es in rep["errors"].items():
            for e in es:
                print(f"  ✗ {f}: {e}")
        for w in rep["warnings"]:
            print(f"  ! {w}")
    return 1 if rep["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
