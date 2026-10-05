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


class Yetenek(unittest.TestCase):
    def test_olc_ve_bilinmeyen(self):
        import yetenek_kontrol as Y
        r = Y.olc(["python3", "git", "yok-yetenek"])
        self.assertTrue(r["python3"]["ok"] and r["git"]["ok"])
        self.assertFalse(r["yok-yetenek"]["ok"])
        self.assertFalse(r["yok-yetenek"]["insan"])

    def test_profil_yoksa_insan_adimi(self):
        import os
        import yetenek_kontrol as Y
        with tempfile.TemporaryDirectory() as d:
            os.environ["STUDIO_KESIF_PROFIL"] = d
            try:
                r = Y.k_kesif_profili()
            finally:
                del os.environ["STUDIO_KESIF_PROFIL"]
        self.assertFalse(r["ok"])
        self.assertTrue(r["insan"])                 # giriş = insan adımı, studio kendiliğinden yapmaz

    def test_koruma_degismeyen_dosya(self):
        import koruma_kontrol as K
        self.assertEqual(K.degisenler("HEAD", ["scripts/koruma_kontrol.py"]) is not None, True)
        self.assertEqual(K.main(["--dosyalar", "LICENSE"]), 0)


class KosucuDayanikliligi(unittest.TestCase):
    def test_yerel_ortam_cikti_izni_ve_workspace_disi_red(self):
        import studio_engine as E
        self.assertEqual(E.check_output_path("workspace/yerel_ortam.sh").name, "yerel_ortam.sh")   # planlayıcı kuralı: workspace içine
        for kotu in ("yerel_ortam.sh", "baska/dosya.sh"):
            with self.assertRaises(ValueError):                                                   # workspace dışı hâlâ reddedilir
                E.check_output_path(kotu)

    def test_org_chart_yerel_ortam_workspace_icinde(self):
        import re as _re
        s = (ROOT / "org_chart.json").read_text(encoding="utf-8")
        self.assertEqual(_re.findall(r"(?<!workspace/)yerel_ortam\.sh", s), [])

    def test_updater_calistirma_izni_korur(self):
        import stat
        import tempfile as _t
        import studio_updater as U
        with _t.TemporaryDirectory() as d:
            kaynak = Path(d) / "k.sh"
            kaynak.write_text("#!/bin/sh\n")
            kaynak.chmod(0o755)
            hedef = Path(d) / "alt" / "h.sh"
            self.assertTrue(U.dosya_guncelle(hedef, kaynak))
            self.assertTrue(hedef.stat().st_mode & stat.S_IXUSR)


class Yalitim(unittest.TestCase):
    def test_resolve_script_workspace_oncelikli(self):
        import tempfile as _t
        import studio_engine as E
        with _t.TemporaryDirectory() as d:
            eskiw, eskir = E.WORKSPACE, E.ROOT
            E.WORKSPACE, E.ROOT = Path(d) / "workspace", Path(d)
            try:
                (Path(d) / "scripts").mkdir()
                (Path(d) / "scripts" / "a.mjs").write_text("fw")
                self.assertEqual(E.resolve_script("a.mjs"), Path(d) / "scripts" / "a.mjs")            # override yok → framework
                (Path(d) / "workspace" / "scripts").mkdir(parents=True)
                (Path(d) / "workspace" / "scripts" / "a.mjs").write_text("proje")
                self.assertEqual(E.resolve_script("a.mjs"), Path(d) / "workspace" / "scripts" / "a.mjs")  # override kazanır
            finally:
                E.WORKSPACE, E.ROOT = eskiw, eskir


class GorevGirdileri(unittest.TestCase):
    def test_girdi_satiri_dosya_dizin_okur_disari_cikmaz(self):
        import tempfile as _t
        import studio_engine as E
        with _t.TemporaryDirectory() as d:
            root = Path(d)
            (root / "workspace" / "docs" / "ekranlar" / "m").mkdir(parents=True)
            (root / "workspace" / "docs" / "ekranlar" / "m" / "a.md").write_text("ALAN-A")
            (root / "workspace" / "docs" / "ekranlar" / "m" / "_gizli.md").write_text("GIZLI")
            (root / "workspace" / "docs" / "t.json").write_text('{"x":1}')
            (root / "disari.md").write_text("DISARI")
            metin = E.gorev_girdileri("Aç. Girdi: workspace/docs/ekranlar/m, workspace/docs/t.json, ../disari.md, disari.md", root)
            self.assertIn("ALAN-A", metin)
            self.assertIn('{"x":1}', metin)
            self.assertNotIn("GIZLI", metin)                 # _ ile başlayanlar alınmaz
            self.assertNotIn("DISARI", metin)                # workspace dışı yol okunmaz
            self.assertEqual(E.gorev_girdileri("girdi yok", root), "")

    def test_okunamadi_beyani_yakalanir(self):
        import studio_engine as E
        d = "Tasarla. Girdi: workspace/docs/a.md"
        self.assertTrue(E._girdi_beyani_hatasi(d, "> **Varsayım:** `a.md` bu görevde okunamadı (okuma izni yok)."))
        self.assertTrue(E._girdi_beyani_hatasi(d, "GİRDİ-EKSİK: workspace/docs/a.md\n..."))
        self.assertFalse(E._girdi_beyani_hatasi(d, "> **Varsayım:** modal alanları bilinmiyor, ikinci tur keşif."))
        self.assertFalse(E._girdi_beyani_hatasi("Girdi yok görevi", "okunamadı"))   # Girdi: yoksa kapı çalışmaz
