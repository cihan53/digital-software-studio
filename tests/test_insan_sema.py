"""İnsan onay kapısı ve API şema çıkarımı birim testleri (issue #136)."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import studio_board as B  # noqa: E402
import insan_onayi as I  # noqa: E402


def board(statuses):
    tasks = [{"id": f"T{i}", "title": "g", "role": r, "phase": "develop", "outputs": ["x.md"], "status": st,
              "depends_on": [], "order": i} for i, (r, st) in enumerate(statuses)]
    return {"sprints": [{"id": "S1", "order": 0, "status": B.READY, "tasks": tasks}]}


class InsanKapisi(unittest.TestCase):
    def test_human_gorev_calistirilmaz(self):
        b = board([("human", B.READY), ("web_engineer", B.TODO)])
        s, t = B.next_ready(b)
        self.assertIsNone(t)                       # yalnız insan görevi hazır: koşucu bekler
        self.assertEqual([x["id"] for x in B.pending_human(b)], ["T0"])

    def test_diger_gorevler_etkilenmez(self):
        b = board([("human", B.READY), ("web_engineer", B.READY)])
        s, t = B.next_ready(b)
        self.assertEqual(t["id"], "T1")

    def test_onay_kaydi_yazilir(self):
        with tempfile.TemporaryDirectory() as d:
            task = {"id": "S2-G1", "title": "Modül onayı", "description": "Tasarımlar sunuldu", "outputs": [str(Path(d) / "onay.md")]}
            p = I.kayit_yaz(task, "ONAYLANDI", "Test Kişi", "uygun")
            txt = p.read_text(encoding="utf-8")
            self.assertIn("Karar veren: Test Kişi", txt)
            self.assertIn("ONAYLANDI", txt)
            I.kayit_yaz(task, "REDDEDİLDİ", "Test Kişi", "eksik")   # geçmiş korunur (append)
            self.assertEqual(p.read_text(encoding="utf-8").count("Karar veren"), 2)


def node(script_input):
    r = subprocess.run(["node", "scripts/kesif_sema.mjs"], cwd=ROOT, input=script_input, capture_output=True, text=True, timeout=30)
    return json.loads(r.stdout)


class Sema(unittest.TestCase):
    def test_deger_saklanmaz_enum_sadece_durum_alanlarinda(self):
        out = json.dumps(node(json.dumps({"name": "Ali Veli", "email": "a@b.io", "status": "Finished", "n": 3,
                                          "id": "6abcb8c88594b2864be38ece", "at": "2026-01-02T10:00:00Z"})))
        self.assertNotIn("Ali Veli", out)
        self.assertNotIn("a@b.io", out)
        self.assertIn('"Finished"', out)
        for tip in ("email", "integer", "date-time", "id"):
            self.assertIn(tip, out)

    def test_dizi_ve_opsiyonel_alan_birlesimi(self):
        s = node(json.dumps({"tags": [{"type": "A", "at": "2026-01-01"}, {"type": "B"}]}))
        item = s["object"]["tags"]["array"]["object"]
        self.assertEqual(sorted(item["type"]["enum"]), ["A", "B"])
        self.assertIn("at?", item)                  # her örnekte yok = opsiyonel


if __name__ == "__main__":
    unittest.main()


class LivePorts(unittest.TestCase):
    def test_varsayilan_ve_config(self):
        import json as _j
        import tempfile as _t
        eski = B.WORKSPACE
        with _t.TemporaryDirectory() as d:
            B.WORKSPACE = Path(d)
            try:
                self.assertEqual(B.live_ports(), (3000, 3001))                        # config yok
                (Path(d) / "studio.config.json").write_text(_j.dumps({"live": {"ports": [3000, 8080]}}))
                self.assertEqual(B.live_ports(), (3000, 8080))
                self.assertEqual(sorted(B.live_status()), [3000, 8080])
                (Path(d) / "studio.config.json").write_text(_j.dumps({"live": {"ports": ["x"]}}))
                self.assertEqual(B.live_ports(), (3000, 3001))                        # geçersiz → varsayılan
            finally:
                B.WORKSPACE = eski
