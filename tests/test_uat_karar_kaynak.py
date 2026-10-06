"""uat_karari / kaynak_dizinleri testleri (issue #128)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import studio_engine as E  # noqa: E402


class UatKarari(unittest.TestCase):
    def _k(self, metin):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.md"
            p.write_text(metin, encoding="utf-8")
            return E.uat_karari(p)

    def test_red_bicimleri(self):
        self.assertEqual(self._k("# UAT\n\n**KARAR: REDDEDİLDİ (BUG).** x"), "RED")
        self.assertEqual(self._k("**Sonuç: REDDEDİLDİ (kanıt yetersiz).**"), "RED")
        self.assertEqual(self._k("**SONUÇ: REDDEDİLDİ — TALEP-010 kabul edilmedi.**"), "RED")
        self.assertEqual(self._k("> KARAR: reddedildi"), "RED")

    def test_kabul(self):
        self.assertEqual(self._k("**KARAR: KABUL EDİLDİ**"), "KABUL")
        self.assertEqual(self._k("Sonuç: ONAYLANDI"), "KABUL")

    def test_olumsuz_kabul_red_sayilir(self):
        self.assertEqual(self._k("KARAR: KABUL EDİLEMEZ"), "RED")
        self.assertEqual(self._k("Sonuç: KABUL EDİLMEDİ"), "RED")

    def test_karar_yok_veya_dosya_yok(self):
        self.assertIsNone(self._k("# Rapor\nHerhangi bir karar yok. kabul edilebilir"))
        self.assertIsNone(E.uat_karari("/yok/yok.md"))


class UatRedGecerliligi(unittest.TestCase):
    """issue #253"""

    def test_red_sayaci_insan_mudahalesinde_sifirlanir(self):
        b = {"eylem": "Durum güncellendi: BEKLEMEDE", "durum": "BEKLEMEDE"}
        self.assertEqual(E.uat_red_sayisi([b, b, b]), 3)
        self.assertEqual(E.uat_red_sayisi([b, b, b, {"eylem": "x", "durum": "INSAN_GEREKLI"}, {"eylem": "İnsan: yeniden kuyruğa alındı", "durum": "BEKLEMEDE"}]), 0)
        self.assertEqual(E.uat_red_sayisi([b, {"eylem": "İnsan: yeniden", "durum": "BEKLEMEDE"}, b]), 1)

    def test_bayat_kanita_dayanan_red_yesil_kanitla_gecersiz(self):
        rapor = ("| TLP-02 | kopya | **KALDI (BUG, önceki kanıt)** | bu oturumda doğrulanmadı |\n"
                 "| TLP-03 | veri | **ÇALIŞTIRILMADI** | - |\n")
        self.assertFalse(E.uat_red_gecerli(rapor, True))
        self.assertTrue(E.uat_red_gecerli(rapor, False))        # kanıt kırmızı: ajan kararı geçerli
        self.assertTrue(E.uat_red_gecerli(rapor, None))         # kanıt toplanamadı: ajan kararı geçerli

    def test_calistirilmis_basarisiz_madde_red_kalir(self):
        rapor = "| TLP-06 | konsol | **BAŞARISIZ** | TypeError: x undefined (playwright çıktısı) |\n"
        self.assertTrue(E.uat_red_gecerli(rapor, True))

    def test_kanit_yalniz_talepli_uat_gorevinde_toplanir(self):
        self.assertEqual(E.uat_kaniti_topla({"id": "T1", "role": "web_engineer", "talep_id": "TALEP-1"}), "")
        self.assertEqual(E.uat_kaniti_topla({"id": "T2", "role": "uat_auditor", "talep_id": None}), "")
        self.assertIsNone(E._UAT_KANIT["T1"])


class KaynakDizinleri(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ref = Path(self.tmp.name) / "ref-proje"
        self.ref.mkdir()
        self._w, self._d = E.WORKSPACE, E.DOC_DIR
        E.WORKSPACE = Path(self.tmp.name) / "workspace"
        E.DOC_DIR = E.WORKSPACE / "docs"
        E.DOC_DIR.mkdir(parents=True)
        os.environ.pop("STUDIO_KAYNAK_DIRS", None)

    def tearDown(self):
        E.WORKSPACE, E.DOC_DIR = self._w, self._d
        os.environ.pop("STUDIO_KAYNAK_DIRS", None)
        self.tmp.cleanup()

    def test_baslik_ve_env_ve_olmayan_dizin(self):
        (E.DOC_DIR / "kaynak_proje_envanter.md").write_text(
            f"# T\n\n> Bu doküman `{self.ref}` projesinden üretildi.\n> `/yok/dizin` değil\n",
            encoding="utf-8")
        self.assertEqual(E.kaynak_dizinleri(), [str(self.ref.resolve())])
        os.environ["STUDIO_KAYNAK_DIRS"] = "/yok/x"
        self.assertEqual(E.kaynak_dizinleri(), [str(self.ref.resolve())])

    def test_json_kaydi(self):
        (E.WORKSPACE / ".kaynak_projeler.json").write_text(
            '{"dizinler": ["%s"]}' % self.ref, encoding="utf-8")
        self.assertEqual(E.kaynak_dizinleri(), [str(self.ref.resolve())])


if __name__ == "__main__":
    unittest.main()
