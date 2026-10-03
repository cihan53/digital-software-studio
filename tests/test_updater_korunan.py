"""studio_updater.korunan_dosyalar / local_version_kaydet testleri (issue #126)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import studio_updater as U  # noqa: E402


class KorunanDosyalar(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.f = Path(self.tmp.name) / ".studio-version"
        self._eski = U.LOCAL_VERSION_FILE
        U.LOCAL_VERSION_FILE = self.f

    def tearDown(self):
        U.LOCAL_VERSION_FILE = self._eski
        self.tmp.cleanup()

    def test_ds_ve_yerel_birlesir(self):
        self.f.write_text(json.dumps({"version": "1", "protected_files": ["a.py"]}))
        self.assertEqual(U.korunan_dosyalar({"protected_files": ["b.py"]}), {"a.py", "b.py"})

    def test_yerel_yoksa_yalniz_ds(self):
        self.assertEqual(U.korunan_dosyalar({"protected_files": ["b.py"]}), {"b.py"})

    def test_kaydet_korunani_siler_mi(self):
        self.f.write_text(json.dumps({"version": "1", "protected_files": ["a.py"]}))
        U.local_version_kaydet("2", "/x")
        self.assertEqual(json.loads(self.f.read_text())["protected_files"], ["a.py"])


if __name__ == "__main__":
    unittest.main()
