"""Birim-envanteri tabanlı plan üretici (issue #171)."""
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
import studio_config as C  # noqa: E402
import birim_envanteri as BE  # noqa: E402
import plan_birim as PB  # noqa: E402


def kur(tmp: Path) -> dict:
    out = tmp / "workspace" / "docs" / "ekranlar"
    (out / "_ham").mkdir(parents=True)
    rotalar = {"/a": 1, "/a/x": 1, "/b": 1}
    for i in range(10):                                         # 10 birimli büyük modül (parça=8 → 2 parça)
        rotalar[f"/buyuk/{i}"] = 1
    durum = {}
    for r in rotalar:
        slug = BE.slug(r)
        (out / "_ham" / f"{slug}.json").write_text(json.dumps({"birim": r, "durum": "tamam", "wid": ["w"], "th": ["k"], "cv": 0, "modals": [], "api": ["/api/z"]}))
        durum[r] = "tamam"
    (out / "_ham" / "_durum.json").write_text(json.dumps({"bitti": durum}))
    (out / "_api_semalari.json").write_text(json.dumps({"GET /api/a": {"durum": 200, "sema": "x", "birimler": ["/a", "/a/x"]},
                                                         "GET /api/ortak": {"durum": 200, "sema": "x", "birimler": list(rotalar)}}))
    cfg = C._merge(C.DEFAULTS, {"analysis": {"output_dir": str(out)}})
    cfg["planlama"]["uretici"] = "birim"
    cfg["planlama"]["sprint_birim"] = 8
    return cfg


class PlanBirim(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg = kur(self.tmp)
        self.eski = PB.ROOT
        PB.ROOT = Path("/")                                      # output_dir mutlak yol

    def tearDown(self):
        PB.ROOT = self.eski
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_zincir_kapi_parcalama_girdi(self):
        b = B.normalize(PB.uret(self.cfg))
        self.assertEqual(B.validate(b), [])
        gor = {t["id"]: t for _, t in B.all_tasks(b)}
        d = [t for t in gor.values() if t["id"].endswith("BUYUK-D1") or t["id"].endswith("BUYUK-D2")]
        self.assertEqual(len(d), 2)                              # 10 birim / parça 8 → 2 tasarım parçası
        a_d = next(t for t in gor.values() if t["id"].endswith("-A-D"))
        a_g = next(t for t in gor.values() if t["id"].endswith("-A-G"))
        a_b = next(t for t in gor.values() if t["id"].endswith("-A-B"))
        a_w = next(t for t in gor.values() if t["id"].endswith("-A-W"))
        self.assertEqual(a_g["role"], "human")
        self.assertIn("Girdi:", a_d["description"])
        self.assertTrue(any(o.endswith("/a.html") for o in a_d["outputs"]))   # HTML önizleme
        self.assertIn("İncele:", a_g["description"])
        self.assertEqual(a_b["depends_on"][0], a_g["id"])                      # mock, kapıdan sonra
        self.assertIn(a_b["id"], a_w["depends_on"])                            # ekran mock'tan sonra

    def test_api_yoksa_mock_gorevi_yok_ortak_uc_haric(self):
        b = B.normalize(PB.uret(self.cfg))
        ids = [t["id"] for _, t in B.all_tasks(b)]
        self.assertTrue(any(i.endswith("-A-B") for i in ids))                  # /a modülüne özgü uç var
        self.assertFalse(any(i.endswith("-B-B") for i in ids))                 # /b yalnız ortak uç çağırıyor → mock görevi yok

    def test_son_sprint_insan_kabul_kapisi(self):
        b = B.normalize(PB.uret(self.cfg))
        son = b["sprints"][-1]
        self.assertEqual(son["tasks"][-1]["role"], "human")
        self.assertTrue(all(d in {t["id"] for _, t in B.all_tasks(b)} for t in son["tasks"] for d in t["depends_on"]))

    def test_atla_modulleri(self):
        self.cfg["planlama"]["atla_modulleri"] = ["buyuk"]
        b = B.normalize(PB.uret(self.cfg))
        self.assertFalse(any("BUYUK" in t["id"] for _, t in B.all_tasks(b)))


if __name__ == "__main__":
    unittest.main()
