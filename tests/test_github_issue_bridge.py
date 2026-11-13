#!/usr/bin/env python3
"""
tests/test_github_issue_bridge.py
GitHub Issues Bridge Inbound Discovery ve İçe Aktarma Birim Testleri
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import github_issue_bridge as GH


class TestGithubIssueBridgeInbound(unittest.TestCase):

    @patch("github_issue_bridge.github_acik_isleri_tara")
    @patch("musteri_talepleri.load_data")
    def test_eslenmemis_github_islerini_bul(self, mock_load_data, mock_tara):
        # 1. Mevcut taleplerde #101 ve #102 kayıtlı olsun
        mock_load_data.return_value = {
            "talepler": [
                {
                    "id": "TALEP-001",
                    "baslik": "Mevcut Talep 1",
                    "github_issue_number": 101,
                    "github_issue_url": "https://github.com/org/repo/issues/101"
                },
                {
                    "id": "TALEP-002",
                    "baslik": "[TALEP-002] Başka Talep",
                    "github_issue_number": 102
                }
            ]
        }

        # 2. GitHub üzerinde #101, #102 ve yeni #233 PR'ı olsun
        mock_tara.return_value = [
            {"number": 101, "title": "[TALEP-001] Mevcut Talep 1", "is_pr": False, "url": "https://..."},
            {"number": 102, "title": "[TALEP-002] Başka Talep", "is_pr": False, "url": "https://..."},
            {"number": 233, "title": "feat(routing): Akıllı Rota Planlama", "is_pr": True, "url": "https://github.com/org/repo/pull/233", "labels": []}
        ]

        eslenmemis = GH.eslenmemis_github_islerini_bul()
        self.assertEqual(len(eslenmemis), 1)
        self.assertEqual(eslenmemis[0]["number"], 233)
        self.assertTrue(eslenmemis[0]["is_pr"])

    @patch("musteri_talepleri.load_data")
    @patch("musteri_talepleri.save_data")
    @patch("musteri_talepleri._sonraki_talep_no", return_value=5)
    def test_github_isini_talebe_aktar(self, mock_no, mock_save, mock_load):
        mock_load.return_value = {"talepler": []}

        item = {
            "number": 233,
            "title": "feat(routing): Akıllı Rota Planlama",
            "body": "Rota sıcaklık faktörlerini hesaba katar.",
            "url": "https://github.com/org/repo/pull/233",
            "is_pr": True,
            "labels": [{"name": "enhancement"}]
        }

        yeni = GH.github_isini_talebe_aktar(item)
        self.assertIsNotNone(yeni)
        self.assertEqual(yeni["id"], "TALEP-005")
        self.assertEqual(yeni["github_issue_number"], 233)
        self.assertEqual(yeni["tur"], "ISTEK")
        self.assertIn("GitHub PR #233", yeni["aciklama"])
        self.assertTrue(mock_save.called)


if __name__ == "__main__":
    unittest.main()
