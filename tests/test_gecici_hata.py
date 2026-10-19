"""Geçici hata (SIGKILL/interrupted) görevi öldürmez, koşucuyu kapatmaz (issue #311)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import studio_engine as E  # noqa: E402


class GeciciHata(unittest.TestCase):
    def test_kesinti_hatalari_gecici_sayilir(self):
        for m in ("agy hata koduyla çıktı (-9): error: interrupted", "devin hata koduyla çıktı (-15)", "process killed: 9", "error: interrupted"):
            self.assertTrue(E.is_limit_error(m), m)

    def test_deterministik_hatalar_gecici_degil(self):
        for m in ("girdi okunamadı beyanı: çıktı yazılmadı (GİRDİ-EKSİK / okunamadı)", "derleme başarısız (import 3)", "rol bulunamadı: x", "kaynak uygulanmadı"):
            self.assertFalse(E.is_limit_error(m), m)

    def test_azami_deneme_ayari(self):
        self.assertEqual(E.GOREV_HATA_AZAMI, 3)


if __name__ == "__main__":
    unittest.main()


class AgyAsiliKalma313(unittest.TestCase):
    """#313: agy yanıt JSON'unu yazıp çıkmazsa çıktı kurtarılır; zaman aşımı sınırlıdır."""

    def test_sahte_agy_yaniti_yazip_cikmaz_cikti_kullanilir(self):
        import json
        import stat
        import tempfile
        import time
        d = Path(tempfile.mkdtemp())
        sahte = d / "agy"
        sahte.write_text('#!/bin/bash\necho \'{"conversation_id":"x","status":"SUCCESS","response":"=== FILE: a.md ===\\nmerhaba","usage":{}}\'\nsleep 600\n', encoding="utf-8")
        sahte.chmod(sahte.stat().st_mode | stat.S_IXUSR)
        eski = (E.find_exe, E.AGY_CIKIS_TOLERANSI)
        E.find_exe = lambda n: str(sahte) if n == "agy" else eski[0](n)
        E.AGY_CIKIS_TOLERANSI = 1
        try:
            t0 = time.time()
            sonuc = E._call_agy("sistem", "kullanıcı", "high", "gemini-3.8-flash-high", [])
            self.assertIn("merhaba", sonuc.text)
            self.assertLess(time.time() - t0, 60)                      # 600 sn uyku beklenmedi
        finally:
            E.find_exe, E.AGY_CIKIS_TOLERANSI = eski

    def test_zaman_asimi_gecici_hata_sayilsa_da_kosucu_duzeyinde_yeniden_denenmez(self):
        self.assertTrue(E.is_limit_error("agy 1860s içinde yanıt vermedi."))
        self.assertEqual(E.CALL_RETRY, 2)
