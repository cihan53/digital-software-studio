#!/usr/bin/env python3
"""Faz planlama (issue #249): aktif faz için sprintleri planlayıcı üretir, insan onaylar, panoya EKLENİR.

Akış (hepsi mevcut panoya sprint olarak eklenir; var olan işe dokunulmaz):
  1. `planlama_sprinti_ekle`  → "Faz planlama" sprinti: T1 sprint_planner planı JSON yazar,
                                T2 `role: human` onay kapısı (panel Onaylar sekmesi).
  2. `kontrol`                → her koşucu turunda: T1 bitti → plan doğrulanır (geçersizse T1 hata
                                listesiyle yeniden açılır), insan okunur .md üretilir;
                                T2 onaylandı → plan sprintleri panoya eklenir (bir kez).
  3. Ret = insan_onayi.py revizyonu: T1 notla yeniden çalışır, plan dosyası ezilir.

Plan dosyası: workspace/docs/faz_planlari/<FAZ>.json  (uygulandı işareti: <FAZ>.uygulandi)
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import studio_board as B  # noqa: E402

PLAN_DIZIN = "workspace/docs/faz_planlari"
EN_FAZLA_SPRINT, EN_FAZLA_GOREV = 5, 6


def plan_yolu(faz_id: str, kok: Path = ROOT) -> Path:
    return kok / PLAN_DIZIN / f"{faz_id}.json"


def uygulandi_yolu(faz_id: str, kok: Path = ROOT) -> Path:
    return kok / PLAN_DIZIN / f"{faz_id}.uygulandi"


def _planlama_gorevleri(board: dict, faz_id: str):
    """(plan görevi, onay görevi) — plan görevi çıktısından tanınır; yoksa (None, None)."""
    hedef = f"{PLAN_DIZIN}/{faz_id}.json"
    for _, t in B.all_tasks(board):
        if hedef in (t.get("outputs") or []) and not B.is_human(t):
            onay = next((x for _, x in B.all_tasks(board) if B.is_human(x) and t["id"] in x.get("depends_on", [])), None)
            return t, onay
    return None, None


def aktif_faz(kok: Path = ROOT) -> tuple[dict | None, int]:
    try:
        import karar_verici_triage as KVT
        fazlar = KVT.load_fazlar().get("fazlar", [])
    except Exception:
        return None, -1
    for i, f in enumerate(fazlar):
        if f.get("durum") == "AKTIF":
            return f, i
    return None, -1


def gerekli(board: dict, kok: Path = ROOT) -> dict | None:
    """Otomatik tetik: aktif faz ilk faz DEĞİL (ilk faz panoyla planlanır), pano tamamen kapalı (boşta) ve
    bu faz için plan sprinti yok. Plan gerekiyorsa faz kaydını döndürür."""
    faz, idx = aktif_faz(kok)
    if faz is None or idx <= 0:
        return None
    if any(t["status"] not in B.TERMINAL for _, t in B.all_tasks(board)):
        return None
    if _planlama_gorevleri(board, faz["id"])[0] is not None or plan_yolu(faz["id"], kok).exists():
        return None
    return faz


def sema_metni(org: dict) -> str:
    roller = "\n".join(f'- "{a["id"]}" → çıktıları: {", ".join(a.get("outputs", []))}'
                       for a in org.get("hierarchy", []) if a.get("stage") == "build")
    return f"""# Faz planı çıktı şeması

Yalnızca GEÇERLİ JSON üret (kod çiti ve açıklama YOK):
{{"sprints": [{{"id": "P1", "name": "kısa ad", "goal": "sprint sonunda çalışır olacak şey", "planned_days": 3,
  "tasks": [{{"id": "P1-T1", "title": "...", "description": "en fazla 25 kelime", "role": "aşağıdaki rollerden biri",
    "phase": "develop | test | deploy", "outputs": ["workspace/... yol"], "depends_on": ["yalnız bu plandaki görev id'leri"]}}]}}]}}

Kurallar: en fazla {EN_FAZLA_SPRINT} sprint, sprint başına en fazla {EN_FAZLA_GOREV} görev; her sprintte en az bir develop ve bir test görevi;
test görevi geliştirmeye bağlı; her sprint gösterilebilir bir dilim üretir (katman değil). Sprint/görev id'lerini P1, P1-T1 biçiminde ver
(motor panoya eklerken yeniden numaralandırır). Zaten bitmiş işi tekrar planlama; yalnız bu fazın kalan kapsamını planla.
Rol adları yalnızca şu listeden, birebir:
{roller}
"""


def planlama_sprinti_ekle(board: dict, faz: dict, org: dict, cfg: dict | None = None, kok: Path = ROOT) -> str:
    """Panoya 'Faz planlama' sprinti ekler (T1 plan, T2 insan onayı). Eklenen sprint id'sini döndürür."""
    fid = faz["id"]
    d = kok / PLAN_DIZIN
    d.mkdir(parents=True, exist_ok=True)
    (d / "_sema.md").write_text(sema_metni(org), encoding="utf-8")
    girdiler = ", ".join(g for g in (
        "proje_kapsami.md", "workspace/docs/backlog.md", "workspace/docs/ekran_envanteri.md",
        "workspace/docs/kabul_kriterleri.md", "workspace/docs/fazlar.json", f"{PLAN_DIZIN}/_sema.md",
        "workspace/docs/uat_kabul_raporu*.md", "workspace/docs/render_raporu*.md",
        "workspace/docs/bug_raporlari.md") if "*" in g or (kok / g).exists())
    sid = f"S{len(board.get('sprints', [])) + 1}"
    ad = faz.get("ad", fid)
    plan_o = f"{PLAN_DIZIN}/{fid}.json"
    onay_o = f"{PLAN_DIZIN}/{fid}_onay.md"
    sprint = {
        "id": sid, "name": f"Faz planlama — {fid}", "goal": f"{fid} ({ad}) için sprintlerin planlanması ve insan onayı",
        "planned_days": 1,
        "tasks": [
            {"id": f"{sid}-T1", "title": f"{fid} sprint planı", "role": "sprint_planner", "phase": "develop",
             "description": (f"{fid} fazını planla: «{ad}» — {faz.get('aciklama', '')}. Brief, backlog, ekran envanteri ve önceki faz sonuçlarını "
                             f"(UAT/render/hata raporları, açık bulgular) oku; fazın KALAN kapsamını sprintlere böl. Şema ve kurallar _sema.md'de. "
                             f"Çıktı yalnız JSON. Girdi: {girdiler}"),
             "outputs": [plan_o], "depends_on": []},
            {"id": f"{sid}-T2", "title": f"{fid} planı insan onayı", "role": "human", "phase": "test",
             "description": f"İnsan onayı: {PLAN_DIZIN}/{fid}.md planını oku. Onay → sprintler panoya eklenir; ret (gerekçeli) → plan notla yeniden üretilir.",
             "outputs": [onay_o], "depends_on": [f"{sid}-T1"]},
        ],
    }
    B.append_sprint(board, sprint)
    B.audit("engine", "faz_planlama_baslatildi", detay={"faz": fid, "sprint": sid})
    return sid


def plan_dogrula(plan: object, org: dict | None = None) -> list[str]:
    """Geçerlilik hataları (boş liste = geçerli). Panoya dokunmaz."""
    if not isinstance(plan, dict) or not isinstance(plan.get("sprints"), list) or not plan["sprints"]:
        return ["plan boş: 'sprints' listesi yok"]
    errs = []
    if len(plan["sprints"]) > EN_FAZLA_SPRINT:
        errs.append(f"en fazla {EN_FAZLA_SPRINT} sprint")
    ids = [t.get("id") for s in plan["sprints"] for t in s.get("tasks", [])]
    if len(ids) != len(set(ids)):
        errs.append("yinelenen görev id")
    for s in plan["sprints"]:
        if not s.get("name") or not s.get("tasks"):
            errs.append(f"sprint '{s.get('id', '?')}' ad/görev eksik")
            continue
        if len(s["tasks"]) > EN_FAZLA_GOREV:
            errs.append(f"sprint '{s.get('id')}' en fazla {EN_FAZLA_GOREV} görev")
        fazlar = {t.get("phase") for t in s["tasks"]}
        if not {"develop", "test"} <= fazlar:
            errs.append(f"sprint '{s.get('id')}' en az bir develop ve bir test görevi içermeli")
        for t in s["tasks"]:
            for k in ("id", "title", "role", "phase", "outputs"):
                if not t.get(k):
                    errs.append(f"görev '{t.get('id', '?')}' alanı eksik: {k}")
            if t.get("phase") not in B.PHASE_ORDER:
                errs.append(f"görev '{t.get('id')}' geçersiz faz: {t.get('phase')}")
            if (t.get("role") or "").lower() == B.HUMAN_ROLE:
                errs.append(f"görev '{t.get('id')}' human rolü kullanamaz (onay kapısını motor ekler)")
            for dep in t.get("depends_on", []):
                if dep not in ids:
                    errs.append(f"görev '{t.get('id')}' tanımsız bağımlılık: {dep}")
    return errs


def plan_oku(faz_id: str, kok: Path = ROOT) -> tuple[dict | None, list[str]]:
    p = plan_yolu(faz_id, kok)
    if not p.is_file():
        return None, [f"plan dosyası yok: {p.relative_to(kok)}"]
    ham = p.read_text(encoding="utf-8", errors="replace").strip()
    i, j = ham.find("{"), ham.rfind("}")
    if i == -1 or j <= i:
        return None, ["geçerli JSON değil: nesne bulunamadı"]
    try:
        plan = json.loads(ham[i:j + 1])
    except json.JSONDecodeError as e:
        return None, [f"geçerli JSON değil: {e}"]
    return plan, plan_dogrula(plan)


def plan_md(faz_id: str, plan: dict) -> str:
    out = [f"# {faz_id} sprint planı (onay bekliyor)", "", f"> Üretim: {datetime.now():%Y-%m-%d %H:%M} — onaylanmadan sprintler açılmaz.", ""]
    for s in plan["sprints"]:
        out.append(f"## {s.get('id')} · {s.get('name')} ({s.get('planned_days', '?')} gün)")
        out.append(f"**Hedef:** {s.get('goal', '-')}")
        out.append("")
        for t in s["tasks"]:
            dep = f" ← {', '.join(t['depends_on'])}" if t.get("depends_on") else ""
            out.append(f"- `{t['id']}` **{t['title']}** — {t['role']} / {t['phase']}{dep}\n  {t.get('description', '')}")
        out.append("")
    return "\n".join(out)


def plani_uygula(board: dict, faz_id: str, plan: dict, org: dict | None = None, cfg: dict | None = None, kok: Path = ROOT) -> int:
    """Plan sprintlerini panoya EKLER (yeniden numaralar, bağımlılıkları eşler). Eklenen sprint sayısını döndürür."""
    if uygulandi_yolu(faz_id, kok).exists():
        return 0
    n0 = len(board.get("sprints", []))
    mevcut = {t["id"] for _, t in B.all_tasks(board)}
    eslem: dict[str, str] = {}
    yeni_sprintler = []
    for k, s in enumerate(plan["sprints"]):
        sid = f"S{n0 + k + 1}"
        while any(sid == x["id"] for x in board.get("sprints", [])) or any(sid == x["id"] for x in yeni_sprintler):
            sid += "x"
        for i, t in enumerate(s["tasks"]):
            yeni = f"{sid}-T{i + 1}"
            if yeni in mevcut:
                yeni += "p"
            eslem[t["id"]] = yeni
        yeni_sprintler.append({"id": sid, "name": s["name"], "goal": s.get("goal", ""), "planned_days": s.get("planned_days") or 3,
                               "tasks": []})
    for s, ys in zip(plan["sprints"], yeni_sprintler):
        for t in s["tasks"]:
            ys["tasks"].append({"id": eslem[t["id"]], "title": t["title"], "description": t.get("description", ""), "role": t["role"],
                                "phase": t["phase"], "outputs": list(t["outputs"]),
                                "depends_on": [eslem[d] for d in t.get("depends_on", []) if d in eslem]})
    if org is not None:
        import studio_engine as E
        for ys in yeni_sprintler:
            for t in ys["tasks"]:
                if not any(a["id"] == t["role"] for a in org["hierarchy"]):
                    E.synthesize_role(org, t["role"])
    gecici = {"sprints": yeni_sprintler}
    try:
        import uygulama_dizini as UD
        UD.uygula(gecici, cfg)
    except Exception:
        pass
    for ys in gecici["sprints"]:
        B.append_sprint(board, ys)
    uygulandi_yolu(faz_id, kok).write_text(datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
    B.audit("engine", "faz_plani_uygulandi", detay={"faz": faz_id, "sprint": len(yeni_sprintler)})
    return len(yeni_sprintler)


def kontrol(board: dict, org: dict | None = None, cfg: dict | None = None, kok: Path = ROOT) -> bool:
    """Her koşucu turunda çağrılır; panoyu değiştirdiyse True (çağıran kaydeder/yeniler)."""
    degisti = False
    # Plan görevleri çıktı yolundan tanınır (sprint/görev tablolarında faz_id saklanmaz).
    fidler = sorted({m.group(1) for _, t in B.all_tasks(board) for o in (t.get("outputs") or [])
                     if (m := re.fullmatch(re.escape(PLAN_DIZIN) + r"/(.+)\.json", o))})
    for fid in fidler:
        plan_t, onay_t = _planlama_gorevleri(board, fid)
        if plan_t is None or onay_t is None or uygulandi_yolu(fid, kok).exists():
            continue
        if plan_t["status"] == B.DONE and onay_t["status"] in (B.TODO, B.READY):
            plan, errs = plan_oku(fid, kok)
            if errs:
                plan_t["description"] = re.sub(r"\n\nGEÇERSİZ PLAN:.*$", "", plan_t["description"], flags=re.S) \
                    + "\n\nGEÇERSİZ PLAN: " + "; ".join(errs[:8]) + " — düzeltip JSON'u yeniden yaz."
                B.mark(board, plan_t["id"], B.TODO, "plan doğrulanamadı: " + errs[0][:120])
                B.refresh(board)
                degisti = True
            else:
                md = kok / PLAN_DIZIN / f"{fid}.md"
                yeni = plan_md(fid, plan)
                if not md.exists() or md.read_text(encoding="utf-8") != yeni:
                    md.write_text(yeni, encoding="utf-8")
        elif onay_t["status"] == B.DONE:
            plan, errs = plan_oku(fid, kok)
            if errs:
                continue
            if plani_uygula(board, fid, plan, org, cfg, kok):
                B.refresh(board)
                degisti = True
    return degisti


def tetikle(board: dict, org: dict, cfg: dict | None = None, zorla: str | None = None, kok: Path = ROOT) -> str | None:
    """Gerekliyse planlama sprinti ekler; eklenen sprint id'sini döndürür. zorla: faz id (panel/CLI)."""
    if zorla:
        import karar_verici_triage as KVT
        faz = next((f for f in KVT.load_fazlar().get("fazlar", []) if f["id"] == zorla), None)
        if faz is None or _planlama_gorevleri(board, zorla)[0] is not None:
            return None
        plan_yolu(zorla, kok).unlink(missing_ok=True)
        uygulandi_yolu(zorla, kok).unlink(missing_ok=True)
    else:
        faz = gerekli(board, kok)
        if faz is None:
            return None
    return planlama_sprinti_ekle(board, faz, org, cfg, kok)
