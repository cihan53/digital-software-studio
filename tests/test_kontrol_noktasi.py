"""Kontrol noktası: commit + etiket + push (issue #275)."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import kontrol_noktasi as KN  # noqa: E402


def git(d, *a):
    return subprocess.run(["git", *a], cwd=d, capture_output=True, text=True)


class Kontrol(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.uzak = self.tmp / "uzak.git"
        git(self.tmp, "init", "-q", "--bare", str(self.uzak))
        self.p = self.tmp / "proje"
        self.p.mkdir()
        git(self.p, "init", "-q", "-b", "studio/calisma")
        git(self.p, "config", "user.email", "t@t")
        git(self.p, "config", "user.name", "t")
        (self.p / "workspace").mkdir()
        (self.p / "workspace/studio.config.json").write_text("{}", encoding="utf-8")
        (self.p / "brief.md").write_text("v1", encoding="utf-8")
        git(self.p, "add", "-A")
        git(self.p, "commit", "-q", "-m", "ilk")
        git(self.p, "remote", "add", "origin", str(self.uzak))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_commit_etiket_ve_push(self):
        (self.p / "brief.md").write_text("v2 kararlar", encoding="utf-8")
        e = KN.olustur("brief-karari", "t", self.p)
        self.assertTrue(e and e.startswith("kontrol/brief-karari-"))
        self.assertEqual(git(self.p, "status", "--porcelain").stdout.strip(), "")
        self.assertIn(e, git(self.uzak, "tag", "--list").stdout)
        self.assertIn("studio/calisma", git(self.uzak, "branch", "--list").stdout)
        self.assertTrue(KN.var_mi("brief-karari", self.p))

    def test_yoksa_olustur_tekrarlamaz(self):
        self.assertIsNotNone(KN.yoksa_olustur("brief-karari", "", self.p))
        self.assertIsNone(KN.yoksa_olustur("brief-karari", "", self.p))

    def test_ana_dalda_ve_proje_disinda_noop(self):
        git(self.p, "checkout", "-q", "-b", "main")
        self.assertIsNone(KN.olustur("x", "", self.p))
        git(self.p, "checkout", "-q", "studio/calisma")
        (self.p / "workspace/studio.config.json").unlink()
        self.assertIsNone(KN.olustur("x", "", self.p))

    def test_uzak_yoksa_yerel_etiket(self):
        git(self.p, "remote", "remove", "origin")
        self.assertIsNotNone(KN.olustur("a", "", self.p))


if __name__ == "__main__":
    unittest.main()
