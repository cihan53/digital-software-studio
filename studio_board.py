#!/usr/bin/env python3
"""
Sprint panosu ve durum makinesi.

Tasarım kararı: sprint'ler ZAMANLA değil BAĞIMLILIKLA ilerler.
Takvim yalnızca tahmindir; bir sprint beklenenden uzun sürerse sonraki sprint
başlamaz, onun yerine sonraki tüm sprint'lerin planlanan tarihleri kayar.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT / "workspace"
BOARD_FILE = WORKSPACE / "pano.json"

TODO, READY, RUNNING, BLOCKED, DONE, FAILED, SKIPPED = (
    "TODO", "READY", "RUNNING", "BLOCKED", "DONE", "FAILED", "SKIPPED"
)
TERMINAL = {DONE, SKIPPED}
PHASE_ORDER = {"develop": 0, "test": 1, "deploy": 2}


# ---------------------------------------------------------------- yükle/kaydet
def load(path: Path = BOARD_FILE) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"{path.name} yok. Önce planlayıcıyı çalıştırın: "
            f"python studio_engine.py --plan"
        )
    board = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(board, dict) or "sprints" not in board:
        raise ValueError(
            f"{path.name} beklenen şemada değil (üst düzeyde 'sprints' yok). "
            f"Yeniden planlayın: python studio_engine.py --replan"
        )
    return board


def save(board: dict, path: Path = BOARD_FILE):
    board["updated_at"] = datetime.now().isoformat(timespec="seconds")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(board, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)          # atomik: yarım yazılmış pano kalmasın


def all_tasks(board: dict):
    for s in board["sprints"]:
        for t in s["tasks"]:
            yield s, t


def find_task(board: dict, task_id: str):
    for s, t in all_tasks(board):
        if t["id"] == task_id:
            return s, t
    return None, None


# ---------------------------------------------------------------- doğrulama
def validate(board: dict) -> list[str]:
    """Planlayıcı çıktısını kabul etmeden önceki tutarlılık kontrolü."""
    errs = []
    if not board.get("sprints"):
        errs.append("pano boş: hiç sprint yok")
        return errs

    ids = [t["id"] for _, t in all_tasks(board)]
    if len(ids) != len(set(ids)):
        dupes = {i for i in ids if ids.count(i) > 1}
        errs.append(f"yinelenen görev id: {sorted(dupes)}")

    known = set(ids)
    for s in board["sprints"]:
        for key in ("id", "name", "tasks"):
            if key not in s:
                errs.append(f"sprint '{s.get('id', '?')}' alanı eksik: {key}")
        for t in s.get("tasks", []):
            for key in ("id", "title", "role", "phase", "outputs"):
                if key not in t:
                    errs.append(f"görev '{t.get('id', '?')}' alanı eksik: {key}")
            if t.get("phase") not in PHASE_ORDER:
                errs.append(f"görev '{t.get('id')}' geçersiz faz: {t.get('phase')}")
            for d in t.get("depends_on", []):
                if d not in known:
                    errs.append(f"görev '{t['id']}' tanımsız bağımlılığa işaret ediyor: {d}")
            if not t.get("outputs"):
                errs.append(f"görev '{t.get('id')}' hiç çıktı üretmiyor")
    return errs


def normalize(board: dict) -> dict:
    """Eksik çalışma-zamanı alanlarını tamamlar (planlayıcı bunları yazmaz)."""
    board.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
    for i, s in enumerate(board["sprints"]):
        s.setdefault("order", i)
        s.setdefault("status", TODO)
        s.setdefault("actual_start", None)
        s.setdefault("actual_end", None)
        s.setdefault("planned_days", max(1, len(s["tasks"]) // 2 or 1))
        for t in s["tasks"]:
            t.setdefault("status", TODO)
            t.setdefault("depends_on", [])
            t.setdefault("attempts", 0)
            t.setdefault("note", "")
    return board


def append_sprint(board: dict, new_sprint: dict) -> dict:
    """Mevcut panoyu bozmadan sonuna yeni bir sprint fazı ekler ve takvimi günceller."""
    existing_sprint_ids = {s["id"] for s in board.get("sprints", [])}
    sid = new_sprint.get("id")
    if not sid or sid in existing_sprint_ids:
        sid = f"S{len(board.get('sprints', [])) + 1}"
        new_sprint["id"] = sid

    new_sprint["order"] = len(board.get("sprints", []))
    new_sprint.setdefault("status", TODO)
    new_sprint.setdefault("actual_start", None)
    new_sprint.setdefault("actual_end", None)
    new_sprint.setdefault("planned_days", max(1, len(new_sprint.get("tasks", [])) // 2 or 1))

    existing_task_ids = {t["id"] for _, t in all_tasks(board)}
    for idx, t in enumerate(new_sprint.get("tasks", [])):
        if not t.get("id") or t["id"] in existing_task_ids:
            t["id"] = f"{sid}-T{idx + 1}"
        t.setdefault("status", TODO)
        t.setdefault("depends_on", [])
        t.setdefault("attempts", 0)
        t.setdefault("note", "")
        existing_task_ids.add(t["id"])

    board.setdefault("sprints", []).append(new_sprint)
    normalize(board)
    refresh(board)
    schedule(board)
    if board["sprints"]:
        board["baseline_end"] = board["sprints"][-1].get("planned_end")
    return board


# ---------------------------------------------------------------- takvim
def schedule(board: dict, start: date | None = None) -> dict:
    """Planlanan tarihleri yeniden hesaplar.

    Bitmiş sprint'ler GERÇEK bitiş tarihlerini korur; bitmemişler onların
    ardından sıralanır. Bir sprint geciktiyse sonrakiler kendiliğinden kayar —
    'takvimler kaymalı' kuralı buradan gelir.
    """
    cursor = start or date.today()
    for s in sorted(board["sprints"], key=lambda x: x["order"]):
        if s["status"] == DONE and s.get("actual_end"):
            cursor = max(cursor, date.fromisoformat(s["actual_end"][:10]) + timedelta(days=1))
            # actual_start anahtarı None değeriyle var olabilir; .get varsayılanı kurtarmaz.
            s["planned_start"] = (s.get("actual_start") or s["actual_end"])[:10]
            s["planned_end"] = s["actual_end"][:10]
            continue
        s["planned_start"] = cursor.isoformat()
        cursor = cursor + timedelta(days=max(1, int(s["planned_days"])) - 1)
        s["planned_end"] = cursor.isoformat()
        cursor += timedelta(days=1)
    return board


def slip_days(board: dict) -> int:
    """Gerçekleşen ile ilk plan arasındaki toplam kayma (gün)."""
    base = board.get("baseline_end")
    if not base:
        return 0
    last = max((s.get("planned_end") or "" for s in board["sprints"]), default="")
    if not last:
        return 0
    return (date.fromisoformat(last) - date.fromisoformat(base)).days


def is_runner_active() -> bool:
    """Başka bir sürecin aktif olarak koşup koşmadığını kontrol eder."""
    lock_file = WORKSPACE / ".lock"
    if not lock_file.exists():
        return False
    try:
        pid = int(lock_file.read_text(encoding="utf-8").strip())
        if pid == os.getpid():
            return False
        os.kill(pid, 0)
        return True
    except (ValueError, OSError):
        return False


def recover_orphans(board: dict) -> bool:
    """Kapanmış veya çökmüş koşulardan arta kalan RUNNING durumundaki görevleri kurtarır."""
    if is_runner_active():
        return False
    changed = False
    for s in board.get("sprints", []):
        for t in s.get("tasks", []):
            if t.get("status") == RUNNING:
                t["status"] = READY
                t["note"] = (t.get("note") or "") + " [yetim durumdan kurtarıldı]"
                changed = True
    if changed:
        refresh(board)
        save(board)
    return changed


# ---------------------------------------------------------------- durum makinesi
def refresh(board: dict) -> dict:
    """Bağımlılıklara göre TODO -> READY / BLOCKED geçişlerini uygular.

    Sprint'ler kesin sıralıdır: bir sprint'in görevleri, önceki sprint'in
    TAMAMI bitmeden READY olamaz.
    """
    done_ids = {t["id"] for _, t in all_tasks(board) if t["status"] in TERMINAL}
    failed_ids = {t["id"] for _, t in all_tasks(board) if t["status"] == FAILED}

    active = is_runner_active()
    prev_closed = True
    for s in sorted(board["sprints"], key=lambda x: x["order"]):
        statuses = {t["status"] for t in s["tasks"]}

        for t in s["tasks"]:
            # Dışarıda çalışan aktif bir koşucu yoksa RUNNING kalmış yetim görevleri READY durumuna çek
            if t["status"] == RUNNING and not active:
                t["status"] = READY

            if t["status"] in (DONE, SKIPPED, RUNNING, FAILED):
                continue
            deps = set(t.get("depends_on", []))
            if deps & failed_ids:
                t["status"] = BLOCKED
                t["note"] = "bağımlı olduğu görev başarısız"
            elif not prev_closed:
                t["status"] = TODO          # önceki sprint bitmedi: sıra gelmedi
            elif deps <= done_ids:
                t["status"] = READY
            else:
                t["status"] = TODO

        statuses = {t["status"] for t in s["tasks"]}
        if statuses <= TERMINAL:
            if s["status"] != DONE:
                s["status"] = DONE
                s["actual_end"] = s.get("actual_end") or datetime.now().isoformat(timespec="seconds")
        elif RUNNING in statuses:
            s["status"] = RUNNING
        elif FAILED in statuses or BLOCKED in statuses:
            s["status"] = BLOCKED
        elif READY in statuses:
            s["status"] = READY
        else:
            s["status"] = TODO

        # Sonraki sprint ancak bu sprint tamamen kapandıysa açılır.
        prev_closed = prev_closed and (statuses <= TERMINAL)

    return board


def next_ready(board: dict):
    """Yürütülecek tek bir görev döndürür (faz sırasına saygı duyarak)."""
    for s in sorted(board["sprints"], key=lambda x: x["order"]):
        ready = [t for t in s["tasks"] if t["status"] == READY]
        if ready:
            ready.sort(key=lambda t: (PHASE_ORDER.get(t["phase"], 9), t["id"]))
            return s, ready[0]
        if any(t["status"] not in TERMINAL for t in s["tasks"]):
            return None, None      # bu sprint bitmeden sonrakine geçilmez
    return None, None


def mark(board: dict, task_id: str, status: str, note: str = ""):
    s, t = find_task(board, task_id)
    if t is None:
        raise KeyError(task_id)
    t["status"] = status
    if note:
        t["note"] = note
    if status == RUNNING:
        t["attempts"] = t.get("attempts", 0) + 1
        t["started_at"] = time.time()
        if not s.get("actual_start"):
            s["actual_start"] = datetime.now().isoformat(timespec="seconds")
    elif status in (DONE, FAILED, SKIPPED):
        t["finished_at"] = time.time()
        if t.get("started_at"):
            t["duration_s"] = round(t["finished_at"] - t["started_at"], 1)
    return t


def progress(board: dict) -> dict:
    tasks = [t for _, t in all_tasks(board)]
    return {
        "total": len(tasks),
        "done": sum(1 for t in tasks if t["status"] == DONE),
        "failed": sum(1 for t in tasks if t["status"] == FAILED),
        "blocked": sum(1 for t in tasks if t["status"] == BLOCKED),
        "running": sum(1 for t in tasks if t["status"] == RUNNING),
        "sprints_done": sum(1 for s in board["sprints"] if s["status"] == DONE),
        "sprints_total": len(board["sprints"]),
    }


# ---------------------------------------------------------------- kontrol
# Çalışan bir çağrı yarıda kesilemez (para harcanmış olur), ama iki çağrı
# ARASINDA durdurulabilir. Kontrol ekranı buraya dosya bırakır, koşucu okur.
CONTROL_DIR = ROOT / "workspace" / ".control"


def _flag(name: str) -> Path:
    return CONTROL_DIR / name


def request(name: str, value: str = "1"):
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    _flag(name).write_text(value, encoding="utf-8")


def clear(name: str):
    _flag(name).unlink(missing_ok=True)


def is_set(name: str) -> bool:
    return _flag(name).exists()


def value_of(name: str) -> str:
    f = _flag(name)
    return f.read_text(encoding="utf-8").strip() if f.exists() else ""


def control_state() -> dict:
    return {
        "paused": is_set("pause"),
        "stopping": is_set("stop"),
        "skip": value_of("skip"),
    }


# ---------------------------------------------------------------- günlük kota
# Amaç: boru hattı bir günde kontrolsüz harcama yapmasın. Sınıra ulaşınca
# DURUR ve kullanıcının açık onayını bekler; kendiliğinden devam etmez.
LEDGER = ROOT / "workspace" / ".gunluk.json"
GUNLUK_GOREV = int(__import__("os").getenv("STUDIO_GUNLUK_GOREV", "3"))
GUNLUK_BUTCE = float(__import__("os").getenv("STUDIO_GUNLUK_BUTCE", "2.0"))


def _bugun() -> str:
    return date.today().isoformat()


def ledger_read() -> dict:
    d = {"tarih": _bugun(), "gorev": 0, "maliyet": 0.0, "ek_gorev": 0, "ek_butce": 0.0}
    if LEDGER.exists():
        try:
            saved = json.loads(LEDGER.read_text(encoding="utf-8"))
            if saved.get("tarih") == _bugun():      # yeni gün = sıfırdan başla
                d.update(saved)
        except (json.JSONDecodeError, OSError):
            pass
    return d


def ledger_write(d: dict):
    d["tarih"] = _bugun()
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    LEDGER.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")


def ledger_add(cost: float):
    d = ledger_read()
    d["gorev"] += 1
    d["maliyet"] = round(d["maliyet"] + (cost or 0.0), 4)
    ledger_write(d)
    return d


def ledger_limits() -> tuple[int, float]:
    d = ledger_read()
    return GUNLUK_GOREV + d.get("ek_gorev", 0), GUNLUK_BUTCE + d.get("ek_butce", 0.0)


def ledger_approve(gorev: int = None, butce: float = None):
    """Kullanıcı onayı: bugün için ek kota tanır."""
    d = ledger_read()
    d["ek_gorev"] = d.get("ek_gorev", 0) + (GUNLUK_GOREV if gorev is None else gorev)
    d["ek_butce"] = round(d.get("ek_butce", 0.0) + (GUNLUK_BUTCE if butce is None else butce), 4)
    ledger_write(d)
    return d


def ledger_check(tahmini_maliyet: float) -> tuple[bool, str]:
    """Yeni görev alınabilir mi? (izin, sebep)

    Bütçede AŞMADAN ÖNCE durur: sıradaki görevin tahmini maliyeti eklendiğinde
    sınır aşılacaksa görev hiç başlatılmaz.
    """
    d = ledger_read()
    max_gorev, max_butce = ledger_limits()

    if d["gorev"] >= max_gorev:
        return False, (f"Günlük görev kotası doldu: {d['gorev']}/{max_gorev} "
                       f"(bugün ${d['maliyet']:.2f} harcandı)")
    if d["maliyet"] + tahmini_maliyet > max_butce:
        return False, (f"Günlük bütçeye yaklaşıldı: bugün ${d['maliyet']:.2f} harcandı, "
                       f"sıradaki görev ~${tahmini_maliyet:.2f} tutacak, sınır ${max_butce:.2f}")
    return True, ""
