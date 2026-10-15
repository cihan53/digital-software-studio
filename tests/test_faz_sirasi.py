"""Faz sırası sayısal; ilerletme ilk bekleyen fazı seçer, hiçbiri atlanmaz (issue #307)."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import studio_board as B  # noqa: E402
import karar_verici_triage as KVT  # noqa: E402
import faz_planla as FP  # noqa: E402


def T(i, st):
    return {"id": i, "title": i, "description": "", "role": "web_engineer", "phase": "develop", "outputs": ["workspace/x"],
            "depends_on": [], "status": st, "note": "", "talep_id": None, "order": 0, "priority": 0}


class FazSirasi(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.eski = (B.DB_PATH, KVT.FAZLAR_FILE)
        B.DB_PATH = self.tmp / "t.db"
        KVT.FAZLAR_FILE = self.tmp / "fazlar.json"
        (self.tmp / "workspace/docs/faz_planlari").mkdir(parents=True)

    def tearDown(self):
        B.DB_PATH, KVT.FAZLAR_FILE = self.eski
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fazlar(self, durumlar):
        KVT.save_fazlar({"fazlar": [{"id": f"FAZ-{n}", "ad": f"f{n}", "durum": d, "kilitli": d != "AKTIF"} for n, d in durumlar.items()]})

    def test_sayisal_sira(self):
        self.fazlar({1: "TAMAMLANDI", 2: "PLANLANDI", 10: "PLANLANDI", 3: "PLANLANDI", 11: "PLANLANDI", 20: "PLANLANDI", 4: "AKTIF"})
        self.assertEqual([f["id"] for f in KVT.load_fazlar()["fazlar"]], ["FAZ-1", "FAZ-2", "FAZ-3", "FAZ-4", "FAZ-10", "FAZ-11", "FAZ-20"])
        self.assertLess(KVT.faz_sirasi("FAZ-2"), KVT.faz_sirasi("FAZ-10"))
        self.assertLess(KVT.faz_sirasi("FAZ-99"), KVT.faz_sirasi("OZEL"))

    def test_ilerlet_ilk_bekleyen_fazi_secer(self):
        # eski hata: liste metin sırasıydı ve 'sıradaki' FAZ-1 → FAZ-10 oldu; FAZ-2..9 atlanıyordu
        self.fazlar({1: "AKTIF", 2: "PLANLANDI", 3: "PLANLANDI", 10: "PLANLANDI", 11: "PLANLANDI"})
        self.assertTrue(KVT.faz_ilerlet())
        self.assertEqual({f["id"]: f["durum"] for f in KVT.load_fazlar()["fazlar"]}["FAZ-2"], "AKTIF")

    def test_atlanmis_bekleyen_faz_sonradan_da_secilir(self):
        self.fazlar({1: "TAMAMLANDI", 2: "PLANLANDI", 3: "PLANLANDI", 10: "AKTIF", 11: "PLANLANDI"})        # FAZ-10 öne geçmiş (eski hata sonucu)
        self.assertTrue(KVT.faz_ilerlet())
        d = {f["id"]: f["durum"] for f in KVT.load_fazlar()["fazlar"]}
        self.assertEqual((d["FAZ-10"], d["FAZ-2"], d["FAZ-11"]), ("TAMAMLANDI", "AKTIF", "PLANLANDI"))

    def test_son_fazda_ilerletilmez(self):
        self.fazlar({1: "TAMAMLANDI", 2: "AKTIF"})
        self.assertFalse(KVT.faz_ilerlet())

    def test_otomatik_ilerlet_siradaki_fazi_dondurur(self):
        self.fazlar({1: "TAMAMLANDI", 2: "PLANLANDI", 10: "AKTIF", 11: "PLANLANDI"})
        (self.tmp / "workspace/docs/faz_planlari/FAZ-10.uygulandi").write_text("1", encoding="utf-8")
        board = B.normalize({"sprints": [{"id": "S1", "name": "s", "order": 0, "tasks": [T("S1-T1", B.DONE)]}]})
        self.assertEqual(FP.otomatik_ilerlet(board, self.tmp), "FAZ-2")


if __name__ == "__main__":
    unittest.main()
