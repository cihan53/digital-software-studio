#!/usr/bin/env python3
"""
tests/test_canli_dagitim.py
Canlıya dağıtım (toplu merge & tekil cherry-pick) ve GitHub issue kapatma birim testleri.
"""

import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import canli_dagitim as CD


class TestCanliDagitim(unittest.TestCase):

    @patch("subprocess.run")
    def test_ana_dal_bul_master_varsa(self, mock_run):
        # master dalı varsa
        def side_effect(cmd, **kwargs):
            m = MagicMock()
            if "refs/heads/master" in cmd:
                m.returncode = 0
            elif "refs/heads/main" in cmd:
                m.returncode = 1
            else:
                m.returncode = 0
            return m
        mock_run.side_effect = side_effect
        self.assertEqual(CD.ana_dal_bul(ROOT), "master")

    @patch("subprocess.run")
    def test_ana_dal_bul_main_varsayilan(self, mock_run):
        # master yoksa main'e düşmeli
        def side_effect(cmd, **kwargs):
            m = MagicMock()
            if "refs/heads/master" in cmd or "refs/remotes/origin/master" in cmd:
                m.returncode = 1
            else:
                m.returncode = 0
            return m
        mock_run.side_effect = side_effect
        self.assertEqual(CD.ana_dal_bul(ROOT), "main")

    @patch("canli_dagitim.issuelari_kapat")
    @patch("canli_dagitim.mevcut_dal_bul", return_value="studio/calisma")
    @patch("canli_dagitim.ana_dal_bul", return_value="master")
    @patch("subprocess.run")
    def test_canliya_dagit_hepsi_basarili(self, mock_run, mock_ana, mock_mevcut, mock_issues):
        mock_issues.return_value = {"ok": True, "kapatilanlar": [101]}
        m = MagicMock()
        m.returncode = 0
        mock_run.return_value = m

        res = CD.canliya_dagit_hepsi(ROOT)
        self.assertTrue(res["ok"])
        self.assertIn("başarıyla 'master' dalına birleştirildi", res["mesaj"])

    @patch("canli_dagitim.mevcut_dal_bul", return_value="studio/calisma")
    @patch("canli_dagitim.ana_dal_bul", return_value="master")
    @patch("subprocess.run")
    def test_canliya_dagit_tekil_commit_bulunamazsa(self, mock_run, mock_ana, mock_mevcut):
        m = MagicMock()
        m.returncode = 0
        m.stdout = ""
        mock_run.return_value = m

        res = CD.canliya_dagit_tekil("TALEP-999", ROOT)
        self.assertFalse(res["ok"])
        self.assertIn("commit bulunamadı", res["mesaj"])

    @patch("canli_dagitim.mevcut_dal_bul", return_value="studio/calisma")
    @patch("canli_dagitim.ana_dal_bul", return_value="master")
    @patch("subprocess.run")
    def test_canliya_dagit_tekil_basarili(self, mock_run, mock_ana, mock_mevcut):
        def side_effect(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            if "git" in cmd and "log" in cmd:
                m.stdout = "a1b2c3d4e5f6\n"
            else:
                m.stdout = ""
            return m
        mock_run.side_effect = side_effect

        res = CD.canliya_dagit_tekil("TALEP-014", ROOT)
        self.assertTrue(res["ok"])
        self.assertIn("başarıyla 'master' dalına aktarıldı", res["mesaj"])

    @patch("github_issue_bridge.gh_mevcut_mu", return_value=True)
    @patch("musteri_talepleri.db_tum_talepler")
    @patch("subprocess.run")
    def test_issuelari_kapat_senkronizasyon(self, mock_run, mock_db, mock_gh):
        mock_db.return_value = [
            {"id": "TALEP-001", "durum": "COZULDU", "github_issue_number": 201},
            {"id": "TALEP-002", "durum": "COZULDU", "github_issue_number": 202},
            {"id": "TALEP-003", "durum": "GELISTIRILIYOR", "github_issue_number": 203},
        ]
        def side_effect(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            if "gh" in cmd and "list" in cmd:
                m.stdout = '[{"number": 201}]'
            return m
        mock_run.side_effect = side_effect

        with patch("github_issue_bridge.github_issue_kapat", return_value=True):
            res = CD.issuelari_kapat(ROOT)
            self.assertTrue(res["ok"])
            self.assertEqual(res["kapatilanlar"], [201])


if __name__ == "__main__":
    unittest.main()
