#!/usr/bin/env python3
"""Depo hijyeni (issue #169): yalıtım modeline uygun .gitignore/.gitattributes yönetilen blokları + izlenen artıkların temizliği.

  python3 scripts/depo_hijyeni.py            # durumu raporla (yazmaz)
  python3 scripts/depo_hijyeni.py --uygula   # blokları yaz/güncelle, izlenen artıkları `git rm --cached` ile çıkar

Yönetilen bloklar `# >>> studio ... <<< studio` işaretleriyle sınırlanır; dışındaki satırlara dokunulmaz, idempotenttir.
Kök yalnızca framework + .studio-version; projeye özel her şey workspace/ altındadır (AGENTS.md yalıtım kuralı).
`git_auto_commit` `git add -A` kullandığından hijyenin tamamı bu beyaz listeye bağlıdır.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BAS, SON = "# >>> studio (otomatik yönetilen blok; dışına yazın) >>>", "# <<< studio <<<"

GITIGNORE = f"""{BAS}
# Kök: yalnız framework (sync ile gelir) + .studio-version. Projeye özel her şey workspace/ altında.
/*
!/.gitignore
!/.gitattributes
!/.studio-version
!/workspace/
workspace/*
!/workspace/docs/
!/workspace/src/
!/workspace/scripts/
!/workspace/tests/
!/workspace/infra/
!/workspace/mock/
!/workspace/.history/
!/workspace/.trace/
!/workspace/.state.json
!/workspace/studio.config.json
!/workspace/pano_snapshot.json
!/workspace/yerel_ortam.sh
!/workspace/ci_cd_pipeline.yml
!/workspace/build_checklist.json
!/workspace/smoke_checklist.json
# Çalışma zamanı / yerel / kişisel veri içerebilen: git'e girmez
workspace/studio.db*
workspace/logs/
workspace/.yedek/
workspace/.stale/
workspace/.kesif_profil/
workspace/.control/
workspace/.scratch/
workspace/.lock
workspace/.web.pid
workspace/.trace/*
!workspace/.trace/index.jsonl
workspace/docs/ekranlar/_ham/
workspace/docs/ekranlar/_gorsel/
node_modules/
dist/
.nuxt/
.output/
.DS_Store
__pycache__/
{SON}
"""

GITATTRIBUTES = f"""{BAS}
# Betikler her ortamda LF kalır (core.autocrlf=true shebang satırını bozar: env: bash\\r)
*.sh text eol=lf
*.py text eol=lf
*.mjs text eol=lf
*.js text eol=lf
{SON}
"""

# İzlenmemesi gereken yollar (git ls-files desenleri)
ARTIK = [r"^workspace/studio\.db", r"^workspace/logs/", r"^workspace/docs/ekranlar/_ham/", r"^workspace/docs/ekranlar/_gorsel/",
         r"^workspace/\.yedek/", r"^workspace/\.stale/", r"^workspace/\.kesif_profil/", r"^workspace/\.trace/(?!index\.jsonl)",
         r"(^|/)node_modules/", r"(^|/)__pycache__/", r"(^|/)\.DS_Store$"]


def blok_yaz(yol: Path, blok: str) -> bool:
    """Yönetilen bloğu ekler/günceller. Değişiklik olduysa True."""
    mevcut = yol.read_text(encoding="utf-8") if yol.exists() else ""
    desen = re.compile(re.escape(BAS) + r".*?" + re.escape(SON) + r"\n?", re.S)
    yeni = desen.sub(blok, mevcut, count=1) if desen.search(mevcut) else (mevcut.rstrip("\n") + "\n\n" if mevcut.strip() else "") + blok
    if yeni == mevcut:
        return False
    yol.write_text(yeni, encoding="utf-8")
    return True


def framework_dosyalari(kok: Path) -> set[str]:
    """studio.version tracked_files: framework dosyaları sync ile gelir, proje reposunda izlenmemeli."""
    try:
        return set(json.loads((kok / "studio.version").read_text(encoding="utf-8")).get("tracked_files", []))
    except (OSError, ValueError):
        return set()


def izlenen_artiklar(kok: Path) -> list[str]:
    r = subprocess.run(["git", "ls-files"], cwd=kok, capture_output=True, text=True)
    if r.returncode != 0:
        return []
    rx = [re.compile(p) for p in ARTIK]
    fw = framework_dosyalari(kok)
    return [f for f in r.stdout.splitlines() if any(x.search(f) for x in rx) or f in fw]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--uygula", action="store_true")
    ap.add_argument("--kok", default=str(ROOT))
    a = ap.parse_args(argv)
    kok = Path(a.kok)
    art = izlenen_artiklar(kok)
    print(f".gitignore yönetilen blok: {'güncel' if blok_yaz_kuru(kok / '.gitignore', GITIGNORE) else 'GÜNCELLENECEK'}")
    print(f".gitattributes yönetilen blok: {'güncel' if blok_yaz_kuru(kok / '.gitattributes', GITATTRIBUTES) else 'GÜNCELLENECEK'}")
    print(f"izlenen artık dosya: {len(art)}" + ("" if not art else " (örn. " + ", ".join(art[:3]) + ")"))
    if not a.uygula:
        return 0
    blok_yaz(kok / ".gitignore", GITIGNORE)
    blok_yaz(kok / ".gitattributes", GITATTRIBUTES)
    for i in range(0, len(art), 200):
        subprocess.run(["git", "rm", "-r", "-q", "--cached", "--ignore-unmatch", *art[i:i + 200]], cwd=kok)
    print("uygulandı." + (f" {len(art)} artık dosya takipten çıkarıldı (diskte duruyor; commit'leyin)." if art else ""))
    return 0


def blok_yaz_kuru(yol: Path, blok: str) -> bool:
    """Blok zaten güncel mi?"""
    mevcut = yol.read_text(encoding="utf-8") if yol.exists() else ""
    return blok in mevcut


if __name__ == "__main__":
    sys.exit(main())
