"""Gözlem paneli: neden beklediği, etkinlik akışı, görev değişikliği (v2, issue #259)."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import studio_board as B  # noqa: E402
import gozlem as GO  # noqa: E402


def T(i, st, role="web_engineer", title="", dep=()):
    return {"id": i, "title": title or i, "description": "", "role": role, "phase": "develop", "outputs": ["workspace/x"],
            "depends_on": list(dep), "status": st, "note": "", "talep_id": None, "order": 0, "priority": 0}


def pano(*tasks):
    b = B.normalize({"sprints": [{"id": "S1", "name": "s", "order": 0, "tasks": list(tasks)}]})
    B.refresh(b)
    return b


CTRL = {"paused": False, "stopping": False}


class BeklemeNedeni(unittest.TestCase):
    def n(self, board, **k):
        a = dict(ctrl=CTRL, kosucu=True, onay_bekliyor=None, canli={3000: True}, canli_baslatilabilir=True, log="", cur={})
        a.update(k)
        return GO.bekleme_nedeni(board, **a)

    def test_oncelik_siralari(self):
        b = pano(T("A", B.TODO))
        self.assertEqual(self.n(b, ctrl={"paused": True, "stopping": False})["kod"], "duraklatildi")
        self.assertEqual(self.n(b, ctrl={"paused": False, "stopping": True})["kod"], "durduruluyor")
        self.assertEqual(self.n(b, onay_bekliyor={"gorev": 3, "sinir_gorev": 3, "maliyet": 1, "sinir_butce": 2, "sonraki": "A"})["kod"], "kota_onayi")
        self.assertEqual(self.n(b, kosucu=False)["kod"], "kosucu_yok")

    def test_kimlik_hatasi_kota_degil(self):
        n = self.n(pano(T("A", B.TODO)), log="... Failed to authenticate: OAuth session expired and could not be refreshed")
        self.assertEqual(n["kod"], "kimlik")
        self.assertIn("kota değil", n["mesaj"])

    def test_canli_kapali_uat_icin(self):
        b = pano(T("U", B.TODO, role="uat_auditor"))
        n = self.n(b, canli={3000: False})
        self.assertEqual(n["kod"], "canli_kapali")
        self.assertIn("3000", n["mesaj"])
        self.assertEqual(self.n(b, canli={3000: True})["kod"], "baslamak_uzere")

    def test_calisan_varsa_neden_yok(self):
        b = pano(T("A", B.TODO))
        b["sprints"][0]["tasks"][0]["status"] = B.RUNNING
        self.assertIsNone(self.n(b))

    def test_insan_onayi_ve_bitti(self):
        b = pano(T("H", B.TODO, role="human"))
        self.assertEqual(self.n(b)["kod"], "insan_onayi")
        self.assertEqual(self.n(pano(T("A", B.DONE)))["kod"], "bitti")

    def test_telafi_bekliyor(self):
        a = T("A", B.SKIPPED)
        a["note"] = "kaynak uygulanmadı; telafi TALEP-1 talebine devredildi"
        b = pano(a, T("B", B.TODO, dep=["A"]))
        b["sprints"][0]["tasks"][1]["status"] = B.TODO
        n = self.n(b)
        self.assertIn(n["kod"], ("telafi_bekliyor", "bagimlilik", "bloke"))


class AkisVeDegisiklik(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.eski = B.DB_PATH
        B.DB_PATH = self.tmp / "t.db"

    def tearDown(self):
        B.DB_PATH = self.eski
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_arac_olayi_akista_gorunur_ve_filtrelenir(self):
        GO.arac_olayi("Edit", '{"file_path": "a.ts"}', "S1-T1", "web_engineer")
        GO.arac_olayi("Bash", '{"command": "pnpm test"}', "S1-T2")
        B.audit("engine", "gorev_durum", gorev_id="S1-T1", detay={"durum": "DONE"})
        hepsi = GO.akis(50)
        self.assertEqual(len(hepsi), 3)
        s1 = GO.akis(50, gorev="S1-T1")
        self.assertEqual({r["olay"] for r in s1}, {"arac_cagrisi", "gorev_durum"})
        self.assertIn("a.ts", s1[-1]["ozet"] + s1[0]["ozet"])
        self.assertEqual(len(GO.akis(50, olay="arac_cagrisi")), 2)

    def test_degisiklik_gorev_commitinden(self):
        r = self.tmp / "repo"
        r.mkdir()
        g = lambda *a: subprocess.run(["git", *a], cwd=r, capture_output=True, text=True, check=True)
        g("init", "-q")
        g("config", "user.email", "t@t")
        g("config", "user.name", "t")
        (r / "a.txt").write_text("1\n")
        g("add", ".")
        g("commit", "-q", "-m", "ilk")
        (r / "a.txt").write_text("1\n2\n")
        g("commit", "-qam", "studio: görev DONE — S1-T1")
        d = GO.degisiklik("S1-T1", r)
        self.assertTrue(d["ok"])
        self.assertEqual(d["kaynak"], "commit")
        self.assertIn("+2", d["diff"])
        (r / "a.txt").write_text("1\n2\n3\n")
        d2 = GO.degisiklik("S9-T9", r)                       # commit yok → çalışma ağacı farkı
        self.assertEqual(d2["kaynak"], "calisma_agaci")
        self.assertIn("+3", d2["diff"])

    def test_notes_dali_commitleri_karismaz(self):
        r = self.tmp / "repo2"
        r.mkdir()
        g = lambda *a: subprocess.run(["git", *a], cwd=r, capture_output=True, text=True, check=True)
        g("init", "-q")
        g("config", "user.email", "t@t")
        g("config", "user.name", "t")
        (r / "a.txt").write_text("1\n")
        g("add", ".")
        g("commit", "-q", "-m", "studio: görev DONE — S1-T1")
        gercek = g("rev-parse", "HEAD").stdout.strip()
        (r / "n.txt").write_text("x\n")
        g("add", ".")
        g("commit", "-q", "-m", "studio: görev DONE — S1-T1 (not)")
        g("update-ref", "refs/notes/blamely", "HEAD")
        g("reset", "-q", "--hard", gercek)
        self.assertEqual(GO.gorev_commit("S1-T1", r), gercek)

    def test_ozet_ic_ice_json_acilir(self):
        B.audit("engine", "kontrol_istek", detay={"flag": "onay_bekliyor", "deger": '{"sebep": "G\u00fcnl\u00fck b\u00fct\u00e7e"}'})
        o = GO.akis(1)[0]["ozet"]
        self.assertIn("Günlük bütçe", o)
        self.assertNotIn("\\u", o)

    def test_gecersiz_gorev_kimligi_komuta_girmez(self):
        self.assertIsNone(GO.gorev_commit("x; rm -rf /"))


if __name__ == "__main__":
    unittest.main()
