"""İlk kez oluşan workspace/src dizini 'kaynak değişmedi' sayılmamalı (issue #189)."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import kalite_kapilari as K


class KaynakKapisi(unittest.TestCase):
    def test_yeni_src_dizini_gercek_kaynak_sayilir(self):
        d = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q"], cwd=d, check=True)
        subprocess.run(["git", "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "i"], cwd=d, check=True)
        eski = K.ROOT
        try:
            K.ROOT = d
            oncesi = K.porcelain_snapshot()
            (d / "workspace/src/web/app").mkdir(parents=True)
            (d / "workspace/src/web/app/app.vue").write_text("<template/>")
            dosyalar = K.changed_files_since(oncesi)
            self.assertIn("workspace/src/web/app/app.vue", dosyalar)                 # dizin tek satıra çökmez
            gorev = {"phase": "develop", "outputs": ["workspace/src/web/app/app.vue"]}
            self.assertIs(K.kaynak_degisti_mi(gorev, dosyalar), True)
        finally:
            K.ROOT = eski


if __name__ == "__main__":
    unittest.main()
