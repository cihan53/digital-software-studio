"""Kapalı döngü onarım (issue #247): döngü, istem, kapı koşturucu, güvenlik denetimleri, claude yasak araç bayrağı."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import onarim as ON


class Dongu(unittest.TestCase):
    def test_kapi_zaten_geciyorsa_ajan_cagrilmaz(self):
        cagri = []
        s = ON.dongu(lambda t: (True, "tamam"), lambda t, k: cagri.append(t), log=lambda *_: None)
        self.assertEqual((s["durum"], s["tur"], cagri), ("zaten_gecti", 0, []))

    def test_ikinci_turda_cozulur_ve_kanit_tasinir(self):
        durumlar = iter([(False, "ilk hata"), (False, "ikinci hata"), (True, "")])
        gorulen, kontrol = [], []
        s = ON.dongu(lambda t: next(durumlar), lambda t, k: gorulen.append((t, k)), kontrol.append, azami_tur=3, log=lambda *_: None)
        self.assertEqual(s["durum"], "cozuldu")
        self.assertEqual(s["tur"], 2)
        self.assertEqual(gorulen, [(1, "ilk hata"), (2, "ikinci hata")])          # her tura SON kanıt taşınır
        self.assertEqual(kontrol, [1, 2])                                         # her tur öncesi kontrol noktası

    def test_sinir_asilirsa_cozulemedi(self):
        s = ON.dongu(lambda t: (False, "hep hata"), lambda t, k: None, azami_tur=2, log=lambda *_: None)
        self.assertEqual((s["durum"], s["tur"], s["kanit"]), ("cozulemedi", 2, "hep hata"))


class Istem(unittest.TestCase):
    def test_etiket_ve_uygunluk(self):
        self.assertEqual(ON.etiket({"title": "[TALEP-009] [RENDER] S4-T4 tarayıcıda çizim"}), "RENDER")
        self.assertEqual(ON.etiket({"title": "[TALEP-004] [HİJYEN] x"}), "HİJYEN")
        self.assertIsNone(ON.etiket({"title": "Müşteri isteği: yeni buton"}))
        self.assertTrue(ON.uygun_mu({"talep_id": "TALEP-1", "phase": "develop", "role": "web_engineer"}))
        self.assertFalse(ON.uygun_mu({"talep_id": "TALEP-1", "phase": "test", "role": "uat_auditor"}))
        self.assertFalse(ON.uygun_mu({"phase": "develop", "role": "web_engineer"}))             # talepsiz normal görev etkilenmez

    def test_istem_kanit_tur_ve_kurallar(self):
        sis, kul = ON.istem({"title": "[RENDER] x", "description": "açıklama"}, "RENDER", "hata çıktısı", 2, 3)
        self.assertIn("hata çıktısı", kul)
        self.assertIn("TUR: 2/3", kul)
        self.assertIn("render_kapisi", kul)
        self.assertIn("baştan yazma", sis)
        self.assertIn("workspace/", sis)

    def test_araclar_komut_serbest_yazma_kapsamli_tehlikeli_yasak(self):
        self.assertIn("Bash", ON.ARACLAR)
        self.assertIn("Edit(workspace/**)", ON.ARACLAR)
        for yasak in ("!Bash(sudo:*)", "!Bash(git push:*)", "!Bash(pkill:*)", "!Bash(git reset:*)"):
            self.assertIn(yasak, ON.ARACLAR)


class KapiKosturucu(unittest.TestCase):
    def test_build_kapisi_alias_eksikligini_gorur_ve_duzelince_gecer(self):
        k = Path(tempfile.mkdtemp()).resolve()
        (k / "workspace/src/web/app/stores").mkdir(parents=True)
        (k / "workspace/src/web/nuxt.config.ts").write_text("export default defineNuxtConfig({})")
        (k / "workspace/src/web/app/stores/s.ts").write_text("import x from '#shared/schemas/s'\n")
        f = ON.kapi("BUILD", k)
        ok, kanit = f(0)
        self.assertFalse(ok)
        self.assertIn("#shared/schemas/s", kanit)
        (k / "workspace/src/web/shared/schemas").mkdir(parents=True)
        (k / "workspace/src/web/shared/schemas/s.ts").write_text("export default 1")
        self.assertTrue(f(1)[0])

    def test_etiketsiz_icin_kapi_yok(self):
        self.assertIsNone(ON.kapi(None, ROOT))


class Guvenlik(unittest.TestCase):
    def _repo(self):
        k = Path(tempfile.mkdtemp()).resolve()
        git = lambda *a: subprocess.run(["git", "-c", "user.email=a@b", "-c", "user.name=t", *a], cwd=k, capture_output=True, check=True)
        git("init", "-q")
        (k / "workspace").mkdir()
        (k / "README.md").write_text("orijinal")
        (k / "workspace/a.txt").write_text("a")
        git("add", "-A")
        git("commit", "-qm", "i")
        return k

    def test_workspace_disi_degisiklik_geri_alinir(self):
        k = self._repo()
        import kalite_kapilari as K
        eski = K.ROOT
        try:
            K.ROOT = k
            once = K.porcelain_snapshot()
        finally:
            K.ROOT = eski
        (k / "README.md").write_text("bozuldu")                    # izlenen dosya, workspace dışı
        (k / "yeni_disari.txt").write_text("x")                    # izlenmeyen, workspace dışı
        (k / "workspace/a.txt").write_text("serbest degisiklik")   # workspace içi: dokunulmaz
        geri = ON.kapsam_denetle(k, once)
        self.assertEqual(sorted(geri), ["README.md", "yeni_disari.txt"])
        self.assertEqual((k / "README.md").read_text(), "orijinal")
        self.assertFalse((k / "yeni_disari.txt").exists())
        self.assertEqual((k / "workspace/a.txt").read_text(), "serbest degisiklik")

    def test_cerceve_butunlugu(self):
        k = Path(tempfile.mkdtemp()).resolve()
        (k / "scripts").mkdir()
        (k / "scripts/x.py").write_text("print(1)")
        (k / "studio.version").write_text(json.dumps({"version": "1", "tracked_files": ["scripts/x.py"]}))
        once = ON.butunluk_anlik(k)
        self.assertEqual(ON.butunluk_denetle(k, once), [])
        (k / "scripts/x.py").write_text("print(2)")
        self.assertEqual(ON.butunluk_denetle(k, once), ["scripts/x.py"])


class ClaudeYasakBayragi(unittest.TestCase):
    def test_unlem_oneki_disallowedTools_olur(self):
        import studio_engine as E
        yakalanan = {}
        eski = (E._run_cli, E.find_exe)
        try:
            E.find_exe = lambda n: "/bin/claude"

            def sahte(cmd, cwd, timeout, ad, **kw):
                yakalanan["cmd"], yakalanan["cwd"] = cmd, cwd
                return 0, json.dumps({"type": "result", "result": "tamam", "is_error": False, "usage": {}, "total_cost_usd": 0}), ""
            E._run_cli = sahte
            E._call_claude("sistem", "kullanıcı", "medium", "haiku", ["Read", "Bash", "!Bash(sudo:*)"])
        finally:
            E._run_cli, E.find_exe = eski
        cmd = yakalanan["cmd"]
        i = cmd.index("--disallowedTools")
        self.assertEqual(cmd[i + 1], "Bash(sudo:*)")
        self.assertIn("Bash", [cmd[j + 1] for j, c in enumerate(cmd) if c == "--allowedTools"])
        self.assertEqual(Path(yakalanan["cwd"]), E.ROOT)                          # araçlı çağrı proje kökünde koşar


if __name__ == "__main__":
    unittest.main()


class GercekDogrulama(unittest.TestCase):
    """KAYNAK/BUILD kapısı uygulamanın testini koşar; telafi UAT bulgusunu girdi alır (issue #251)."""

    def _uygulama(self, kod: int):
        kok = Path(tempfile.mkdtemp())
        d = kok / "workspace" / "src" / "web"
        (d / "node_modules").mkdir(parents=True)
        (d / "package.json").write_text(json.dumps({"scripts": {"test": f"echo kirmizi-cikti; exit {kod}"}}), encoding="utf-8")
        return kok

    def test_kirmizi_test_kapiyi_basarisiz_sayar(self):
        kok = self._uygulama(1)
        ok, kanit = ON.testleri_kos(kok)
        self.assertFalse(ok)
        self.assertIn("kirmizi-cikti", kanit)
        ok, kanit = ON.kapi("KAYNAK", kok)(0)
        self.assertFalse(ok)
        self.assertIn("kirmizi-cikti", kanit)

    def test_yesil_veya_betiksiz_gecer(self):
        self.assertTrue(ON.testleri_kos(self._uygulama(0))[0])
        kok = Path(tempfile.mkdtemp())
        self.assertTrue(ON.testleri_kos(kok)[0])                      # uygulama yok → atla

    def test_uat_bulgulari_istemde(self):
        kok = Path(tempfile.mkdtemp())
        (kok / "workspace/docs").mkdir(parents=True)
        (kok / "workspace/docs/uat_kabul_raporu_TALEP-9.md").write_text(
            "| ENV-01 | sunucu | **GEÇTİ** | ok |\n| TLP-02 | kopya | **KALDI (BUG)** | costLedger.test.ts:29 sohbet metni |\n"
            "| TLP-03 | veri | **ÇALIŞTIRILMADI** | - |\n", encoding="utf-8")
        b = ON.uat_bulgulari("TALEP-9", kok)
        self.assertIn("costLedger.test.ts:29", b)
        self.assertNotIn("ENV-01", b)
        self.assertNotIn("TLP-03", b)
        self.assertEqual(ON.uat_bulgulari(None, kok), "")
        self.assertEqual(ON.uat_bulgulari("TALEP-1", kok), "")


class AcikBulgu(unittest.TestCase):
    """issue #269"""

    def test_kapi_gecse_de_acik_bulguda_ajan_cagrilir(self):
        cagri = []
        s = ON.dongu(lambda tur: (True, ""), lambda tur, k: cagri.append((tur, k)), azami_tur=2, log=lambda *a: None,
                     acik_bulgu="| UAT-B1 | SelectItem value='' | KALDI |")
        self.assertEqual(len(cagri), 1)
        self.assertIn("UAT-B1", cagri[0][1])
        self.assertEqual(s["durum"], "cozuldu")

    def test_bulgu_yoksa_eski_davranis(self):
        cagri = []
        s = ON.dongu(lambda tur: (True, ""), lambda tur, k: cagri.append(tur), log=lambda *a: None)
        self.assertEqual((s["durum"], cagri), ("zaten_gecti", []))

    def test_kaynak_kapisi_onarim_muaf(self):
        import kalite_kapilari as K
        eski = K.kaynak_degisti_mi
        K.kaynak_degisti_mi = lambda t, f: False
        try:
            t = {"id": "T", "role": "web_engineer", "phase": "develop", "outputs": ["workspace/src/web/"]}
            self.assertIn("kaynak uygulanmadı", K.gorev_kapilari(dict(t), set()))
            self.assertNotIn("kaynak uygulanmadı", K.gorev_kapilari({**t, "onarim_muaf": True}, set()))
        finally:
            K.kaynak_degisti_mi = eski
