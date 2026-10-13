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
        self.assertTrue(EA.ertele(self.cfg, self.tmp))               # tamamlansa da tasarım rolleri brief'ten yeniden çalışmaz (#287)
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
        self.assertEqual(len(roller), 6)                                       # ana şablon + 2 modül tasarımı + 3 önizleme
        sablon = next(t for _, t in B.all_tasks(self.board) if SABLON_BASLIK in t["title"])
        digerleri = [t for _, t in B.all_tasks(self.board) if t["title"].startswith(("Ekran tasarımı", "Paket"))]
        self.assertEqual(len(digerleri), 3)
        g = next(t for _, t in B.all_tasks(self.board) if t["role"] == "security_lead")
        paket = next(t for _, t in B.all_tasks(self.board) if t["title"].startswith("Paket"))
        self.assertEqual(g["depends_on"], [paket["id"]])
        self.assertTrue(all(sablon["id"] in t["depends_on"] for t in digerleri))

    def _tasarima_gec(self):
        self.rapor([self.B("a"), self.B("b", modul="ayar", kaynak="src/settings.ts")])
        EA.kontrol(self.board, {}, self.cfg, self.tmp)
        d = self.tmp / EA.EKRAN_DIZIN
        d.mkdir(parents=True)
        for i in ("a", "b"):
            (d / f"{i}.md").write_text(TAM, encoding="utf-8")
        for s in self.board["sprints"][1:]:
            for t in s["tasks"]:
                B.mark(self.board, t["id"], B.DONE, "ok")
        EA.kontrol(self.board, {}, self.cfg, self.tmp)

    def test_onizleme_gorevleri_tasarima_bagli_ve_planı_bekletir(self):
        self._tasarima_gec()
        onz = [t for _, t in B.all_tasks(self.board) if t["title"].startswith("Önizleme:")]
        self.assertEqual(len(onz), 3)
        self.assertTrue(all(t["outputs"][0].startswith(EA.ONIZLEME_DIZIN) and t["outputs"][0].endswith(".html") for t in onz))
        self.assertTrue(all("<script>" not in t["description"] or "YOK" in t["description"] for t in onz))
        self.assertEqual(EA.durum_oku(self.tmp)["asama"], "tasarim")
        for t in [t for _, t in B.all_tasks(self.board) if t["role"] == EA.TASARIMCI]:
            B.mark(self.board, t["id"], B.DONE, "ok")
        EA.kontrol(self.board, {}, self.cfg, self.tmp)                  # önizleme dosyaları yok → yeniden açılır, plana geçilmez
        self.assertEqual(EA.durum_oku(self.tmp)["asama"], "tasarim")
        self.assertTrue(any("GEÇERSİZ ÖNİZLEME" in t["description"] for _, t in B.all_tasks(self.board)))

    def test_onizleme_dogrulama_kurallari(self):
        d = self.tmp / "o.html"
        d.write_text("<html><body>" + "x" * 500 + "</body></html>", encoding="utf-8")
        self.assertEqual(EA.onizleme_eksikleri(d), [])
        d.write_text("<html><body>" + "x" * 500 + "<script>1</script></body></html>", encoding="utf-8")
        self.assertIn("<script> kullanılmış", EA.onizleme_eksikleri(d))
        d.write_text('<html><head><link href="https://cdn.x/a.css"></head>' + "x" * 500, encoding="utf-8")
        self.assertIn("harici kaynak kullanılmış", EA.onizleme_eksikleri(d))
        self.assertEqual(EA.onizleme_eksikleri(self.tmp / "yok.html"), ["dosya yok"])

    def test_gecerli_onizlemeler_plana_gecirir(self):
        self._tasarima_gec()
        (self.tmp / EA.ONIZLEME_DIZIN).mkdir(parents=True)
        for _, t in B.all_tasks(self.board):
            if t["title"].startswith("Önizleme:"):
                (self.tmp / t["outputs"][0]).write_text("<html><body>" + "x" * 500 + "</body></html>", encoding="utf-8")
        for _, t in B.all_tasks(self.board):
            B.mark(self.board, t["id"], B.DONE, "ok")
        EA.kontrol(self.board, {}, self.cfg, self.tmp)
        self.assertTrue(EA.durum_oku(self.tmp)["onizleme_dogrulandi"])
        EA.kontrol(self.board, {}, self.cfg, self.tmp)
        d = EA.durum_oku(self.tmp)
        self.assertEqual(d["asama"], "tasarim")                          # insan tasarım onayı bekleniyor
        kapi = next(t for _, t in B.all_tasks(self.board) if t["id"] == d["onay_gorevi"])
        self.assertEqual(kapi["role"], "human")
        self.assertIn(EA.ONIZLEME_DIZIN, kapi["description"])
        B.mark(self.board, kapi["id"], B.DONE, "insan onayı: test")
        EA.kontrol(self.board, {}, self.cfg, self.tmp)
        self.assertEqual(EA.durum_oku(self.tmp)["asama"], "plan")

    def _gate_hazir(self):
        self._tasarima_gec()
        (self.tmp / EA.ONIZLEME_DIZIN).mkdir(parents=True)
        for _, t in B.all_tasks(self.board):
            if t["title"].startswith("Önizleme:"):
                (self.tmp / t["outputs"][0]).write_text("<html><body>" + "x" * 500 + "</body></html>", encoding="utf-8")
        for _, t in B.all_tasks(self.board):
            if t["role"] != "human":
                B.mark(self.board, t["id"], B.DONE, "ok")
        EA.kontrol(self.board, {}, self.cfg, self.tmp)
        EA.kontrol(self.board, {}, self.cfg, self.tmp)
        return next(t for _, t in B.all_tasks(self.board) if t["id"] == EA.durum_oku(self.tmp)["onay_gorevi"])

    def test_hedefli_ret_yalniz_belirtilen_onizlemeyi_yeniden_yaptirir(self):
        import insan_onayi as IO
        kapi = self._gate_hazir()
        self.assertEqual(kapi["status"], B.READY)
        hedef = next(t for _, t in B.all_tasks(self.board) if t["title"].startswith("Önizleme:") and "ayar" in t["outputs"][0])
        ad = hedef["outputs"][0].rsplit("/", 1)[1]
        ok, msg = IO.karar_ver(self.board, kapi["id"], "reject", f"{ad}: filtre barı bozuk", kim="test")
        self.assertTrue(ok, msg)
        acilan = [t for _, t in B.all_tasks(self.board) if t["title"].startswith("Önizleme:") and t["status"] in (B.TODO, B.READY)]
        self.assertEqual([t["id"] for t in acilan], [hedef["id"]])
        self.assertIn("REVİZYON İSTEĞİ", hedef["description"])
        self.assertIn("filtre barı bozuk", hedef["description"])
        # yeniden yapılınca tekrar doğrulanır ve kapı yeniden açılır
        B.mark(self.board, hedef["id"], B.DONE, "ok")
        EA.kontrol(self.board, {}, self.cfg, self.tmp)
        self.assertTrue(EA.durum_oku(self.tmp)["onizleme_dogrulandi"])

    def test_eslesmeyen_retde_hepsi_yeniden_yapilir(self):
        import insan_onayi as IO
        kapi = self._gate_hazir()
        ok, _ = IO.karar_ver(self.board, kapi["id"], "reject", "genel olarak renkler uyumsuz", kim="test")
        self.assertTrue(ok)
        acilan = [t for _, t in B.all_tasks(self.board) if t["title"].startswith("Önizleme:") and t["status"] in (B.TODO, B.READY)]
        self.assertEqual(len(acilan), 3)

    def test_kapali_ayarda_onizleme_yok(self):
        cfg = {**self.cfg, "envanter": {"html_onizleme": False}}
        self.rapor([self.B("a")])
        EA.kontrol(self.board, {}, cfg, self.tmp)
        d = self.tmp / EA.EKRAN_DIZIN
        d.mkdir(parents=True)
        (d / "a.md").write_text(TAM, encoding="utf-8")
        for s in self.board["sprints"][1:]:
            for t in s["tasks"]:
                B.mark(self.board, t["id"], B.DONE, "ok")
        EA.kontrol(self.board, {}, cfg, self.tmp)
        self.assertFalse(any(t["title"].startswith("Önizleme:") for _, t in B.all_tasks(self.board)))

    def test_tasarimi_bitmis_projeye_telafi(self):
        self._tasarima_gec()
        d = EA.durum_oku(self.tmp)
        d.pop("sprintler_onizleme"); d["asama"] = "tamam"; d.pop("onizleme_dogrulandi", None)       # eski proje: önizleme kaydı yok
        EA.durum_yaz(d, self.tmp)
        self.board["sprints"] = [s for s in self.board["sprints"] if not any(t["title"].startswith("Önizleme:") for t in s["tasks"])]
        for _, t in B.all_tasks(self.board):
            B.mark(self.board, t["id"], B.DONE, "ok")
        self.assertTrue(EA.kontrol(self.board, {}, self.cfg, self.tmp))
        onz = [t for _, t in B.all_tasks(self.board) if t["title"].startswith("Önizleme:")]
        self.assertEqual(len(onz), 3)
        self.assertTrue(all(t["depends_on"] == [] for t in onz))                              # tasarım zaten bitmiş

    def test_kok_rolu_org_chartta_var_ve_araclari_okuma(self):
        org = json.loads((ROOT / "org_chart.json").read_text(encoding="utf-8"))
        r = next(a for a in org["hierarchy"] if a["id"] == EA.ANALIST)
        self.assertEqual(set(r["tools"]), {"Read", "Glob", "Grep", "WebFetch"})      # yazma yok; referans sistemi okumak için WebFetch
        self.assertTrue(any(a["id"] == EA.TASARIMCI for a in org["hierarchy"]))


SABLON_BASLIK = "Ana şablon"

if __name__ == "__main__":
    unittest.main()
