"""Canlı sistem beklemesi panoyu kilitlememeli (issue #219)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import studio_board as B


def gorev(i, durum="READY", rol="web_engineer", baslik="x", **kw):
    return {"id": i, "title": baslik, "description": "", "role": rol, "phase": "develop", "outputs": [], "depends_on": [], "status": durum, "order": 0, **kw}


class CanliBekleme(unittest.TestCase):
    def test_needs_live_ve_filtre(self):
        uat = gorev("S1-T1", rol="uat_auditor", baslik="UAT kabul")
        web = gorev("S1-T2")
        board = {"sprints": [{"id": "S1", "order": 0, "tasks": [uat, web]}]}
        self.assertTrue(B.needs_live(uat))
        self.assertEqual(B.next_ready(board)[1]["id"] in ("S1-T1", "S1-T2"), True)
        self.assertEqual(B.next_ready(board, uygun=lambda t: not B.needs_live(t))[1]["id"], "S1-T2")   # canlı gerektirmeyen seçilir

    def test_yalniz_canli_gorev_varsa_alternatif_yok(self):
        uat = gorev("S6-T2", rol="uat_auditor", baslik="UAT", talep_id="TALEP-001")
        board = {"sprints": [{"id": "S1", "order": 0, "tasks": [gorev("S1-T2", durum="SKIPPED", note="telafi TALEP-001 talebine devredildi"), gorev("S1-T3", durum="TODO")]},
                             {"id": "S6", "order": 5, "tasks": [uat]}]}
        self.assertEqual(B.next_ready(board)[1]["id"], "S6-T2")                                      # telafi sprinti sırayı atlar
        self.assertEqual(B.next_ready(board, uygun=lambda t: not B.needs_live(t)), (None, None))      # alternatif yok → motor SKIP/bekleme kararı verir

    def test_live_baslatilabilir(self):
        d = Path(tempfile.mkdtemp())
        eski = (B.WORKSPACE, B.ROOT)
        try:
            B.WORKSPACE, B.ROOT = d / "workspace", d
            (d / "workspace").mkdir()
            self.assertFalse(B.live_baslatilabilir())
            (d / "workspace" / "yerel_ortam.sh").write_text("#!/bin/sh\n")
            self.assertTrue(B.live_baslatilabilir())
        finally:
            B.WORKSPACE, B.ROOT = eski


if __name__ == "__main__":
    unittest.main()
