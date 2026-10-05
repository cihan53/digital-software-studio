"""ekip_yapisi.json serbest şemalı rolleri org şemasına güvenle eklenmeli (issue #211)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import studio_engine as E


class DinamikRol(unittest.TestCase):
    def test_serbest_semali_rol_normalize_edilir(self):
        r = E._normalize_dynamic_role({"id": "e2e_visitor_tester", "type": "tester", "purpose": "Akış testi",
                                       "responsibilities": ["login", "filtre"], "deliverables": ["x"], "note": "yarı otomatik"})
        for alan in ("title", "system_prompt", "inputs", "outputs", "tools"):
            self.assertIn(alan, r)
        self.assertEqual(r["outputs"], [])
        self.assertIn("Akış testi", r["system_prompt"])
        self.assertIn("- login", r["system_prompt"])

    def test_mevcut_alanlar_korunur(self):
        r = E._normalize_dynamic_role({"id": "x", "title": "T", "system_prompt": "sp", "outputs": ["workspace/docs/a.md"]})
        self.assertEqual((r["title"], r["system_prompt"], r["outputs"]), ("T", "sp", ["workspace/docs/a.md"]))

    def test_yukleme_n_calls_calisir(self):
        d = Path(tempfile.mkdtemp())
        (d / "docs").mkdir()
        (d / "docs" / "ekip_yapisi.json").write_text(json.dumps({"roles": [{"id": "perf", "purpose": "p"}, {"id": "uat_c", "responsibilities": "r"}]}))
        eski = E.WORKSPACE
        try:
            E.WORKSPACE = d
            org = E.load_and_merge_dynamic_roles({"hierarchy": [{"id": "cto", "outputs": ["a"]}]})
            self.assertEqual(sum(len(a["outputs"]) for a in org["hierarchy"]), 1)        # main()'deki n_calls artık düşmez
            self.assertEqual({a["id"] for a in org["hierarchy"]}, {"cto", "perf", "uat_c"})
        finally:
            E.WORKSPACE = eski


if __name__ == "__main__":
    unittest.main()
