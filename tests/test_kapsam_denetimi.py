"""Kapsam açığı denetimi (issue #271)."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import studio_board as B  # noqa: E402
import kapsam_denetimi as KD  # noqa: E402
import karar_verici_triage as KVT  # noqa: E402


def T(i, st):
    return {"id": i, "title": i, "description": "", "role": "web_engineer", "phase": "develop", "outputs": ["workspace/x"],
            "depends_on": [], "status": st, "note": "", "talep_id": None, "order": 0, "priority": 0}


class Kapsam(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.eski = (B.DB_PATH, KVT.FAZLAR_FILE)
        B.DB_PATH = self.tmp / "t.db"
        KVT.FAZLAR_FILE = self.tmp / "fazlar.json"
        (self.tmp / "workspace/docs").mkdir(parents=True)
        (self.tmp / "workspace/docs/ekran_envanteri.md").write_text("| /home | /reports/weekly | /settings |\n", encoding="utf-8")
        (self.tmp / "workspace/src/web/pages").mkdir(parents=True)
        (self.tmp / "workspace/src/web/pages/home.vue").write_text("<template/>", encoding="utf-8")
        (self.tmp / "workspace/src/web/node_modules").mkdir()
        (self.tmp / "workspace/src/web/node_modules/x.vue").write_text("", encoding="utf-8")
        self.board = B.normalize({"sprints": [{"id": "S1", "name": "s1", "order": 0, "tasks": [T("S1-T1", B.DONE), T("S1-T2", B.SKIPPED)]}]})
        B.refresh(self.board)

    def tearDown(self):
        B.DB_PATH, KVT.FAZLAR_FILE = self.eski
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_kanit_ui_ve_skipped_listeler_node_modules_haric(self):
        p = self.tmp / KD.kanit_yaz(self.board, self.tmp)
        m = p.read_text(encoding="utf-8")
        self.assertIn("pages/home.vue", m)
        self.assertNotIn("node_modules", m)
        self.assertIn("S1-T2", m)

    def test_bosta_degilse_tetiklenmez(self):
        b = B.normalize({"sprints": [{"id": "S1", "name": "s", "order": 0, "tasks": [T("S1-T1", B.DONE), T("S1-T2", B.TODO)]}]})
        self.assertFalse(KD.gerekli(b, self.tmp, None))

    def test_kapali_config_tetiklemez(self):
        self.assertFalse(KD.gerekli(self.board, self.tmp, {"kapsam_denetimi": {"acik": False}}))

    def test_tetikle_sprint_ve_kanit(self):
        sid = KD.tetikle(self.board, {}, None, self.tmp)
        self.assertEqual(sid, "S2")
        t = next(t for _, t in B.all_tasks(self.board) if t["id"] == "S2-T1")
        self.assertEqual(t["outputs"], [f"{KD.DIZIN}/K1.json"])
        self.assertIn("ekran_envanteri.md", t["description"])
        self.assertIsNone(KD.tetikle(self.board, {}, None, self.tmp))  # açık denetim varken yineleme yok

    def test_uydurma_birim_reddedilir(self):
        r = {"tamam": False, "ozet": "x", "eksikler": [{"birim": "/olmayan", "kanit": "k"}],
             "fazlar": [{"ad": "A", "aciklama": "a", "birimler": ["/olmayan"]}]}
        self.assertTrue(any("envanterde geçmiyor" in e for e in KD.rapor_dogrula(r, self.tmp)))

    def test_faz_disi_birim_reddedilir(self):
        r = {"tamam": False, "ozet": "x", "eksikler": [{"birim": "/home", "kanit": "k"}, {"birim": "/settings", "kanit": "k"}],
             "fazlar": [{"ad": "A", "aciklama": "a", "birimler": ["/home"]}]}
        self.assertTrue(any("hiçbir fazda değil" in e for e in KD.rapor_dogrula(r, self.tmp)))

    def test_faz_siniri_ayarlanabilir_ve_genis(self):
        (self.tmp / "workspace/docs/ekran_envanteri.md").write_text(" ".join(f"/m{i}" for i in range(6)), encoding="utf-8")
        r = {"tamam": False, "ozet": "x", "eksikler": [{"birim": f"/m{i}", "kanit": "k"} for i in range(6)],
             "fazlar": [{"ad": f"M{i}", "aciklama": "a", "birimler": [f"/m{i}"]} for i in range(6)]}
        self.assertEqual(KD.rapor_dogrula(r, self.tmp), [])                                  # modül başına faz serbest (6 > eski sınır 3)
        self.assertTrue(any("en fazla 4" in e for e in KD.rapor_dogrula(r, self.tmp, {"kapsam_denetimi": {"en_fazla_faz": 4}})))

    def test_gecerli_rapor_ve_tamam(self):
        r = {"tamam": False, "ozet": "x", "eksikler": [{"birim": "/reports/weekly", "kanit": "yok"}],
             "fazlar": [{"ad": "Raporlar", "aciklama": "a", "birimler": ["/reports/weekly"]}]}
        self.assertEqual(KD.rapor_dogrula(r, self.tmp), [])
        self.assertEqual(KD.rapor_dogrula({"tamam": True, "eksikler": [], "fazlar": []}, self.tmp), [])
        self.assertTrue(KD.rapor_dogrula({"tamam": True, "eksikler": [{"birim": "a", "kanit": "b"}], "fazlar": []}, self.tmp))

    def test_kontrol_fazlari_acar_ve_dongu_durur(self):
        KVT.save_fazlar({"fazlar": [{"id": "FAZ-1", "ad": "a", "durum": "TAMAMLANDI"}, {"id": "FAZ-2", "ad": "b", "durum": "AKTIF"}]})
        (self.tmp / "workspace/docs/faz_planlari").mkdir(parents=True)
        (self.tmp / "workspace/docs/faz_planlari/FAZ-2.json").write_text("{}", encoding="utf-8")  # FAZ-2 zaten planlandı
        KD.tetikle(self.board, {}, None, self.tmp)
        rapor = {"tamam": False, "ozet": "x", "eksikler": [{"birim": "/reports/weekly", "kanit": "yok"}],
                 "fazlar": [{"ad": "Raporlar", "aciklama": "a", "birimler": ["/reports/weekly"]}]}
        (self.tmp / KD.DIZIN / "K1.json").write_text(json.dumps(rapor), encoding="utf-8")
        B.mark(self.board, "S2-T1", B.DONE, "ok")
        self.assertTrue(KD.kontrol(self.board, None, self.tmp))
        fz = {f["id"]: f for f in KVT.load_fazlar()["fazlar"]}
        self.assertEqual(fz["FAZ-2"]["durum"], "TAMAMLANDI")
        self.assertEqual(fz["FAZ-3"]["durum"], "AKTIF")
        self.assertEqual(fz["FAZ-3"]["onkosul_faz"], "FAZ-2")
        self.assertFalse(KD.kontrol(self.board, None, self.tmp))  # ikinci kez uygulanmaz

    def test_tamam_raporu_donguyu_durdurur(self):
        KD.tetikle(self.board, {}, None, self.tmp)
        (self.tmp / KD.DIZIN / "K1.json").write_text(json.dumps({"tamam": True, "ozet": "eksik yok", "eksikler": [], "fazlar": []}), encoding="utf-8")
        B.mark(self.board, "S2-T1", B.DONE, "ok")
        KD.kontrol(self.board, None, self.tmp)
        self.assertFalse(KD.gerekli(self.board, self.tmp, None))

    def test_gecersiz_rapor_gorevi_yeniden_acar(self):
        KD.tetikle(self.board, {}, None, self.tmp)
        (self.tmp / KD.DIZIN / "K1.json").write_text("bozuk", encoding="utf-8")
        B.mark(self.board, "S2-T1", B.DONE, "ok")
        self.assertTrue(KD.kontrol(self.board, None, self.tmp))
        t = next(t for _, t in B.all_tasks(self.board) if t["id"] == "S2-T1")
        self.assertIn(t["status"], (B.TODO, B.READY))
        self.assertIn("GEÇERSİZ RAPOR", t["description"])


if __name__ == "__main__":
    unittest.main()
