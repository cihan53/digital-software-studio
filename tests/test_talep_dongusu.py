"""UAT kapısı yalnız canlı gerektiren görevlerde; talep sonsuz yeniden sprinte alınmaz (issue #281)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import studio_board as B  # noqa: E402
import studio_engine as E  # noqa: E402
import studio_yetkilisi as SY  # noqa: E402


def T(i, st, title="x", role="web_engineer", talep=None):
    return {"id": i, "title": title, "description": "", "role": role, "phase": "develop", "outputs": ["workspace/x"],
            "depends_on": [], "status": st, "note": "", "talep_id": talep, "order": 0, "priority": 0}


class Dongu(unittest.TestCase):
    def test_planlayici_gorevi_uat_kelimesiyle_uat_kapisina_girmez(self):
        t = {"id": "S26-T1", "title": "FAZ-1 sprint planı", "role": "sprint_planner", "phase": "develop",
             "description": "Önceki faz sonuçlarını (UAT/render/hata raporları) oku", "outputs": []}
        with mock.patch.object(E, "resolve_script", side_effect=AssertionError("UAT betiği çağrılmamalı")):
            self.assertEqual(E._verify_task_execution_core(t, {"id": "S26"}), "")

    def test_plan_gorevi_icin_otomatik_talep_acilmaz(self):
        self.assertIsNone(E._auto_talep_uat({"id": "S26-T1", "role": "sprint_planner", "title": "plan"}, "hata"))

    def test_talep_sprint_sinirinda_insan_gerekliye_cekilir(self):
        sprintler = [{"id": f"S{i}", "name": "n", "order": i, "tasks": [T(f"S{i}-T1", B.SKIPPED, "[TALEP-009] düzelt", talep="TALEP-009")]} for i in range(1, 4)]
        board = {"sprints": sprintler}
        talep = {"id": "TALEP-009", "durum": "GELISTIRILIYOR", "tur": "HATA", "baslik": "b"}
        guncel = []
        with mock.patch.object(B, "load", return_value=board), mock.patch.object(B, "reconcile_talepler_and_board", return_value=None), \
                mock.patch.object(B, "audit"), mock.patch.object(SY.MT, "load_data", return_value={"talepler": [talep]}), \
                mock.patch.object(SY.MT, "guncelle", side_effect=lambda tid, **kw: guncel.append((tid, kw))):
            self.assertEqual(SY.otomatik_musteri_talepleri_senkronize_et(), 0)
        self.assertEqual(guncel[0][0], "TALEP-009")
        self.assertEqual(guncel[0][1]["durum"], "INSAN_GEREKLI")


if __name__ == "__main__":
    unittest.main()
