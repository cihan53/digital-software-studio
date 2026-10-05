"""Uygulama dizini sözleşmesi (issue #195)."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import uygulama_dizini as UD


def pano():
    return {"sprints": [{"id": "S1", "tasks": [
        {"id": "S1-T1", "role": "devops_engineer", "phase": "develop", "outputs": ["workspace/yerel_ortam.sh", "workspace/infra/"],
         "description": "Tek komutla ortam."},
        {"id": "S1-T2", "role": "web_engineer", "phase": "develop", "outputs": ["workspace/src/frontend/"], "description": "Nuxt iskeleti."},
        {"id": "S1-T3", "role": "product_owner", "phase": "design", "outputs": ["workspace/docs/x.md"], "description": "Tasarım."},
        {"id": "S1-T4", "role": "human", "phase": "test", "outputs": ["workspace/docs/onay.md"], "description": "İNSAN KAPISI."},
        {"id": "S1-T5", "role": "backend_engineer", "phase": "develop", "outputs": ["workspace/src/backend/"], "description": "Mock."}]}]}


class UygulamaDizini(unittest.TestCase):
    def test_varsayilan_ve_config(self):
        self.assertEqual(UD.dizin(None), "workspace/src/web")
        self.assertEqual(UD.dizin({"planlama": {"dizinler": {"uygulama": "workspace/src/app/"}}}), "workspace/src/app")

    def test_devops_ve_web_ayni_dizini_kullanir(self):
        b = pano()
        kok = Path(tempfile.mkdtemp())
        UD.uygula(b, None, kok)
        t = {x["id"]: x for x in b["sprints"][0]["tasks"]}
        self.assertEqual(t["S1-T2"]["outputs"], ["workspace/src/web/"])                  # frontend takma adı sözleşmeye çekilir
        for i in ("S1-T1", "S1-T2", "S1-T5"):
            self.assertIn("workspace/src/web/", t[i]["description"], i)                  # her ilgili görev aynı dizini taşır
        self.assertIn("keşfeder", t["S1-T1"]["description"])                              # yerel_ortam.sh dizini sabit yazmaz
        self.assertNotIn(UD.MARKER, t["S1-T3"]["description"])                          # tasarım görevi etkilenmez
        self.assertNotIn(UD.MARKER, t["S1-T4"]["description"])                          # insan kapısı etkilenmez
        self.assertEqual(t["S1-T5"]["outputs"], ["workspace/src/backend/"])             # backend dizinine dokunulmaz

    def test_idempotent_ve_teknoloji_girdisi(self):
        kok = Path(tempfile.mkdtemp())
        (kok / "workspace/docs").mkdir(parents=True)
        (kok / "workspace/docs/teknoloji_stack_karari.md").write_text("x")
        b = pano()
        UD.uygula(b, None, kok)
        ilk = b["sprints"][0]["tasks"][0]["description"]
        self.assertIn("Girdi: workspace/docs/teknoloji_stack_karari.md", ilk)
        self.assertEqual(UD.uygula(b, None, kok), 0)                                    # ikinci çalıştırma değişiklik yapmaz
        self.assertEqual(b["sprints"][0]["tasks"][0]["description"], ilk)

    def test_planlayici_notu(self):
        self.assertIn("workspace/src/web/", UD.planlayici_notu(None))


if __name__ == "__main__":
    unittest.main()
