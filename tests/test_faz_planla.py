"""Faz planlama: onay kapılı sprint ekleme (issue #249)."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import studio_board as B  # noqa: E402
import faz_planla as FP  # noqa: E402

ORG = {"hierarchy": [{"id": "sprint_planner", "stage": "design", "outputs": []},
                     {"id": "web_engineer", "stage": "build", "outputs": ["workspace/src/web/"]},
                     {"id": "qa_lead", "stage": "build", "outputs": ["workspace/docs/qa.md"]}]}
FAZ = {"id": "FAZ-2", "ad": "Stabilizasyon", "aciklama": "iyileştirme"}


def T(i, st, dep=()):
    return {"id": i, "title": i, "description": "", "role": "web_engineer", "phase": "develop", "outputs": ["workspace/x"],
            "depends_on": list(dep), "status": st, "note": "", "talep_id": None, "order": 0, "priority": 0}


def PLAN():
    return {"sprints": [{"id": "P1", "name": "Ekran düzeltmeleri", "goal": "g", "planned_days": 2, "tasks": [
        {"id": "P1-T1", "title": "yap", "description": "d", "role": "web_engineer", "phase": "develop", "outputs": ["workspace/src/web/"], "depends_on": []},
        {"id": "P1-T2", "title": "sına", "description": "d", "role": "qa_lead", "phase": "test", "outputs": ["workspace/docs/qa.md"], "depends_on": ["P1-T1"]}]},
        {"id": "P2", "name": "İkinci", "goal": "g", "tasks": [
        {"id": "P2-T1", "title": "yap2", "description": "d", "role": "web_engineer", "phase": "develop", "outputs": ["workspace/src/web/"], "depends_on": ["P1-T2"]},
        {"id": "P2-T2", "title": "sına2", "description": "d", "role": "qa_lead", "phase": "test", "outputs": ["workspace/docs/qa.md"], "depends_on": ["P2-T1"]}]}]}


class FazPlan(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.eski = B.DB_PATH
        B.DB_PATH = self.tmp / "t.db"
        self.board = B.normalize({"sprints": [{"id": "S1", "name": "s1", "order": 0, "tasks": [T("S1-T1", B.DONE)]}]})
        B.refresh(self.board)

    def tearDown(self):
        B.DB_PATH = self.eski
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _ekle(self):
        return FP.planlama_sprinti_ekle(self.board, FAZ, ORG, None, kok=self.tmp)

    def test_planlama_sprinti_plan_ve_insan_kapisi_icerir(self):
        sid = self._ekle()
        s = next(x for x in self.board["sprints"] if x["id"] == sid)
        plan_t, onay_t = FP._planlama_gorevleri(self.board, "FAZ-2")
        self.assertEqual(plan_t["role"], "sprint_planner")
        self.assertTrue(B.is_human(onay_t))
        self.assertEqual(onay_t["depends_on"], [plan_t["id"]])
        self.assertEqual(len(s["tasks"]), 2)
        self.assertTrue((self.tmp / FP.PLAN_DIZIN / "_sema.md").is_file())

    def test_onaysiz_sprint_acilmaz_onayla_eklenir(self):
        self._ekle()
        plan_t, onay_t = FP._planlama_gorevleri(self.board, "FAZ-2")
        FP.plan_yolu("FAZ-2", self.tmp).write_text(json.dumps(PLAN()), encoding="utf-8")
        B.mark(self.board, plan_t["id"], B.DONE)
        B.refresh(self.board)
        n = len(self.board["sprints"])
        FP.kontrol(self.board, ORG, None, kok=self.tmp)                    # doğrulanır, md üretilir, sprint EKLENMEZ
        self.assertEqual(len(self.board["sprints"]), n)
        self.assertTrue((self.tmp / FP.PLAN_DIZIN / "FAZ-2.md").is_file())
        B.mark(self.board, onay_t["id"], B.DONE)
        FP.kontrol(self.board, ORG, None, kok=self.tmp)
        self.assertEqual(len(self.board["sprints"]), n + 2)
        yeni = self.board["sprints"][-2:]
        ids = {t["id"] for _, t in B.all_tasks(self.board)}
        self.assertEqual(len(ids), len([1 for _ in B.all_tasks(self.board)]))     # çakışma yok
        self.assertEqual(B.validate(self.board), [])
        self.assertEqual(yeni[1]["tasks"][0]["depends_on"], [yeni[0]["tasks"][1]["id"]])   # bağımlılıklar yeniden eşlendi
        FP.kontrol(self.board, ORG, None, kok=self.tmp)                    # ikinci kez eklenmez
        self.assertEqual(len(self.board["sprints"]), n + 2)

    def test_gecersiz_plan_planlayiciya_geri_doner(self):
        self._ekle()
        plan_t, onay_t = FP._planlama_gorevleri(self.board, "FAZ-2")
        FP.plan_yolu("FAZ-2", self.tmp).write_text("bu json değil", encoding="utf-8")
        B.mark(self.board, plan_t["id"], B.DONE)
        B.refresh(self.board)
        self.assertTrue(FP.kontrol(self.board, ORG, None, kok=self.tmp))
        self.assertIn(plan_t["status"], (B.TODO, B.READY))
        self.assertIn("GEÇERSİZ PLAN", plan_t["description"])

    def test_dogrulama(self):
        self.assertEqual(FP.plan_dogrula(PLAN()), [])
        k = PLAN(); k["sprints"][0]["tasks"][1]["depends_on"] = ["YOK"]
        self.assertTrue(any("tanımsız" in e for e in FP.plan_dogrula(k)))
        k = PLAN(); k["sprints"][0]["tasks"][1]["role"] = "human"
        self.assertTrue(any("human" in e for e in FP.plan_dogrula(k)))
        k = PLAN(); k["sprints"][0]["tasks"][1]["phase"] = "develop"
        self.assertTrue(any("test" in e for e in FP.plan_dogrula(k)))
        self.assertTrue(FP.plan_dogrula({}))


if __name__ == "__main__":
    unittest.main()
