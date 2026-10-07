"""Model çıktısının sonuna sızan araç-çağrısı etiketleri dosyaya yazılmaz (issue #197)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import studio_engine as E

# Etiketler parçalı kurulur: kaynak dosyanın kendisi araç çağrısı biçimi taşımasın.
LT = "<"
KAPAT = LT + "/"
NS = "ant" + "ml:"
P_KAPAT = KAPAT + "parameter>"
I_KAPAT = KAPAT + "invoke>"
P_AC = LT + 'parameter name="content">'


class AracArtefakti(unittest.TestCase):
    def test_sondaki_etiketler_silinir(self):
        s = f"export const a = 1\n{P_KAPAT}\n{I_KAPAT}\n"
        self.assertEqual(E.temizle_arac_artefakti(s).strip(), "export const a = 1")
        s = f"x\n{KAPAT}{NS}parameter>\n{KAPAT}{NS}invoke>"
        self.assertEqual(E.temizle_arac_artefakti(s).strip(), "x")

    def test_etiketleri_anlatan_dokumana_dokunulmaz(self):
        s = f"Örnek: {P_AC}x{P_KAPAT} biçimi\n{P_KAPAT}\n"
        self.assertEqual(E.temizle_arac_artefakti(s), s)

    def test_normal_icerik_degismez(self):
        s = "<template><div>merhaba</div></template>\n"
        self.assertEqual(E.temizle_arac_artefakti(s), s)

    def test_dosyaya_yazma(self):
        eski_out, eski_ws = E.check_output_path, E.WORKSPACE
        d = Path(tempfile.mkdtemp())
        try:
            E.check_output_path = lambda p: (d / 'ciktilar').resolve()
            ya = E.write_multi_file("ciktilar/", f"=== FILE: a.ts ===\nexport const a = 1\n{P_KAPAT}\n{I_KAPAT}\n=== FILE: b.ts ===\nexport const b = 2\n")
            self.assertEqual({f.name for f in ya}, {"a.ts", "b.ts"})
            self.assertEqual((d / "ciktilar" / "a.ts").read_text().strip(), "export const a = 1")
            self.assertEqual((d / "ciktilar" / "b.ts").read_text().strip(), "export const b = 2")
        finally:
            E.check_output_path, E.WORKSPACE = eski_out, eski_ws


class DosyaIsaretleyici(unittest.TestCase):
    def test_uc_ve_daha_fazla_esit_isareti(self):
        for ayrac in ("===", "=====", "========"):
            m = E.FILE_MARKER.findall(f"{ayrac} FILE: app/a.ts {ayrac}\nx\n{ayrac} FILE: b/c.vue {ayrac}\ny\n")
            self.assertEqual(m, ["app/a.ts", "b/c.vue"], ayrac)

    def test_normal_satir_isaretleyici_sayilmaz(self):
        self.assertEqual(E.FILE_MARKER.findall("== FILE: a.ts ==\nconst a = '=== FILE: x ===' + 1\n"), [])

    def test_bes_esit_isaretli_cok_dosyali_cikti_ayrilir(self):
        eski = E.check_output_path
        d = Path(tempfile.mkdtemp())
        try:
            E.check_output_path = lambda p: (d / "web").resolve()
            ya = E.write_multi_file("web/", "===== FILE: app/a.ts =====\nexport const a = 1\n===== FILE: app/b.ts =====\nexport const b = 2\n")
            self.assertEqual(sorted(f.name for f in ya), ["a.ts", "b.ts"])
            self.assertNotIn("FILE:", (d / "web/app/a.ts").read_text())
        finally:
            E.check_output_path = eski


class BasBosSatir(unittest.TestCase):
    def test_shebang_ilk_satirda_yazilir(self):
        eski = (E.check_output_path,)
        d = Path(tempfile.mkdtemp())
        try:
            E.check_output_path = lambda p: (d / "betikler").resolve()
            ya = E.write_multi_file("betikler/", "=== FILE: a.mjs ===\n#!/usr/bin/env node\nconsole.log(1)\n\nconsole.log(2)\n=== FILE: b.sh ===\r\n\n#!/bin/sh\necho x\n")
            a = (d / "betikler" / "a.mjs").read_text()
            self.assertTrue(a.startswith("#!/usr/bin/env node\n"), repr(a[:30]))
            self.assertIn("console.log(1)\n\nconsole.log(2)", a)                  # iç boşluklar korunur
            self.assertTrue((d / "betikler" / "b.sh").read_text().startswith("#!/bin/sh\n"))
            E.check_output_path = lambda p: (d / "tek.mjs").resolve()
            E.write_single_file("tek.mjs", "\n\n#!/usr/bin/env node\nx\n")
            self.assertTrue((d / "tek.mjs").read_text().startswith("#!/usr/bin/env node"))
        finally:
            E.check_output_path, = eski


class YedekDokum(unittest.TestCase):
    def test_isaretleyicisiz_cikti_src_disina_yazilir(self):
        d = Path(tempfile.mkdtemp()).resolve()
        eski = (E.check_output_path, E.WORKSPACE, E.DOC_DIR)
        try:
            E.WORKSPACE, E.DOC_DIR = d / "workspace", d / "workspace" / "docs"
            hedef = d / "workspace" / "src" / "web" / "app" / "components"
            E.check_output_path = lambda p: hedef
            ya = E.write_multi_file("workspace/src/web/app/components/", "Dosyaları doğrudan düzenledim, özet burada.")
            self.assertEqual(len(ya), 1)
            self.assertTrue(str(ya[0]).startswith(str(d / "workspace/docs/cikti_notlari")))
            self.assertNotIn("_CIKTI", ya[0].name)                             # hijyen kapısı artefakt saymaz
            self.assertFalse(hedef.exists() and any(hedef.iterdir()))          # kaynak ağacına dosya bırakılmaz
            # kaynak dışı (doküman) dizin hedefleri eski davranışı korur
            doc = d / "workspace" / "docs" / "tasarim"
            E.check_output_path = lambda p: doc
            ya2 = E.write_multi_file("workspace/docs/tasarim/", "özet")
            self.assertEqual(ya2[0].name, "_CIKTI.md")
        finally:
            E.check_output_path, E.WORKSPACE, E.DOC_DIR = eski


class ShebangOncesi(unittest.TestCase):
    """issue #255"""

    def test_anlatim_atilir(self):
        m = "Mevcut betiği inceliyorum.\n\n#!/usr/bin/env bash\necho 1\n"
        self.assertEqual(E.shebang_oncesini_at(m, "workspace/yerel_ortam.sh"), "#!/usr/bin/env bash\necho 1\n")

    def test_dokunulmayanlar(self):
        self.assertEqual(E.shebang_oncesini_at("#!/bin/sh\nx\n", "a.sh"), "#!/bin/sh\nx\n")
        self.assertEqual(E.shebang_oncesini_at("anlatim\n#!/bin/sh\n", "a.md"), "anlatim\n#!/bin/sh\n")      # betik değil
        self.assertEqual(E.shebang_oncesini_at("echo 1\n# yorum\n", "a.sh"), "echo 1\n# yorum\n")            # shebang yok

    def test_dosyaya_yazma(self):
        eski = E.check_output_path
        d = Path(tempfile.mkdtemp())
        try:
            E.check_output_path = lambda p: (d / "y.sh").resolve()
            E.write_single_file("y.sh", "Anlatim burada.\n#!/usr/bin/env bash\necho 1\n")
            self.assertTrue((d / "y.sh").read_text().startswith("#!/usr/bin/env bash\n"))
            E.check_output_path = lambda p: (d / "m").resolve()
            E.write_multi_file("m/", "=== FILE: a.sh ===\nAnlatim\n#!/bin/sh\necho 2\n")
            self.assertTrue((d / "m" / "a.sh").read_text().startswith("#!/bin/sh\n"))
        finally:
            E.check_output_path = eski


class BetikSozdizimi(unittest.TestCase):
    def test_bozuk_betik_yakalanir(self):
        import kalite_kapilari as K
        d = Path(tempfile.mkdtemp())
        (d / "workspace").mkdir()
        (d / "workspace/iyi.sh").write_text("#!/usr/bin/env bash\necho ok\n")
        (d / "workspace/bozuk.sh").write_text("Mevcut betiği inceliyorum (kontrol)\n#!/usr/bin/env bash\n")
        eski = K.ROOT
        try:
            K.ROOT = d
            h = K.betik_sozdizimi_hatalari(["workspace/iyi.sh", "workspace/bozuk.sh"])
        finally:
            K.ROOT = eski
        self.assertEqual(len(h), 1)
        self.assertIn("bozuk.sh", h[0])


if __name__ == "__main__":
    unittest.main()
