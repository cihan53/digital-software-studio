"""Envanter aşaması (issue #273)."""
import json
import shutil
import sys
import tempfile
import unittest
from unittest import mock
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
        import karar_verici_triage as KVT0
        self._kvt_eski = KVT0.FAZLAR_FILE
        KVT0.FAZLAR_FILE = self.tmp / "fazlar.json"
        self.cfg = {"source": {"path": str(self.kaynak)}}
        self.board = B.normalize(EA.baslangic_panosu(self.cfg, self.tmp))
        B.refresh(self.board)

    def tearDown(self):
        import karar_verici_triage as KVT0
        KVT0.FAZLAR_FILE = self._kvt_eski
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
        d.write_text('<html><body><a href="https://oobeya.io/contact-sales/">İletişim</a>' + "x" * 500 + "</body></html>", encoding="utf-8")
        self.assertEqual(EA.onizleme_eksikleri(d), [])                  # bağlantı kaynak değildir
        d.write_text('<html><body><img src="https://x.io/a.png">' + "x" * 500 + "</body></html>", encoding="utf-8")
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
        d = EA.durum_oku(self.tmp)
        self.assertEqual(d["fazlar_kuruldu"][0], "FAZ-1")                  # onaydan sonra modül fazları kuruldu
        self.assertGreaterEqual(len(d["fazlar_kuruldu"]), 2)               # altyapı + modül(ler)
        import karar_verici_triage as KVT0
        self.assertEqual(KVT0.load_fazlar()["fazlar"][0]["ad"], "Ortak altyapı ve kabuk")

    def _kayitlari_izole(self, IO):
        """Onay kaydı proje klasörüne (workspace/docs/onaylar) yazılmasın (#299)."""
        p = mock.patch.object(IO, "ROOT", self.tmp)
        p.start()
        self.addCleanup(p.stop)

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
        self._kayitlari_izole(IO)
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
        self._kayitlari_izole(IO)
        kapi = self._gate_hazir()
        ok, _ = IO.karar_ver(self.board, kapi["id"], "reject", "genel olarak renkler uyumsuz", kim="test")
        self.assertTrue(ok)
        acilan = [t for _, t in B.all_tasks(self.board) if t["title"].startswith("Önizleme:") and t["status"] in (B.TODO, B.READY)]
        self.assertEqual(len(acilan), 3)

    def test_cikti_kurtarma_satir_ortasi_isaret(self):
        d = self.tmp / EA.EKRAN_DIZIN
        d.mkdir(parents=True)
        (d / "var.md").write_text("zaten var", encoding="utf-8")
        govde = "\n".join(f"## {b}\nicerik burada yeterince uzun bir satir" for b in EA.BASLIKLAR) * 2
        (d / "_CIKTI.md").write_text(f"Kaynağı inceliyorum.Son doğrulama.=== FILE: eksik-birim.md ===\n{govde}\n=== FILE: var.md ===\n{govde}\n=== FILE: ../kacis.md ===\n{govde}", encoding="utf-8")
        self.assertEqual(EA.cikti_kurtar(self.tmp), ["eksik-birim"])
        self.assertEqual((d / "var.md").read_text(encoding="utf-8"), "zaten var")                  # mevcut dosya ezilmez
        self.assertFalse((self.tmp / "kacis.md").exists())                                          # dizin dışına yazılmaz
        self.assertIn("## Veri yapısı", (d / "eksik-birim.md").read_text(encoding="utf-8"))

    def test_eksik_envanterli_birim_icin_tasarim_gorevi_acilmaz(self):
        self.rapor([self.B("a"), self.B("b", modul="ayar", kaynak="src/settings.ts")])
        EA.kontrol(self.board, {}, self.cfg, self.tmp)
        d = self.tmp / EA.EKRAN_DIZIN
        d.mkdir(parents=True)
        (d / "a.md").write_text(TAM, encoding="utf-8")                                              # b için dosya hiç yok
        for _ in range(EA.TEKRAR_SINIRI + 1):
            for s_ in self.board["sprints"][1:]:
                for t in s_["tasks"]:
                    if t["status"] in (B.TODO, B.READY) or t["status"] == B.DONE:
                        B.mark(self.board, t["id"], B.DONE, "ok")
            EA.kontrol(self.board, {}, self.cfg, self.tmp)
        self.assertEqual(EA.durum_oku(self.tmp)["asama"], "tasarim")
        self.assertEqual(EA.durum_oku(self.tmp)["eksik_birimler"], ["b"])
        self.assertIn("`b`", (self.tmp / EA.DIZIN / "_eksikler.md").read_text(encoding="utf-8"))
        metin = " ".join(t["description"] for _, t in B.all_tasks(self.board) if t["title"].startswith("Ekran tasarımı"))
        self.assertIn("a.md", metin)
        self.assertNotIn("/b.md", metin)

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


class ModulFazlari303(unittest.TestCase):
    """#303: envanterden modül tabanlı fazlar, kapsam dosyası, tam kapsam doğrulaması, plan geri alma."""

    def setUp(self):
        import karar_verici_triage as KVT
        self.KVT = KVT
        self.tmp = Path(tempfile.mkdtemp())
        self.eski = (B.DB_PATH, KVT.FAZLAR_FILE)
        B.DB_PATH = self.tmp / "t.db"
        KVT.FAZLAR_FILE = self.tmp / "fazlar.json"
        self.kaynak = self.tmp / "kaynak"
        (self.kaynak / "src").mkdir(parents=True)
        (self.kaynak / "src" / "x.ts").write_text("x", encoding="utf-8")
        self.cfg = {"source": {"path": str(self.kaynak)}}
        self.birimler = ([self._b(f"home-{i}", "home") for i in range(4)] + [self._b(f"admin-{i}", "admin") for i in range(5)]
                         + [self._b("sistem", "system"), self._b("proje", "project"), self._b("profil", "profile")] + [self._b(f"rapor-{i}", "reports") for i in range(3)])
        (self.tmp / EA.DIZIN).mkdir(parents=True)
        (self.tmp / EA.ROTALAR).write_text(json.dumps({"birimler": self.birimler}), encoding="utf-8")

    def tearDown(self):
        B.DB_PATH, self.KVT.FAZLAR_FILE = self.eski
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _b(self, i, modul):
        return {"id": i, "ad": i, "rota": f"/{i}", "tur": "ekran", "ust": "", "modul": modul, "kaynak": "src/x.ts"}

    def test_gruplama_altyapi_fazi_brief_onceligi_ve_kucuk_modul_birlesimi(self):
        g = EA.faz_grupla(self.birimler, self.cfg, "Pilot: önce reports ve home ekranları")
        adlar = [x["ad"] for x in g]
        self.assertEqual(adlar[0], "Ortak altyapı ve kabuk")
        self.assertEqual(g[0]["birimler"], [])
        self.assertEqual(adlar[1], "Modül: Reports")                         # brief'te ilk geçen
        self.assertEqual(adlar[2], "Modül: Home")
        self.assertEqual(adlar[3], "Modül: Admin")
        kucuk = g[-1]
        self.assertTrue(kucuk["ad"].startswith("Küçük modüller"))
        self.assertEqual(sorted(kucuk["moduller"]), ["profile", "project", "system"])
        self.assertEqual(sum(len(x["birimler"]) for x in g), len(self.birimler))   # hiçbir birim düşmez

    def test_briefte_gecen_kucuk_modul_kendi_fazini_alir(self):
        g = EA.faz_grupla(self.birimler, self.cfg, "pilot: system ekranı önce")
        self.assertEqual([x["ad"] for x in g][1], "Modül: System")
        self.assertNotIn("system", g[-1]["moduller"])

    def test_esik_ayarlanabilir(self):
        g = EA.faz_grupla(self.birimler, {"envanter": {"faz_min_birim": 1}}, "")
        self.assertEqual(len(g), 1 + 6)                                      # altyapı + 6 modülün hepsi ayrı

    def test_fazlari_kur_kapsam_dosyalari_ve_eski_fazlar_silinir(self):
        self.KVT.save_fazlar({"fazlar": [{"id": "FAZ-9", "ad": "eski", "durum": "AKTIF"}]})
        ids = EA.modul_fazlarini_kur(self.cfg, self.tmp, "reports home")
        self.assertEqual(ids[0], "FAZ-1")
        fz = {f["id"]: f for f in self.KVT.load_fazlar()["fazlar"]}
        self.assertNotIn("FAZ-9", fz)
        self.assertEqual(fz["FAZ-1"]["durum"], "AKTIF")
        self.assertEqual(fz["FAZ-2"]["onkosul_faz"], "FAZ-1")
        kap = json.loads((self.tmp / "workspace/docs/faz_planlari/FAZ-2_kapsam.json").read_text(encoding="utf-8"))
        self.assertEqual(kap["birimler"], ["rapor-0", "rapor-1", "rapor-2"])
        self.assertTrue(any("*reports*" in g for g in kap["girdiler"]))

    def test_plan_kapsami_tum_birimleri_kapsamali(self):
        import faz_planla as FP
        plan = {"sprints": [{"id": "P1", "name": "s", "goal": "g", "tasks": [
            {"id": "P1-T1", "title": "a", "description": "d", "role": "web_engineer", "phase": "develop", "outputs": ["workspace/src/web/"], "depends_on": []},
            {"id": "P1-T2", "title": "b", "description": "d", "role": "qa_lead", "phase": "test", "outputs": ["workspace/docs/qa.md"], "depends_on": ["P1-T1"]}]}]}
        ids = ["a", "b"]
        self.assertIn("'kapsam' alanı yok", FP.plan_dogrula(plan, None, ids)[0])
        plan["kapsam"] = {"a": "P1-T1"}
        self.assertTrue(any("kapsamda olmayan birim: b" in e for e in FP.plan_dogrula(plan, None, ids)))
        plan["kapsam"] = {"a": "P1-T1", "b": "P9-T9"}
        self.assertTrue(any("tanımsız görev" in e for e in FP.plan_dogrula(plan, None, ids)))
        plan["kapsam"] = {"a": "P1-T1", "b": "P1-T1"}
        self.assertEqual(FP.plan_dogrula(plan, None, ids), [])
        self.assertEqual(FP.plan_dogrula({k: v for k, v in plan.items() if k != "kapsam"}, None, None), [])       # kapsamsız (altyapı/eski) faz etkilenmez

    def test_planlama_gorevi_kapsam_ve_girdileri_icerir(self):
        import faz_planla as FP
        EA.modul_fazlarini_kur(self.cfg, self.tmp, "reports")
        board = B.normalize({"sprints": [{"id": "S1", "name": "s", "order": 0, "tasks": [{"id": "S1-T1", "title": "x", "description": "", "role": "web_engineer", "phase": "develop",
                                                                                           "outputs": ["workspace/x"], "depends_on": [], "status": B.DONE, "note": "", "talep_id": None, "order": 0, "priority": 0}]}]})
        org = {"hierarchy": [{"id": "sprint_planner", "stage": "design", "outputs": []}, {"id": "web_engineer", "stage": "build", "outputs": ["workspace/src/web/"]}]}
        FP.planlama_sprinti_ekle(board, {"id": "FAZ-2", "ad": "Modül: Reports", "aciklama": "a"}, org, None, kok=self.tmp)
        t = next(t for _, t in B.all_tasks(board) if t["role"] == "sprint_planner")
        self.assertIn("FAZ KAPSAMI", t["description"])
        self.assertIn("rapor-0, rapor-1, rapor-2", t["description"])
        self.assertIn("\"kapsam\"", t["description"])
        self.assertIn("*reports*", t["description"])

    def test_plani_geri_al_ve_baslamis_plan_reddedilir(self):
        import faz_planla as FP
        board = B.normalize({"sprints": [{"id": "S1", "name": "s", "order": 0, "tasks": [{"id": "S1-T1", "title": "x", "description": "", "role": "web_engineer", "phase": "develop",
                                                                                           "outputs": ["workspace/x"], "depends_on": [], "status": B.DONE, "note": "", "talep_id": None, "order": 0, "priority": 0}]}]})
        org = {"hierarchy": [{"id": "sprint_planner", "stage": "design", "outputs": []}, {"id": "web_engineer", "stage": "build", "outputs": ["workspace/src/web/"]}]}
        FP.planlama_sprinti_ekle(board, {"id": "FAZ-1", "ad": "a", "aciklama": "a"}, org, None, kok=self.tmp)
        plan = {"sprints": [{"id": "P1", "name": "Plan sprinti", "goal": "g", "tasks": [
            {"id": "P1-T1", "title": "a", "description": "d", "role": "web_engineer", "phase": "develop", "outputs": ["workspace/src/web/"], "depends_on": []},
            {"id": "P1-T2", "title": "b", "description": "d", "role": "web_engineer", "phase": "test", "outputs": ["workspace/docs/qa.md"], "depends_on": ["P1-T1"]}]}]}
        FP.plan_yolu("FAZ-1", self.tmp).write_text(json.dumps(plan), encoding="utf-8")
        FP.plani_uygula(board, "FAZ-1", plan, None, None, kok=self.tmp)
        self.assertTrue(any(s["name"] == "Plan sprinti" for s in board["sprints"]))
        uyg = next(t for s in board["sprints"] if s["name"] == "Plan sprinti" for t in s["tasks"])
        B.mark(board, uyg["id"], B.RUNNING, "")
        ok, msg = FP.plani_geri_al(board, "FAZ-1", self.tmp)
        self.assertFalse(ok)
        B.mark(board, uyg["id"], B.DONE, "")
        self.assertFalse(FP.plani_geri_al(board, "FAZ-1", self.tmp)[0])                 # bitmiş görev: zorla gerekir
        B.mark(board, uyg["id"], B.TODO, "")
        ok, msg = FP.plani_geri_al(board, "FAZ-1", self.tmp)
        self.assertTrue(ok, msg)
        self.assertEqual([s["name"] for s in board["sprints"]], ["s"])
        self.assertFalse(FP.uygulandi_yolu("FAZ-1", self.tmp).exists())


SABLON_BASLIK = "Ana şablon"

if __name__ == "__main__":
    unittest.main()
