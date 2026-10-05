"""Depo hijyeni aracı (issue #169)."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARAC = ROOT / "scripts" / "depo_hijyeni.py"


class DepoHijyeni(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.sh = lambda *a: subprocess.run(a, cwd=self.d, capture_output=True, text=True)
        self.sh("git", "init", "-q")
        for f in ("workspace/studio.db", "workspace/studio.db-wal", "workspace/logs/p.log", "workspace/docs/ekranlar/_ham/a.json",
                  "workspace/docs/ekranlar/_gorsel/a.png", "workspace/src/app.vue", "workspace/.trace/0001.json",
                  "workspace/.trace/index.jsonl", "workspace/pano_snapshot.json", "workspace/yerel_ortam.sh", "basla.sh", "studio_engine.py"):
            p = self.d / f
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x")
        (self.d / "studio.version").write_text(json.dumps({"tracked_files": ["basla.sh", "studio_engine.py"]}))
        self.sh("git", "add", "-f", "-A")

    def calistir(self):
        return subprocess.run([sys.executable, str(ARAC), "--uygula", "--kok", str(self.d)], capture_output=True, text=True)

    def test_artiklar_cikar_proje_dosyalari_kalir_idempotent(self):
        r = self.calistir()
        self.assertEqual(r.returncode, 0, r.stderr)
        izl = set(self.sh("git", "ls-files").stdout.split())
        for kalan in ("workspace/src/app.vue", "workspace/.trace/index.jsonl", "workspace/pano_snapshot.json", "workspace/yerel_ortam.sh"):
            self.assertIn(kalan, izl)                                          # projeye özel dosyalar izlenmeye devam eder
        for gitti in ("workspace/studio.db", "workspace/studio.db-wal", "workspace/logs/p.log", "workspace/docs/ekranlar/_ham/a.json",
                      "workspace/docs/ekranlar/_gorsel/a.png", "workspace/.trace/0001.json", "basla.sh", "studio_engine.py"):
            self.assertNotIn(gitti, izl)                                       # db/log/ham veri/görsel/trace ayrıntısı/framework çıktı
        self.assertEqual(self.sh("git", "check-ignore", "-q", "workspace/logs/new.log").returncode, 0)
        self.assertNotEqual(self.sh("git", "check-ignore", "-q", "workspace/src/new.vue").returncode, 0)
        ilk = (self.d / ".gitignore").read_text()
        self.calistir()
        self.assertEqual((self.d / ".gitignore").read_text(), ilk)             # ikinci çalıştırma değişiklik üretmez
        self.assertIn("*.sh text eol=lf", (self.d / ".gitattributes").read_text())

    def test_kullanici_satirlari_korunur(self):
        (self.d / ".gitignore").write_text("benim_satirim\n")
        self.calistir()
        self.assertIn("benim_satirim", (self.d / ".gitignore").read_text())


if __name__ == "__main__":
    unittest.main()
