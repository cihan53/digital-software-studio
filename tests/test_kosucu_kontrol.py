"""Web panelinden koşucunun izlenmesi ve başlatılması testleri (issue #374)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import studio_board as B  # noqa: E402
import studio_web as W  # noqa: E402


class KosucuKontrol(unittest.TestCase):
    def test_durum_ozeti_kosucu_kapali_raporlar(self):
        with mock.patch.object(B, "runner_pid", return_value=None):
            ozet = W.durum_ozeti()
            self.assertFalse(ozet["kosucu"])
            self.assertIsNone(ozet["kosucu_pid"])

    def test_durum_ozeti_kosucu_acik_raporlar(self):
        with mock.patch.object(B, "runner_pid", return_value=12345):
            ozet = W.durum_ozeti()
            self.assertTrue(ozet["kosucu"])
            self.assertEqual(ozet["kosucu_pid"], 12345)

    def test_kontrol_baslat_eylemi(self):
        with mock.patch.object(B, "start_runner", return_value=(True, "Koşucu başarıyla başlatıldı (PID: 9999).")) as mock_start:
            resp = W.kontrol({"aksiyon": "baslat"})
            self.assertTrue(resp["ok"])
            self.assertIn("PID: 9999", resp["mesaj"])
            mock_start.assert_called_once_with(restart=False)

    def test_kontrol_yeniden_baslat_eylemi(self):
        with mock.patch.object(B, "start_runner", return_value=(True, "Koşucu başarıyla yeniden başlatıldı (PID: 8888).")) as mock_start:
            resp = W.kontrol({"aksiyon": "yeniden_baslat"})
            self.assertTrue(resp["ok"])
            self.assertIn("PID: 8888", resp["mesaj"])
            mock_start.assert_called_once_with(restart=True)

    def test_start_runner_calisirken_baslatma_engellenir(self):
        with mock.patch.object(B, "runner_pid", return_value=12345):
            ok, msg = B.start_runner(restart=False)
            self.assertFalse(ok)
            self.assertIn("zaten çalışıyor", msg)

    def test_start_runner_surec_baslatir(self):
        mock_proc = mock.MagicMock()
        mock_proc.pid = 54321
        mock_proc.poll.return_value = None  # Process is running

        with mock.patch.object(B, "runner_pid", return_value=None), \
             mock.patch.object(B, "clear") as mock_clear, \
             mock.patch.object(B, "audit"), \
             mock.patch("time.sleep"), \
             mock.patch("builtins.open", mock.mock_open()), \
             mock.patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            ok, msg = B.start_runner(restart=False)
            self.assertTrue(ok)
            self.assertIn("54321", msg)
            # Bayraklar temizlenmeli
            mock_clear.assert_any_call("pause")
            mock_clear.assert_any_call("stop")
            mock_clear.assert_any_call("devre_disi")
            mock_popen.assert_called_once()


if __name__ == "__main__":
    unittest.main()
