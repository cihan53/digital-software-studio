"""Model çıktısının sonuna sızan araç-çağrısı etiketleri dosyaya yazılmaz (issue #197)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
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
            self.assertEqual((d / "ciktilar" / "a.ts").read_text(), "export const a = 1\n")
            self.assertEqual((d / "ciktilar" / "b.ts").read_text(), "export const b = 2\n")
        finally:
            E.check_output_path, E.WORKSPACE = eski_out, eski_ws


if __name__ == "__main__":
    unittest.main()
