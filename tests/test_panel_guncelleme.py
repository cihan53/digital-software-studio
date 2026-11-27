#!/usr/bin/env python3
"""
tests/test_panel_guncelleme.py
Web panelinden doğrudan güncelleme uygulama ve yeniden başlatma testleri (#390).
"""

import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import studio_web as SW


class TestPanelGuncelleme(unittest.TestCase):

    @patch("subprocess.run")
    @patch("studio_board.runner_pid", return_value=1234)
    @patch("studio_board.start_runner")
    @patch("studio_board.audit")
    def test_guncelleme_uygula_basarili(self, mock_audit, mock_start_runner, mock_pid, mock_run):
        m = MagicMock()
        m.returncode = 0
        m.stdout = "2 dosya güncellendi."
        mock_run.return_value = m

        res = SW.guncelleme_uygula({"restart": False})
        self.assertTrue(res["ok"])
        self.assertIn("başarıyla uygulandı", res["mesaj"])
        mock_start_runner.assert_not_called()  # restart: False verilince koşucu yeniden başlatılmaz

        # restart: True ile çağrıldığında
        res_restart = SW.guncelleme_uygula({"restart": True})
        self.assertTrue(res_restart["ok"])
        mock_start_runner.assert_called_once_with(restart=True)
        self.assertIn("Koşucu güncel kodla yeniden başlatıldı", res_restart["mesaj"])

    @patch("subprocess.run")
    def test_guncelleme_uygula_hata(self, mock_run):
        m = MagicMock()
        m.returncode = 1
        m.stderr = "Git bağlantı hatası"
        mock_run.return_value = m

        res = SW.guncelleme_uygula({"restart": False})
        self.assertFalse(res["ok"])
        self.assertIn("Git bağlantı hatası", res["mesaj"])

    @patch("studio_web.guncelleme_uygula")
    def test_kontrol_aksiyonu_guncelleme_uygula(self, mock_guncelle):
        mock_guncelle.return_value = {"ok": True, "mesaj": "Test"}
        res = SW.kontrol({"aksiyon": "guncelleme_uygula", "restart": False})
        self.assertTrue(res["ok"])
        mock_guncelle.assert_called_once_with({"aksiyon": "guncelleme_uygula", "restart": False})

    def test_panel_html_bilesenleri(self):
        panel_html = (ROOT / "web" / "panel.html").read_text(encoding="utf-8")
        self.assertIn("guncelleUygula", panel_html)
        self.assertIn("komutKopyala", panel_html)
        self.assertIn("b-gunc-uygula", panel_html)
        self.assertIn("🚀 Güncellemeyi Uygula", panel_html)
        self.assertIn("user-select: all", panel_html)
        self.assertIn("dataset.updating", panel_html)


if __name__ == "__main__":
    unittest.main()
