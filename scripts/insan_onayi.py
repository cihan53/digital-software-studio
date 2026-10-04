#!/usr/bin/env python3
"""İnsan onay kapıları (role: human) için liste / onay / ret (issue #136).

Koşucu `role: human` görevlerini ASLA çalıştırmaz. Bağımlılıkları bitince görev READY'de bekler;
bu betikle bir insan onaylar (DONE) ya da reddeder. Onay kaydı görevin ilk `.md` çıktısına yazılır
(kim, ne zaman, karar, not) ve audit_log'a düşer; model onay üretemez.

  python3 scripts/insan_onayi.py list
  python3 scripts/insan_onayi.py approve S2-G1 --not "Tasarımlar uygundur"  [--kim "Ad"] [--force]
  python3 scripts/insan_onayi.py reject  S2-G1 --not "PageHeader filtreleri eksik"
"""
from __future__ import annotations

import argparse
import getpass
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import studio_board as B  # noqa: E402


def kim_mi() -> str:
    try:
        g = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    except OSError:
        g = ""
    return g or os.environ.get("USER") or getpass.getuser()


def kayit_yolu(task: dict) -> Path:
    md = next((o for o in task.get("outputs", []) if o.endswith(".md")), None)
    return ROOT / (md or f"workspace/docs/onaylar/{task['id']}.md")


def kayit_yaz(task: dict, karar: str, kim: str, not_: str) -> Path:
    p = kayit_yolu(task)
    p.parent.mkdir(parents=True, exist_ok=True)
    yeni = not p.exists()
    with p.open("a", encoding="utf-8") as f:
        if yeni:
            f.write(f"# İnsan Onay Kaydı — {task['id']} {task['title']}\n\n> {task.get('description', '')}\n")
        f.write(f"\n## {datetime.now():%Y-%m-%d %H:%M} — {karar}\n- Karar veren: {kim}\n- Not: {not_ or '-'}\n")
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("list")
    for c in ("approve", "reject"):
        x = sp.add_parser(c)
        x.add_argument("id")
        x.add_argument("--not", dest="not_", default="")
        x.add_argument("--kim", default=None)
        x.add_argument("--force", action="store_true", help="bağımlılıklar bitmeden de onayla")
    a = ap.parse_args(argv)
    board = B.load()
    B.refresh(board)
    if a.cmd == "list":
        gk = [(s, t) for s, t in B.all_tasks(board) if B.is_human(t) and t["status"] != B.DONE]
        if not gk:
            print("Bekleyen insan onay kapısı yok.")
        for s, t in gk:
            print(f"{t['id']:10} {t['status']:8} {s['id']} · {t['title']}")
        return 0
    s, t = B.find_task(board, a.id)
    if t is None or not B.is_human(t):
        print(f"[HATA] '{a.id}' bir insan onay görevi değil.", file=sys.stderr)
        return 1
    if t["status"] != B.READY and not a.force:
        print(f"[HATA] '{a.id}' henüz hazır değil (durum {t['status']}): bağımlı görevler bitmeli. --force ile geçilebilir.", file=sys.stderr)
        return 1
    kim = a.kim or kim_mi()
    if a.cmd == "reject" and not a.not_:
        print("[HATA] ret için --not (gerekçe) zorunlu.", file=sys.stderr)
        return 1
    karar = "ONAYLANDI" if a.cmd == "approve" else "REDDEDİLDİ"
    yol = kayit_yaz(t, karar, kim, a.not_)
    if a.cmd == "approve":
        B.mark(board, a.id, B.DONE, f"insan onayı: {kim}")
    else:
        B.mark(board, a.id, B.READY, f"REDDEDİLDİ ({kim}): {a.not_}")
    B.save(board)
    B.audit("insan", "onay" if a.cmd == "approve" else "ret", gorev_id=a.id, detay={"kim": kim, "not": a.not_})
    print(f"{a.id}: {karar} ({kim}) → {yol.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
