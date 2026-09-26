#!/usr/bin/env python3
"""
scripts/release_bump.py
Digital Software Studio — sürüm yükseltici (CI release workflow'u kullanır).

Kullanım:
  python3 scripts/release_bump.py patch|minor|major [--msg "changelog satırı"]

Davranış:
  - studio.version'daki 'version' alanını semver'e göre yükseltir
  - 'released' tarihini bugüne alır
  - changelog başına yeni kayıt ekler (--msg varsa tek 'changes' satırı olur)
  - Yeni sürümü stdout'a basar (CI bunu tag adı olarak kullanır)

Dal değiştirme/commit/tag bu scriptin işi değildir — release.yml yapar.
"""

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VFILE = ROOT / "studio.version"


def bump(v: str, part: str) -> str:
    try:
        a, b, c = (list(map(int, str(v).split("."))) + [0, 0, 0])[:3]
    except ValueError:
        a, b, c = 0, 0, 0
    if part == "major":
        return f"{a + 1}.0.0"
    if part == "minor":
        return f"{a}.{b + 1}.0"
    return f"{a}.{b}.{c + 1}"


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    part = args[0] if args and args[0] in ("patch", "minor", "major") else "patch"
    msg = ""
    if "--msg" in sys.argv:
        i = sys.argv.index("--msg")
        msg = sys.argv[i + 1].strip() if i + 1 < len(sys.argv) else ""

    if not VFILE.exists():
        print(f"studio.version bulunamadı: {VFILE}", file=sys.stderr)
        return 1

    d = json.loads(VFILE.read_text(encoding="utf-8"))
    yeni = bump(d.get("version", "0.0.0"), part)
    d["version"] = yeni
    d["released"] = date.today().isoformat()
    d.setdefault("changelog", []).insert(0, {
        "version": yeni,
        "date": d["released"],
        "changes": [msg] if msg else [],
    })
    VFILE.write_text(
        json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(yeni)
    return 0


if __name__ == "__main__":
    sys.exit(main())
