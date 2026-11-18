#!/usr/bin/env python3
"""
tests/test_canli_dagitim.py
İzole Dal (bug/feature) Yaşam Döngüsü, Canlıya Dağıtım ve GitHub Issue Yönetimi Birim Testleri.
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
        def side_effect(cmd, **kwargs):
            m = MagicMock()
            if "refs/heads/master" in cmd or "refs/remotes/origin/master" in cmd:
                m.returncode = 1
            else:
                m.returncode = 0
            return m
        mock_run.side_effect = side_effect
        self.assertEqual(CD.ana_dal_bul(ROOT), "main")

    def test_gorev_dali_adi_tipleri(self):
        # 1. Hata ve issue numaralı
        self.assertEqual(CD.gorev_dali_adi({"tur": "HATA", "github_issue_number": 261}), "bug/261")
        # 2. Geliştirme ve issue numaralı
        self.assertEqual(CD.gorev_dali_adi({"tur": "GELISTIRME", "github_issue_number": 262}), "feature/262")
        # 3. Metinden #issue yakalama
        self.assertEqual(CD.gorev_dali_adi({"title": "fix: bellek sizintisi (#263)", "tur": "HATA"}), "bug/263")
        # 4. Talep numarası
        self.assertEqual(CD.gorev_dali_adi({"id": "TALEP-018", "tur": "HATA"}), "bug/18")
        # 5. Sprint görevi
        self.assertEqual(CD.gorev_dali_adi({"id": "S16-T2", "title": "BBox Harita API"}), "feature/s16-t2")
        # 6. Talep ilişkili görev (talep_id ile)
        with patch("musteri_talepleri.getir", return_value={"id": "TALEP-035", "tur": "HATA", "github_issue_number": 276}):
            self.assertEqual(CD.gorev_dali_adi({"id": "S52-T1", "talep_id": "TALEP-035"}), "bug/276")
            self.assertEqual(CD.gorev_dali_adi({"id": "S52-T2", "title": "[TALEP-035] UAT Kabul"}), "bug/276")

    @patch("shutil.which", return_value="/usr/local/bin/gh")
    @patch("canli_dagitim.ana_dal_bul", return_value="master")
    @patch("subprocess.run")
    def test_talep_pr_olustur_mevcut_pr(self, mock_run, mock_ana, mock_which):
        def side_effect(cmd, **kwargs):
            m = MagicMock()
            if "show-ref" in cmd:
                m.returncode = 0
            elif "pr" in cmd and "list" in cmd:
                m.returncode = 0
                m.stdout = '[{"number": 278, "url": "https://github.com/cihan53/repo/pull/278", "state": "OPEN"}]'
            else:
                m.returncode = 0
                m.stdout = ""
            return m
        mock_run.side_effect = side_effect

        res = CD.talep_pr_olustur({"id": "TALEP-035", "tur": "HATA", "github_issue_number": 276}, ROOT)
        self.assertTrue(res["ok"])
        self.assertEqual(res["pr_number"], 278)
        self.assertIn("pull/278", res["pr_url"])

    @patch("canli_dagitim.ana_dal_bul", return_value="master")
    @patch("subprocess.run")
    def test_gorev_dali_hazirla(self, mock_run, mock_ana):
        m = MagicMock()
        m.returncode = 0
        mock_run.return_value = m

        res = CD.gorev_dali_hazirla({"tur": "HATA", "github_issue_number": 261}, ROOT)
        self.assertTrue(res["ok"])
        self.assertEqual(res["dal"], "bug/261")
        self.assertEqual(res["ana_dal"], "master")

    @patch("canli_dagitim.ana_dal_bul", return_value="master")
    @patch("subprocess.run")
    def test_gorev_dali_birlestir_basarili(self, mock_run, mock_ana):
        m = MagicMock()
        m.returncode = 0
        mock_run.return_value = m

        with patch("github_issue_bridge.github_issue_kapat", return_value=True):
            res = CD.gorev_dali_birlestir("bug/261", issue_number=261, cwd=ROOT)
            self.assertTrue(res["ok"])
            self.assertIn("başarıyla 'master' dalına birleştirildi", res["mesaj"])

    @patch("canli_dagitim.issuelari_kapat")
    @patch("canli_dagitim.mevcut_dal_bul", return_value="studio/calisma")
    @patch("canli_dagitim.ana_dal_bul", return_value="master")
    @patch("subprocess.run")
    def test_canliya_dagit_hepsi_basarili(self, mock_run, mock_ana, mock_mevcut, mock_issues):
        mock_issues.return_value = {"ok": True, "kapatilanlar": [101]}
        m = MagicMock()
        m.returncode = 0
        m.stdout = ""
        mock_run.return_value = m

        res = CD.canliya_dagit_hepsi(ROOT)
        self.assertTrue(res["ok"])
        self.assertIn("başarıyla 'master' dalına birleştirildi", res["mesaj"])

    @patch("canli_dagitim.mevcut_dal_bul", return_value="studio/calisma")
    @patch("canli_dagitim.ana_dal_bul", return_value="master")
    @patch("subprocess.run")
    def test_canliya_dagit_tekil_commit_bulunamazsa(self, mock_run, mock_ana, mock_mevcut):
        def side_effect(cmd, **kwargs):
            m = MagicMock()
            if "show-ref" in cmd:
                m.returncode = 1  # İzole dal yok, fallback'e gir
            elif "git" in cmd and "log" in cmd:
                m.returncode = 0
                m.stdout = ""   # Commit bulunamadı
            else:
                m.returncode = 0
                m.stdout = ""
            return m
        mock_run.side_effect = side_effect

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
            if "show-ref" in cmd:
                m.returncode = 1  # Fallback
            elif "git" in cmd and "log" in cmd:
                m.stdout = "a1b2c3d4e5f6\n"
            else:
                m.stdout = ""
            return m
        mock_run.side_effect = side_effect

        res = CD.canliya_dagit_tekil("TALEP-014", ROOT)
        self.assertTrue(res["ok"])
        self.assertIn("başarıyla 'master' dalına aktarıldı", res["mesaj"])

    @patch("canli_dagitim.ana_dal_bul", return_value="master")
    @patch("subprocess.run")
    def test_canliya_dagit_tetikle(self, mock_run, mock_ana):
        m = MagicMock()
        m.returncode = 0
        mock_run.return_value = m

        res_web = CD.canliya_dagit_tetikle("web", cwd=ROOT)
        self.assertTrue(res_web["ok"])
        self.assertIn("Web & Backend", res_web["mesaj"])

        res_mob = CD.canliya_dagit_tetikle("mobil", kanal="beta", cwd=ROOT)
        self.assertTrue(res_mob["ok"])
        self.assertIn("Mobil Uygulama", res_mob["mesaj"])

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
