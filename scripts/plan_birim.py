#!/usr/bin/env python3
"""Birim-envanteri tabanlı plan üretici (issue #171) — LLM'siz, deterministik.

Keşif envanterinden (scripts/birim_envanteri.py) her modül için şu zinciri üretir:
  tasarım (ui) → İNSAN KAPISI → mock (API'si varsa) → ekran → parite testi
Birimi `planlama.parca`'dan fazla modüllerde tasarım ve ekran görevleri parçalara bölünür. Her göreve `Girdi:` (ekran analizi, modül özeti,
API şema dilimi, tasarım) eklenir; kapıya `İncele:`; tasarım görevine isteğe bağlı HTML önizleme. Genel iskelet: kabuk/altyapı sprint'i ve
son kabul sprint'i (insan kapısıyla). Yapılandırma: studio.config.json → planlama.

  python3 scripts/plan_birim.py [--dry-run]     # panoyu yazmadan özet
  python3 scripts/plan_birim.py --yaz           # mevcut panoyu yedekleyip yeni panoyu yazar (koşucu durmuşken)
"""
from __future__ import annotations

import argparse
import math
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import studio_config as C  # noqa: E402
import birim_envanteri as BE  # noqa: E402

HTML_TALIMAT = ("Tasarım dokümanına EK OLARAK tek dosyalık STATİK HTML önizleme üret ({html}): satır içi CSS, betik YOK, harici kaynak YOK; "
                "her ekran için ayrı bölüm; sticky başlık (ekran adı + filtre barı + aksiyonlar), widget/tablo/modal-çekmece yerleşimi ve "
                "boş/hata/yükleme durumları görsel olarak gösterilsin. Sayı/isim/kişi verisi UYDURMA: veri alanlarında 'veri yok' iskeleti kullan.")


def _tag(mod: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "", mod.upper().replace("-", "")) or "MOD"


def _satir(u: dict) -> str:
    n = f" [{u['not']}]" if u["not"] else ""
    return f"{u['rota']} (widget {u['widget']}, kolon {u['kolon']}, grafik {u['grafik']}, modal {u['modal']}, api {u['api']}; erişim: {u['erisim']}){n}"


def _parcala(units: list[dict], n: int) -> list[list[dict]]:
    return [units[i:i + n] for i in range(0, len(units), n)] or [[]]


def modul_gorevleri(sid: str, mod: str, units: list[dict], P: dict, out_rel: str, onceki: list[str], mock_bag: list[str], api_var: bool) -> list[dict]:
    d, r = P["dizinler"], P["roller"]
    kural = (" Kurallar: " + " ".join(P["kurallar"])) if P["kurallar"] else ""
    ekran = f"{out_rel}/{mod}"
    ozet, api = f"{out_rel}/_modul/{mod}.md", f"{out_rel}/_api/{mod}.json"
    tasarim_md, tasarim_html = f"{d['tasarim']}/{mod}*.md", f"{d['tasarim']}/{mod}*.html"
    parcalar = _parcala(units, P["parca"])
    tag = _tag(mod)
    gor, dids, wids = [], [], []
    for i, g in enumerate(parcalar, 1):
        gid = f"{sid}-{tag}-D{i}" if len(parcalar) > 1 else f"{sid}-{tag}-D"
        dids.append(gid)
        aciklama = (f"{mod} modülü ekranlarının tasarımı (widget, filtre, modal/çekmece, boş/hata/yükleme/yetkisiz durumlar dahil): "
                    + "; ".join(_satir(u) for u in g) + "." + kural + f" Girdi: {ekran}, {ozet}, {api}")
        cik = [f"{d['tasarim']}/{mod}{'-' + str(i) if len(parcalar) > 1 else ''}.md"]
        if P["html_onizleme"] and i == 1:
            h = f"{d['tasarim']}/{mod}.html"
            cik.append(h)
            aciklama += " " + HTML_TALIMAT.format(html=h)
        gor.append({"id": gid, "title": f"{mod}: ekran tasarımı" + (f" ({i}/{len(parcalar)})" if len(parcalar) > 1 else ""), "description": aciklama,
                    "role": r["tasarim"], "phase": "develop", "outputs": cik, "depends_on": list(onceki)})
    onay_dep = dids
    if P["insan_kapisi"]:
        kapi = f"{sid}-{tag}-G"
        gor.append({"id": kapi, "title": f"{mod}: müşteri tasarım onayı", "role": "human", "phase": "test",
                    "description": f"İNSAN KAPISI. {mod} tasarımları sunulur; onay/ret panelde ✅ Onaylar sekmesinden verilir. Onaysız modülün mock/ekran görevleri başlamaz. "
                                   f"İncele: {tasarim_md}, {tasarim_html}, {ekran}",
                    "outputs": [f"{d['onay']}/{mod}.md"], "depends_on": dids})
        onay_dep = [kapi]
    bagimli = onay_dep + list(mock_bag)
    if api_var:
        bid = f"{sid}-{tag}-B"
        gor.append({"id": bid, "title": f"{mod}: mock uçları (gözlenen şemadan)", "role": r["mock"], "phase": "develop",
                    "description": f"{mod} ekranlarının çağırdığı uçlar için mock; şema kaynağı {api} (alan adı/tip; değer YOK). Değer/isim/sayı uydurma, kişisel veri yok; "
                                   f"enum alanlarında yalnız şemadaki değerler; şemada olmayan alan eklenmez.{kural} Girdi: {tasarim_md}, {api}, {ozet}",
                    "outputs": [f"{d['mock']}/{mod}/"], "depends_on": bagimli})
        bagimli = [bid]
    for i, g in enumerate(parcalar, 1):
        wid = f"{sid}-{tag}-W{i}" if len(parcalar) > 1 else f"{sid}-{tag}-W"
        wids.append(wid)
        gor.append({"id": wid, "title": f"{mod}: ekranlar" + (f" ({i}/{len(parcalar)})" if len(parcalar) > 1 else ""), "role": r["ekran"], "phase": "develop",
                    "description": "Onaylı tasarıma göre çalışan ekranlar: " + "; ".join(_satir(u) for u in g) + f". Dizin: {d['ekran']}/{mod}/{{pages,widgets,modals,composables,api}}. "
                                   f"Widget kendi verisini çeker; ortak başlık bileşeni; erişim ekran dokümanındaki gibi.{kural} "
                                   f"Girdi: {tasarim_md}, {tasarim_html}, {ekran}, {ozet}, {api}",
                    "outputs": [f"{d['ekran']}/{mod}/"], "depends_on": list(bagimli)})
    gor.append({"id": f"{sid}-{tag}-Q", "title": f"{mod}: parite testi ve checklist", "role": r["parite"], "phase": "test",
                "description": f"{mod} için ekran dokümanlarına karşı parite: widget, tablo kolonu, filtre, modal/çekmece, durumlar ve rol/menü erişimi (pozitif ve negatif). "
                               f"Yalnız geçen ekrana [✓]; çalıştırılmadan GEÇTİ yazılamaz, kanıt ekle. Sabit değer/uydurma veri taraması. Girdi: {ekran}, {ozet}, {tasarim_md}",
                "outputs": [f"{d['parite']}/{mod}.md"], "depends_on": wids})
    return gor


def iskelet(P: dict) -> tuple[dict, dict, list[str]]:
    """Genel ilk (kabuk/altyapı) ve son (kabul) sprint'ler. Projeye özel ayrıntı planlama.kurallar/kapsam dosyasındadır."""
    s1 = {"id": "S1", "name": "Temel kabuk, altyapı ve mock", "goal": "Yerel ortam tek komutla kalkar; kabuk (layout, tema, erişim zinciri, ortak bileşenler) ve mock altyapısı hazırdır.",
          "tasks": [
              {"id": "S1-T1", "title": "Yerel ortam ve CI", "role": "devops_engineer", "phase": "develop", "outputs": ["workspace/yerel_ortam.sh", "workspace/ci_cd_pipeline.yml", "workspace/infra/"],
               "description": "workspace/yerel_ortam.sh (tek komutla servisler; proje kökünü kendi konumundan bulur) ve CI. Mevcut dizin yapısını önce incele.", "depends_on": []},
              {"id": "S1-T2", "title": "Uygulama kabuğu ve ortak bileşenler", "role": "web_engineer", "phase": "develop", "outputs": ["workspace/src/web/"],
               "description": "Layout, tema, erişim zinciri (canlı şemadan: _api_semalari.json), ortak başlık/widget/modal bileşenleri, i18n.", "depends_on": ["S1-T1"]},
              {"id": "S1-T3", "title": "Mock API altyapısı", "role": "backend_engineer", "phase": "develop", "outputs": ["workspace/src/backend/"],
               "description": "Mock altyapısı ve oturum/erişim uçları; veri kaynağı gözlenen şemalar (uydurma değer yok).", "depends_on": ["S1-T1"]},
              {"id": "S1-T4", "title": "Kabuk smoke testi ve erişim matrisi", "role": "qa_lead", "phase": "test", "outputs": ["workspace/docs/test_raporu.md"],
               "description": "Kabuk ve rol/menü erişim matrisi (pozitif+negatif). Çalıştırılmadan GEÇTİ yazılamaz.", "depends_on": ["S1-T2", "S1-T3"]}]}
    son = {"id": "SON", "name": "Regresyon, kabul ve paketleme", "goal": "Tüm ekranlar parite testinden geçti; paket hazır; müşteri nihai kabulü alındı.",
           "tasks": [
               {"id": "SON-T1", "title": "Tam ziyaretçi yolculuğu denetimi", "role": "screen_visitor_tester", "phase": "test", "outputs": ["workspace/docs/ziyaretci_ekran_denetimi.md"],
                "description": "Tüm rotaları gez; çalıştırılmadan GEÇTİ yazılamaz.", "depends_on": []},
               {"id": "SON-T2", "title": "Hata düzeltmeleri ve paket boyutu", "role": "web_engineer", "phase": "develop", "outputs": ["workspace/src/web/"],
                "description": "Denetim bulgularını kapat; bundle bütçesi.", "depends_on": ["SON-T1"]},
               {"id": "SON-T3", "title": "Üretim paketi", "role": "devops_engineer", "phase": "deploy", "outputs": ["workspace/infra/"],
                "description": "Üretim imajı ve dağıtım betiği.", "depends_on": ["SON-T2"]},
               {"id": "SON-T4", "title": "UAT kabul raporu", "role": "uat_auditor", "phase": "test", "outputs": ["workspace/docs/uat_kabul_raporu.md"],
                "description": "Çalıştırılan UAT; kanıtlı.", "depends_on": ["SON-T3"]},
               {"id": "SON-T5", "title": "Müşteri nihai kabulü", "role": "human", "phase": "test", "outputs": [f"{P['dizinler']['onay']}/nihai_kabul.md"],
                "description": "İNSAN KAPISI. UAT raporu ve canlı sistem incelenir; onay panelden verilir. İncele: workspace/docs/uat_kabul_raporu.md", "depends_on": ["SON-T4"]}]}
    return s1, son, ["S1-T2", "S1-T3"]


def uret(cfg: dict | None = None) -> dict:
    cfg = cfg or C.load_config() or {}
    P = cfg.get("planlama") or C.DEFAULTS["planlama"]
    out_rel = cfg["analysis"]["output_dir"]
    out = ROOT / out_rel
    rows = BE.yukle(out)
    moduller: dict[str, list[dict]] = {}
    for r in rows:
        if r["modul"] not in P["atla_modulleri"]:
            moduller.setdefault(r["modul"], []).append(r)
    ortak = BE.ortak_uclar(out, len(rows))
    sema = {}
    if (out / "_api_semalari.json").exists():
        import json
        sema = json.loads((out / "_api_semalari.json").read_text(encoding="utf-8"))
    # sprint dağıtımı
    if P["sprintler"]:
        gruplar = [(g["ad"], [m for m in g["moduller"] if m in moduller]) for g in P["sprintler"]]
    else:
        n = max(1, math.ceil(sum(len(v) for v in moduller.values()) / max(1, P["sprint_birim"])))
        kovalar = [[0, []] for _ in range(n)]
        for m in sorted(moduller, key=lambda m: -len(moduller[m])):          # büyükten küçüğe, en boş sprint'e
            k = min(kovalar, key=lambda x: x[0])
            k[0] += len(moduller[m])
            k[1].append(m)
        gruplar = [(f"Modüller {i}", sorted(k[1])) for i, k in enumerate(kovalar, 1) if k[1]]
    s1, son, mock_bag = iskelet(P)
    sprintler = [s1]
    for i, (ad, mods) in enumerate(gruplar, 2):
        sid = f"S{i}"
        gor = []
        for m in mods:
            uclar = [k for k, v in sema.items() if set(v.get("birimler", [])) & {u["rota"] for u in moduller[m]} and k not in ortak]
            gor += modul_gorevleri(sid, m, moduller[m], P, out_rel, ["S1-T2"] if i == 2 else [], mock_bag, bool(uclar))
        sprintler.append({"id": sid, "name": ad, "goal": f"{', '.join(mods)} modülleri onaylı tasarımla çalışıyor ve parite testinden geçiyor.", "tasks": gor})
    son["id"] = f"S{len(sprintler) + 1}"
    for t in son["tasks"]:
        t["id"] = t["id"].replace("SON", son["id"])
        t["depends_on"] = [d.replace("SON", son["id"]) for d in t["depends_on"]]
    sprintler.append(son)
    return {"created_at": datetime.now().isoformat(timespec="seconds"), "sprints": sprintler}


def ozet(board: dict) -> str:
    import studio_board as B
    toplam = sum(len(s["tasks"]) for s in board["sprints"])
    insan = sum(1 for s in board["sprints"] for t in s["tasks"] if t["role"] == "human")
    return f"{len(board['sprints'])} sprint, {toplam} görev ({insan} insan kapısı)"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--yaz", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    import studio_board as B
    board = uret()
    B.normalize(board)
    errs = B.validate(board)
    print(ozet(board))
    for s in board["sprints"]:
        print(f"  {s['id']}: {len(s['tasks'])} görev — {s['name']}")
    if errs:
        print("[HATA] doğrulama:\n  " + "\n  ".join(errs[:15]))
        return 1
    if a.yaz and not a.dry_run:
        (ROOT / "workspace" / ".yedek").mkdir(parents=True, exist_ok=True)
        if B.DB_PATH.exists():
            shutil.copy2(B.DB_PATH, ROOT / "workspace" / ".yedek" / f"studio.db.plan-birim-oncesi-{datetime.now():%Y%m%d-%H%M%S}")
        B.board_reset()
        B.refresh(board)
        B.save(board)
        B.audit("plan_birim", "plan_yazildi", detay={"ozet": ozet(board)})
        print("pano yazıldı.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
