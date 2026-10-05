"""Telafiye devredilen SKIPPED görev semantiği (issue #167)."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import studio_board as B  # noqa: E402


def T(i, st, dep=(), note="", talep=None, order=0):
    return {"id": i, "title": i, "description": "", "role": "web_engineer", "phase": "develop", "outputs": ["workspace/x"],
            "depends_on": list(dep), "status": st, "note": note, "talep_id": talep, "order": order, "priority": 0}


def pano(b_note):
    return {"sprints": [
        {"id": "S1", "name": "s1", "order": 0, "status": B.TODO, "tasks": [
            T("A", B.DONE), T("B", B.SKIPPED, ["A"], b_note, order=1), T("C", B.TODO, ["B"], order=2), T("Q", B.TODO, ["C"], order=3)]},
        {"id": "S2", "name": "s2", "order": 1, "status": B.TODO, "tasks": [T("R", B.TODO, [], talep="TALEP-1")]}]}


class TelafiSemantigi(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.eski = B.DB_PATH
        B.DB_PATH = self.tmp / "t.db"
        c = B.db_conn()
        c.execute("INSERT INTO talepler (id, baslik, durum) VALUES ('TALEP-1', 'telafi', 'GELISTIRILIYOR')")
        c.commit()
        c.close()

    def tearDown(self):
        B.DB_PATH = self.eski
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _durum(self, b, tid):
        return B.find_task(b, tid)[1]["status"]

    def test_telafi_bekleyen_skip_bagimlilari_durdurur_ama_telafi_calisir(self):
        b = B.normalize(pano("derleme başarısız (1); telafi TALEP-1 talebine devredildi"))
        B.refresh(b)
        self.assertEqual(self._durum(b, "C"), B.TODO)                      # temel yok: bağımlı başlamaz
        self.assertEqual(self._durum(b, "Q"), B.TODO)                      # parite testi boşuna DONE olmaz
        self.assertEqual(B.find_sprint(b, "S1")["status"] if hasattr(B, "find_sprint") else b["sprints"][0]["status"], B.BLOCKED)
        self.assertEqual(self._durum(b, "R"), B.READY)                     # telafi görevi sprint sırasını atlar
        s, t = B.next_ready(b)
        self.assertEqual((s["id"], t["id"]), ("S2", "R"))                  # ve koşucu onu seçer (kilitlenme yok)

    def test_talep_cozulunce_bagimlilar_acilir(self):
        b = B.normalize(pano("telafi TALEP-1 talebine devredildi"))
        c = B.db_conn()
        c.execute("UPDATE talepler SET durum='COZULDU' WHERE id='TALEP-1'")
        c.commit()
        c.close()
        B.refresh(b)
        self.assertEqual(self._durum(b, "R"), B.DONE)                      # çözülen talebin görevi kapanır
        self.assertEqual(self._durum(b, "C"), B.READY)                     # bağımlı artık başlayabilir

    def test_kullanici_atlamasi_ve_notsuz_skip_eskisi_gibi(self):
        for note in ("kullanıcı atladı", "", "talep iptal edildi"):
            b = B.normalize(pano(note))
            B.refresh(b)
            self.assertEqual(self._durum(b, "C"), B.READY, note)           # bilerek atlanan görev bağımlıyı engellemez


if __name__ == "__main__":
    unittest.main()
