"""agy (Gemini) CLI için stream-json canlı akış ve araç loglama testleri (issue #364)."""
import json
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import studio_engine as E  # noqa: E402
import studio_board as B  # noqa: E402


class AgyStreamJsonTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.eski_trace = E.TRACE_DIR
        self.eski_root = E.ROOT
        E.TRACE_DIR = self.tmp / "trace"
        E.TRACE_DIR.mkdir(parents=True, exist_ok=True)
        E.ROOT = self.tmp

    def tearDown(self):
        E.TRACE_DIR = self.eski_trace
        E.ROOT = self.eski_root

    def test_stream_json_araclar_ve_metin_canli_akisi(self):
        sahte = self.tmp / "sahte_agy"
        stream_satirlari = [
            json.dumps({"event": "init", "init": {"cwd": str(self.tmp)}}),
            json.dumps({"event": "step_update", "step_update": {"step_type": "tool", "state": "ACTIVE", "tool_name": "run_command", "tool_info": {"parameters": {"CommandLine": "npm run test"}}}}),
            json.dumps({"event": "step_update", "step_update": {"step_type": "tool", "state": "DONE", "tool_name": "run_command", "tool_info": {"output": "12 tests passed successfully"}}}),
            json.dumps({"event": "step_update", "step_update": {"step_type": "tool", "state": "ACTIVE", "tool_name": "write_file", "tool_info": {"parameters": {"Path": "src/app.ts"}}}}),
            json.dumps({"event": "step_update", "step_update": {"step_type": "tool", "state": "DONE", "tool_name": "write_file"}}),
            json.dumps({"event": "step_update", "step_update": {"step_type": "agent_response", "state": "ACTIVE", "text_delta": "Tüm testler ve düzenlemeler bitti."}}),
            json.dumps({"event": "result", "result": {"status": "SUCCESS", "response": "Görev başarıyla tamamlandı.", "usage": {"input_tokens": 1500, "output_tokens": 120}}}),
        ]
        script_icerik = "#!/bin/bash\n" + "\n".join(f"echo '{s}'" for s in stream_satirlari) + "\n"
        sahte.write_text(script_icerik, encoding="utf-8")
        sahte.chmod(sahte.stat().st_mode | stat.S_IXUSR)

        eski_find = E.find_exe
        E.find_exe = lambda n: str(sahte) if n == "agy" else eski_find(n)
        try:
            res = E._call_agy("rol sistem prompt", "kullanıcı prompt", "high", "gemini-3.8-flash-high", tools=["run_command", "write_file"])
            self.assertEqual(res.text, "Görev başarıyla tamamlandı.")
            self.assertEqual(res.usage.get("input_tokens"), 1500)

            live_f = E.TRACE_DIR / "current.out"
            self.assertTrue(live_f.exists())
            out_txt = live_f.read_text(encoding="utf-8")
            # Canlı akış logları ve nihai metin
            self.assertIn("[KOMUT] npm run test", out_txt)
            self.assertIn("[YAZ] src/app.ts", out_txt)
            self.assertIn("Tüm testler ve düzenlemeler bitti.", out_txt)
            self.assertIn("Görev başarıyla tamamlandı.", out_txt)
        finally:
            E.find_exe = eski_find

    def test_stream_json_geriye_donuk_duz_json_uyumlulugu(self):
        sahte = self.tmp / "sahte_agy_eski"
        eski_cikti = json.dumps({"status": "SUCCESS", "response": "Eski format yanıt", "usage": {"total_tokens": 42}})
        sahte.write_text(f"#!/bin/bash\necho '{eski_cikti}'\n", encoding="utf-8")
        sahte.chmod(sahte.stat().st_mode | stat.S_IXUSR)

        eski_find = E.find_exe
        E.find_exe = lambda n: str(sahte) if n == "agy" else eski_find(n)
        try:
            res = E._call_agy("rol sistem prompt", "kullanıcı prompt", "high", "gemini-3.8-flash-high", [])
            self.assertEqual(res.text, "Eski format yanıt")
            self.assertEqual(res.usage.get("total_tokens"), 42)
        finally:
            E.find_exe = eski_find


if __name__ == "__main__":
    unittest.main()
