#!/usr/bin/env python3
"""Pano anlık görüntüsü (studio.db git'te takip edilmez; bu JSON takip edilir).

  python3 scripts/pano_snapshot.py export     # workspace/pano_snapshot.json (okunabilir, merge edilebilir)
  python3 scripts/pano_snapshot.py import     # snapshot'tan panoyu geri yükler (mevcut panoyu yedekleyip)
  python3 scripts/pano_snapshot.py yedek      # workspace/.yedek/ altına SQLite yedeği (son 10)
"""
import json, shutil, sqlite3, sys
from datetime import datetime
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import studio_board as B  # noqa: E402

SNAP = ROOT / "workspace" / "pano_snapshot.json"
YEDEK = ROOT / "workspace" / ".yedek"


def yedek() -> Path:
    YEDEK.mkdir(parents=True, exist_ok=True)
    hedef = YEDEK / f"studio.db.{datetime.now():%Y%m%d-%H%M%S}"
    src = sqlite3.connect(B.DB_PATH)
    dst = sqlite3.connect(hedef)
    src.backup(dst)
    dst.close(); src.close()
    eski = sorted(YEDEK.glob("studio.db.2*"))
    for p in eski[:-10]:
        p.unlink()
    return hedef


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "export":
        b = B.load()
        SNAP.write_text(json.dumps(b, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        print(f"{len(b['sprints'])} sprint, {sum(len(s['tasks']) for s in b['sprints'])} görev → {SNAP.relative_to(ROOT)}")
    elif cmd == "import":
        if not SNAP.exists():
            print("snapshot yok", file=sys.stderr); return 1
        print("mevcut pano yedeği:", yedek().name)
        B.board_reset()
        B.save(json.loads(SNAP.read_text(encoding="utf-8")))
        print("pano snapshot'tan yüklendi")
    elif cmd == "yedek":
        print(yedek())
    else:
        print(__doc__); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
