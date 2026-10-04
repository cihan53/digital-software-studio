#!/usr/bin/env python3
"""Studio yetenek/ortam kontrolü (issue #141) — deterministik, LLM'siz.

Bir görevin ihtiyaç duyduğu araçların hazır olup olmadığını ölçer; eksik varsa ne gerektiğini ve bunun
İNSAN adımı (indirme, giriş, onay) olup olmadığını söyler. Studio kendiliğinden indirme/kurulum yapmaz:
indirme gerektiren eksikler için insan kapısı (role: human) önerilir.

  python3 scripts/yetenek_kontrol.py                       # hepsini ölç
  python3 scripts/yetenek_kontrol.py --ihtiyac node22,chrome,kesif-profili --json
Çıkış kodu: 1 = istenen yeteneklerden biri eksik.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as C  # noqa: E402

CHROME = os.environ.get("CHROME_PATH", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def _ver(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return (r.stdout or r.stderr).strip().splitlines()[0] if (r.stdout or r.stderr).strip() else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def k_node22() -> dict:
    v = _ver(["node", "-v"])
    m = re.match(r"v(\d+)", v)
    ok = bool(m and int(m.group(1)) >= 22)
    return {"ok": ok, "detay": v or "node yok", "gerekli": None if ok else "Node >= 22 (nvm install 22)", "insan": not ok}


def k_python3() -> dict:
    v = _ver(["python3", "--version"])
    return {"ok": bool(v), "detay": v or "python3 yok", "gerekli": None if v else "python3", "insan": not v}


def k_git() -> dict:
    v = _ver(["git", "--version"])
    return {"ok": bool(v), "detay": v or "git yok", "gerekli": None if v else "git", "insan": not v}


def k_pnpm() -> dict:
    v = _ver(["pnpm", "-v"])
    return {"ok": bool(v), "detay": v or "pnpm yok", "gerekli": None if v else "corepack enable && corepack prepare pnpm@latest --activate", "insan": not v}


def k_chrome() -> dict:
    ok = Path(CHROME).exists()
    return {"ok": ok, "detay": CHROME if ok else "Chrome bulunamadı", "gerekli": None if ok else "Google Chrome kur veya CHROME_PATH ayarla", "insan": not ok}


def k_kesif_profili() -> dict:
    """Keşif Chrome profili hedefte oturum açık mı? Gerçek yoklama: gezgin --oturum-kontrol (headless).
    (Oturum çerez yerine localStorage'da olabilir; çerez DB'sine bakmak yanlış alarm verir.)"""
    prof = Path(os.environ.get("STUDIO_KESIF_PROFIL") or ROOT / "workspace" / ".kesif_profil")
    gerekli = "`node scripts/kesif_gezgin.mjs --login` (kullanıcı bir kez giriş yapar)"
    if not prof.exists():
        return {"ok": False, "detay": f"profil yok: {prof}", "gerekli": gerekli, "insan": True}
    if not shutil.which("node") or not Path(CHROME).exists():
        return {"ok": False, "detay": "node veya Chrome yok, oturum yoklanamadı", "gerekli": "önce node22 ve chrome", "insan": True}
    try:
        r = subprocess.run(["node", "scripts/kesif_gezgin.mjs", "--oturum-kontrol"], cwd=ROOT, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired:
        return {"ok": False, "detay": "oturum yoklaması zaman aşımı", "gerekli": "Chrome açık mı / profil kilitli mi kontrol et", "insan": True}
    ok = r.returncode == 0
    return {"ok": ok, "detay": (r.stdout.strip() or r.stderr.strip())[:120], "gerekli": None if ok else gerekli, "insan": not ok}


YETENEKLER = {"node22": k_node22, "python3": k_python3, "git": k_git, "pnpm": k_pnpm, "chrome": k_chrome, "kesif-profili": k_kesif_profili}


def olc(ihtiyac: list[str] | None = None) -> dict:
    ad = ihtiyac or list(YETENEKLER)
    out = {}
    for a in ad:
        f = YETENEKLER.get(a)
        out[a] = f() if f else {"ok": False, "detay": "bilinmeyen yetenek", "gerekli": f"yetenek tanımı yok: {a}", "insan": False}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ihtiyac", default=None, help="virgülle: " + ",".join(YETENEKLER))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    r = olc(a.ihtiyac.split(",") if a.ihtiyac else None)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        for k, v in r.items():
            print(f"{'✓' if v['ok'] else '✗'} {k:14} {v['detay']}" + (f"  → {v['gerekli']}" + (" [İNSAN ADIMI]" if v["insan"] else "") if not v["ok"] else ""))
    return 0 if all(v["ok"] for v in r.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
