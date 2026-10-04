#!/usr/bin/env python3
"""Korumalı dosya kapısı (issue #141): sözleşme guard dosyaları bir görev tarafından değiştirildiyse hata.

Keşif rolü gezgini genişletebilir ama izin sözleşmesini (kesif_denetle.py, studio_config.py) gevşetemez.
Git'te (çalışma ağacı + indeks) değişmiş korumalı dosya varsa çıkış kodu 1.
  python3 scripts/koruma_kontrol.py [--taban HEAD] [--dosyalar a,b]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KORUMALI = ["scripts/kesif_denetle.py", "scripts/studio_config.py", "scripts/koruma_kontrol.py", "scripts/insan_onayi.py"]


def degisenler(taban: str, dosyalar: list[str]) -> list[str]:
    r = subprocess.run(["git", "diff", "--name-only", taban, "--", *dosyalar], cwd=ROOT, capture_output=True, text=True)
    return [x for x in r.stdout.splitlines() if x]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--taban", default="HEAD")
    ap.add_argument("--dosyalar", default=None)
    a = ap.parse_args(argv)
    d = degisenler(a.taban, a.dosyalar.split(",") if a.dosyalar else KORUMALI)
    if d:
        print("[KORUMA] sözleşme dosyaları değiştirilmiş (görev bunları değiştiremez): " + ", ".join(d))
        return 1
    print("korumalı dosyalar değişmedi")
    return 0


if __name__ == "__main__":
    sys.exit(main())
