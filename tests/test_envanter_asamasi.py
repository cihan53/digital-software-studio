"""Envanter aşaması (issue #273)."""
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
import envanter_asamasi as EA  # noqa: E402

TAM = "\n".join(f"## {b}\nbilinmiyor ya da yok değil: içerik" for b in EA.BASLIKLAR)


class Envanter(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.eski = B.DB_PATH
        B.DB_PATH = self.tmp / "t.db"
        self.kaynak = self.tmp / "kaynak"
        (self.kaynak / "src").mkdir(parents=True)
        for f in ("home.ts", "settings.ts", "dialog.ts"):
            (self.kaynak / "src" / f).write_text("x", encoding="utf-8")
        self.cfg = {"source": {"path": str(self.kaynak)}}
        self.board = B.normalize(EA.baslangic_panosu(self.cfg, self.tmp))
        B.refresh(self.board)

    def tearDown(self):
        B.DB_PATH = self.eski
        shutil.rmtree(self.tmp, ignore_errors=True)

    def rapor(self, birimler):
        (self.tmp / EA.ROTALAR).write_text(json.dumps({"birimler": birimler}), encoding="utf-8")
        B.mark(self.board, "S1-T1", B.DONE, "ok")

    def B(self, i, tur="ekran", kaynak="src/home.ts", ust="", modul="home"):
        return {"id": i, "ad": i, "rota": f"/{i}", "tur": tur, "ust": ust, "modul": modul, "kaynak": kaynak}

    def test_acik_mi_kaynak_ve_ayarlar(self):
        self.assertTrue(EA.acik_mi(self.cfg))
        self.assertFalse(EA.acik_mi({}))
        self.assertFalse(EA.acik_mi({**self.cfg, "envanter": {"acik": False}}))
        self.assertFalse(EA.acik_mi({**self.cfg, "planlama": {"uretici": "birim"}}))
        self.assertFalse(EA.acik_mi({"source": {"path": str(self.tmp / "yok")}}))

    def test_ertele_yeniden_baslatmada_da_surer(self):
        self.assertTrue(EA.ertele(self.cfg, self.tmp))               # durum 'rotalar' (gerekli() artık False)
        self.assertFalse(EA.gerekli(self.cfg, self.tmp))
        EA.durum_yaz({"asama": "tamam"}, self.tmp)
        self.assertFalse(EA.ertele(self.cfg, self.tmp))
        self.assertFalse(EA.ertele({}, self.tmp))

    def test_baslangic_sadece_rota_gorevi(self):
        self.assertEqual(len(self.board["sprints"]), 1)
        t = self.board["sprints"][0]["tasks"][0]
        self.assertEqual(t["role"], EA.ANALIST)
        self.assertEqual(t["outputs"], [EA.ROTALAR])
        self.assertFalse(EA.gerekli(self.cfg, self.tmp))         # durum artık 'rotalar'

    def test_uydurma_kaynak_yolu_reddedilir(self):
        self.rapor([self.B("a", kaynak="src/yok.ts")])
        self.assertTrue(EA.kontrol(self.board, {}, self.cfg, self.tmp))
        t = self.board["sprints"][0]["tasks"][0]
        self.assertIn(t["status"], (B.TODO, B.READY))
        self.assertIn("GEÇERSİZ LİSTE", t["description"])
        self.assertEqual(EA.durum_oku(self.tmp)["asama"], "rotalar")

    def test_modal_ust_ekran_zorunlu_ve_tekil_id(self):
        errs = EA.rota_dogrula({"birimler": [self.B("m", tur="modal", ust="yok"), self.B("m")]}, self.cfg)
        self.assertTrue(any("üst ekran" in e for e in errs))
        self.assertTrue(any("yinelenen" in e for e in errs))

    def test_gecerli_liste_birim_gorevlerini_ekler(self):
        self.rapor([self.B("a"), self.B("b", kaynak="src/settings.ts"), self.B("c", tur="modal", ust="a", kaynak="src/dialog.ts"),
                    self.B("d", modul="ayar", kaynak="src/settings.ts")])
        self.assertTrue(EA.kontrol(self.board, {}, self.cfg, self.tmp))
        self.assertEqual(EA.durum_oku(self.tmp)["asama"], "envanter")
        gor = [t for s in self.board["sprints"][1:] for t in s["tasks"]]
        self.assertEqual(len(gor), 2)   # home(3) tek parça, ayar(1)
        self.assertTrue(all(t["outputs"] == [f"{EA.EKRAN_DIZIN}/"] for t in gor))

    def test_tamlik_kapisi_eksik_dosyada_gorevi_yeniden_acar(self):
        self.rapor([self.B("a")])
        EA.kontrol(self.board, {}, self.cfg, self.tmp)
        gor = self.board["sprints"][1]["tasks"][0]
        B.mark(self.board, gor["id"], B.DONE, "ok")
        self.assertTrue(EA.kontrol(self.board, {}, self.cfg, self.tmp))        # dosya yok → yeniden açıldı
        g = next(t for _, t in B.all_tasks(self.board) if t["id"] == gor["id"])
        self.assertIn(g["status"], (B.TODO, B.READY))
        self.assertIn("EKSİK ENVANTER", g["description"])
        self.assertEqual(EA.durum_oku(self.tmp)["asama"], "envanter")

    def test_bos_baslik_eksik_sayilir(self):
        d = self.tmp / EA.EKRAN_DIZIN
        d.mkdir(parents=True)
        (d / "a.md").write_text(TAM.replace("içerik", "x", 1).replace("## Tablolar\nbilinmiyor ya da yok değil: içerik", "## Tablolar\n"), encoding="utf-8")
        self.assertTrue(any("Tablolar" in e for e in EA.dosya_eksikleri("a", self.tmp)))
        (d / "a.md").write_text(TAM, encoding="utf-8")
        self.assertEqual(EA.dosya_eksikleri("a", self.tmp), [])

    def test_tam_envanter_tasarima_gecer(self):
        self.rapor([self.B("a"), self.B("b", modul="ayar", kaynak="src/settings.ts")])
        EA.kontrol(self.board, {}, self.cfg, self.tmp)
        d = self.tmp / EA.EKRAN_DIZIN
        d.mkdir(parents=True)
        for i in ("a", "b"):
            (d / f"{i}.md").write_text(TAM, encoding="utf-8")
        for s in self.board["sprints"][1:]:
            for t in s["tasks"]:
                B.mark(self.board, t["id"], B.DONE, "ok")
        self.assertTrue(EA.kontrol(self.board, {}, self.cfg, self.tmp))
        self.assertEqual(EA.durum_oku(self.tmp)["asama"], "tasarim")
        self.assertTrue((self.tmp / EA.INDEKS).exists())
        roller = [t["role"] for _, t in B.all_tasks(self.board) if t["role"] == EA.TASARIMCI]
        self.assertEqual(len(roller), 3)                                       # ana şablon + 2 modül
        sablon = next(t for _, t in B.all_tasks(self.board) if SABLON_BASLIK in t["title"])
        digerleri = [t for _, t in B.all_tasks(self.board) if t["title"].startswith(("Ekran tasarımı", "Paket"))]
        self.assertEqual(len(digerleri), 3)
        g = next(t for _, t in B.all_tasks(self.board) if t["role"] == "security_lead")
        paket = next(t for _, t in B.all_tasks(self.board) if t["title"].startswith("Paket"))
        self.assertEqual(g["depends_on"], [paket["id"]])
        self.assertTrue(all(sablon["id"] in t["depends_on"] for t in digerleri))

    def test_kok_rolu_org_chartta_var_ve_araclari_okuma(self):
        org = json.loads((ROOT / "org_chart.json").read_text(encoding="utf-8"))
        r = next(a for a in org["hierarchy"] if a["id"] == EA.ANALIST)
        self.assertEqual(set(r["tools"]), {"Read", "Glob", "Grep"})
        self.assertTrue(any(a["id"] == EA.TASARIMCI for a in org["hierarchy"]))


SABLON_BASLIK = "Ana şablon"

if __name__ == "__main__":
    unittest.main()
