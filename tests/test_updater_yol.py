"""studio_updater çerçeve yolu çözümü (issue #293)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import studio_updater as U  # noqa: E402


class Yol(unittest.TestCase):
    def test_env_ve_studio_version_oncelikli(self):
        with tempfile.TemporaryDirectory() as t:
            ds = Path(t) / "ds"
            ds.mkdir()
            (ds / "studio.version").write_text("{}", encoding="utf-8")
            with mock.patch.dict(os.environ, {"STUDIO_DS_PATH": str(ds)}), mock.patch.object(U, "DS_LOCAL_PATHS", []):
                self.assertEqual(U.ds_path_bul(), ds)
            vf = Path(t) / ".studio-version"
            vf.write_text(json.dumps({"ds_path": str(ds)}), encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=False), mock.patch.object(U, "LOCAL_VERSION_FILE", vf), mock.patch.object(U, "DS_LOCAL_PATHS", []):
                os.environ.pop("STUDIO_DS_PATH", None)
                self.assertEqual(U.ds_path_bul(), ds)

    def test_bulunamazsa_none(self):
        with mock.patch.object(U, "DS_LOCAL_PATHS", [Path("/yok/yok")]), mock.patch.dict(os.environ, {"STUDIO_DS_PATH": "/yok/yok2"}):
            self.assertIsNone(U.ds_path_bul())


if __name__ == "__main__":
    unittest.main()
