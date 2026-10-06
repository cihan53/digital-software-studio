"""basla.sh --surdur / --duraklat: devre kesici mesajının önerdiği komut gerçekten var (issue #221)."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class BaslaSurdur(unittest.TestCase):
    def test_duraklat_ve_surdur(self):
        d = Path(tempfile.mkdtemp())
        for f in ("basla.sh", "studio_board.py"):
            shutil.copy2(ROOT / f, d / f)
        (d / "workspace").mkdir()

        def calis(arg):
            return subprocess.run(["bash", "basla.sh", arg], cwd=d, capture_output=True, text=True, timeout=60)
        self.assertEqual(calis("--duraklat").returncode, 0)
        self.assertTrue((d / "workspace/.control/pause").exists())
        r = calis("--surdur")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((d / "workspace/.control/pause").exists())
        self.assertIn("Duraklatma kaldırıldı", r.stdout)

    def test_devre_kesici_mesaji_komutu_gosteriyor(self):
        self.assertIn("--surdur", (ROOT / "studio_engine.py").read_text(encoding="utf-8"))
        self.assertIn("--surdur)", (ROOT / "basla.sh").read_text(encoding="utf-8").replace("--surdur|", "--surdur)"))


if __name__ == "__main__":
    unittest.main()
