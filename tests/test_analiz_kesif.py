"""studio_config / analiz_dogrula / kesif_denetle birim testleri (issue #130)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import studio_config as C  # noqa: E402
import analiz_dogrula as A  # noqa: E402
import kesif_denetle as K  # noqa: E402

TEMPLATE = ["amaç", "girdiler"]
ACFG = {**C.DEFAULTS["analysis"], "template": TEMPLATE, "max_words_l1": 40, "max_words_l2": 80}


def doc(level="L1", amac="Liste gösterir [kaynak: a.ts:1]", girdi="bilinmiyor", extra=""):
    return f"# Birim\nSeviye: {level}\n\n## amaç\n{amac}\n\n## girdiler\n{girdi}\n{extra}"


class Config(unittest.TestCase):
    def test_config_yoksa_none(self):
        self.assertIsNone(C.load_config(Path("/yok/studio.config.json")))

    def test_render_degisken_ve_bilinmeyen(self):
        cfg = C._merge(C.DEFAULTS, {"source": {"live_url": "https://x.io"}})
        self.assertEqual(C.render("url={{source.live_url}}", cfg), "url=https://x.io")
        self.assertEqual(C.render("{{yok.anahtar}}", cfg), "{{yok.anahtar}}")
        self.assertEqual(C.render("{{source.live_url}}", None), "{{source.live_url}}")

    def test_kesif_sozlesmesi_zorunlu_alanlar(self):
        self.assertTrue(C.validate_discovery(C._merge(C.DEFAULTS, {})))
        ok = C._merge(C.DEFAULTS, {"discovery": {"goal": "g", "questions": ["q"],
                                                  "allow": {"hosts": ["a.io"]}}})
        self.assertEqual(C.validate_discovery(ok), [])

    def test_rules_block_config_yoksa_bos(self):
        self.assertEqual(C.rules_block(None, analysis=True, discovery=True), "")
        cfg = C._merge(C.DEFAULTS, {"discovery": {"goal": "g", "questions": ["q"],
                                                  "allow": {"hosts": ["a.io"]}}})
        self.assertIn("KEŞİF SÖZLEŞMESİ", C.rules_block(cfg, discovery=True))
        self.assertIn("ANALİZ BÜTÇESİ", C.rules_block(cfg, analysis=True))


class Analiz(unittest.TestCase):
    def test_gecerli_dosya(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "a.md"
            p.write_text(doc())
            errs, lv = A.check_file(p, ACFG)
            self.assertEqual((errs, lv), ([], "L1"))

    def test_kanitsiz_alan_reddedilir(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "a.md"
            p.write_text(doc(amac="Liste gösterir"))
            errs, _ = A.check_file(p, ACFG)
            self.assertTrue(any("kanıtsız" in e for e in errs))

    def test_eksik_alan_ve_seviye_ve_tavan(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "a.md"
            p.write_text("# X\n## amaç\nbilinmiyor\n" + "kelime " * 60)
            errs, lv = A.check_file(p, ACFG)
            self.assertIsNone(lv)
            self.assertTrue(any("Seviye" in e for e in errs))
            self.assertTrue(any("eksik" in e for e in errs))
            self.assertTrue(any("tavan" in e for e in errs))

    def test_l2_kotasi(self):
        with tempfile.TemporaryDirectory() as t:
            for i in range(4):
                (Path(t) / f"b{i}.md").write_text(doc("L2", extra=f"\nbenzersiz satır numara {i}\n"))
            rep = A.validate_dir(Path(t), {**ACFG, "l2_quota_pct": 25, "l2_quota_max": 20})
            self.assertIn("_kota", rep["errors"])

    def test_benzer_dosyalar_uyarilir_indeks_haric(self):
        with tempfile.TemporaryDirectory() as t:
            govde = "".join(f"\nortak uzun satır {i} aynı\n" for i in range(8))
            for n in ("x", "y"):
                (Path(t) / f"{n}.md").write_text(doc(extra=govde))
            (Path(t) / "_indeks.md").write_text("indeks")
            rep = A.validate_dir(Path(t), {**ACFG, "max_words_l1": 500})
            self.assertEqual(rep["files"], 2)
            self.assertEqual(len(rep["warnings"]), 1)

    def test_marjinal_durak(self):
        self.assertTrue(A.marjinal_durak([3, 1, 0, 0, 0], 3))
        self.assertFalse(A.marjinal_durak([0, 0, 1], 3))
        self.assertFalse(A.marjinal_durak([0, 0], 3))


D = C._merge(C.DEFAULTS, {"discovery": {
    "goal": "g", "questions": ["q1", "q2"],
    "allow": {"hosts": ["dev.x.io"], "paths": ["^/(home|admin)"]},
    "limits": {"max_actions_per_unit": 2, "max_depth": 1, "max_units": 5, "max_off_inventory_pct": 10}}})["discovery"]


def row(url="https://dev.x.io/home", sinif="read", eylem="open", soru="Q1", birim="b1", **kw):
    return {"birim": birim, "url": url, "eylem_sinifi": sinif, "eylem": eylem, "soru_id": soru, **kw}


class Kesif(unittest.TestCase):
    def test_izin_kurallari(self):
        self.assertTrue(K.izin("https://dev.x.io/home", "read", "", D)[0])
        self.assertFalse(K.izin("https://evil.io/home", "read", "", D)[0])
        self.assertFalse(K.izin("https://dev.x.io/billing", "read", "", D)[0])
        self.assertFalse(K.izin("https://dev.x.io/home", "mutating", "save", D)[0])
        self.assertFalse(K.izin("https://dev.x.io/home", "reversible", "delete", D)[0])
        self.assertFalse(K.izin("https://dev.x.io/other", "read", "", D)[0])

    def test_temiz_gunluk(self):
        r = K.denetle([row(), row(birim="b2", sinif="reversible")], D, None)
        self.assertEqual(r["ihlaller"], [])

    def test_ihlaller(self):
        rows = [row(), row(), row(),  # b1 üç eylem > 2
                row(url="https://dev.x.io/home", soru="Q9", birim="b2"),
                row(url="https://dev.x.io/admin", sinif="mutating", birim="b3"),
                row(derinlik=3, birim="b4")]
        txt = "\n".join(K.denetle(rows, D, None)["ihlaller"])
        for beklenen in ("eylem > tavan", "soru_id", "mutating", "derinlik"):
            self.assertIn(beklenen, txt)

    def test_envanter_disi_orani(self):
        inv = K.load_inventory(self._inv(["/home", "/admin/:id"]))
        ok = K.denetle([row(url="https://dev.x.io/admin/42")] * 1, D, inv)
        self.assertEqual(ok["ihlaller"], [])
        bad = K.denetle([row(url="https://dev.x.io/home"), row(url="https://dev.x.io/admin/x/y", birim="b2")], D, inv)
        self.assertTrue(any("envanter dışı" in v for v in bad["ihlaller"]))

    def _inv(self, items):
        f = Path(tempfile.mkdtemp()) / "inv.txt"
        f.write_text("\n".join(items))
        return f


if __name__ == "__main__":
    unittest.main()
