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
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT / "workspace"
BOARD_FILE = WORKSPACE / "pano.json"
DB_PATH = ROOT / "studio.db"

TODO, READY, RUNNING, BLOCKED, DONE, FAILED, SKIPPED = (
    "TODO", "READY", "RUNNING", "BLOCKED", "DONE", "FAILED", "SKIPPED"
)
TERMINAL = {DONE, SKIPPED}
PHASE_ORDER = {"develop": 0, "test": 1, "deploy": 2}


# ---------------------------------------------------------------- veritabanı
SCHEMA_INIT = """
CREATE TABLE IF NOT EXISTS sprintler (
    id                  TEXT PRIMARY KEY,
    ad                  TEXT,
    hedef               TEXT,
    planlanan_gun       INTEGER,
    sira                INTEGER,
    durum               TEXT,
    planlanan_baslangic TEXT,
    planlanan_bitis     TEXT,
    gercek_baslangic    TEXT,
    gercek_bitis        TEXT
);

CREATE TABLE IF NOT EXISTS pano_gorevleri (
    id          TEXT PRIMARY KEY,
    sprint_id   TEXT REFERENCES sprintler(id),
    baslik      TEXT,
    aciklama    TEXT,
    rol         TEXT,
    phase       TEXT,
    ciktilar    TEXT,
    bagimlilik  TEXT,
    durum       TEXT,
    deneme      INTEGER,
    not_        TEXT,
    baslangic   TEXT,
    bitis       TEXT,
    sure_s      REAL
);

CREATE TABLE IF NOT EXISTS studio_state (
    anahtar     TEXT PRIMARY KEY,
    deger       TEXT
);

CREATE TABLE IF NOT EXISTS gunluk_kota (
    tarih       TEXT PRIMARY KEY,
    gorev       INTEGER DEFAULT 0,
    maliyet     REAL DEFAULT 0.0,
    ek_gorev    INTEGER DEFAULT 0,
    ek_butce    REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS maliyet_kayitlari (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tarih       TEXT,
    rol         TEXT,
    backend     TEXT,
    model       TEXT,
    cost_usd    REAL,
    detay       TEXT
);
"""

_SCHEMA_INITIALIZED = False


def db_conn() -> sqlite3.Connection:
    global _SCHEMA_INITIALIZED
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    if not _SCHEMA_INITIALIZED:
        try:
            conn.executescript(SCHEMA_INIT)
            conn.commit()
            _SCHEMA_INITIALIZED = True
        except Exception:
            pass
    return conn


def db_load_board() -> dict | None:
    if not DB_PATH.exists():
        return None
    try:
        conn = db_conn()
    except Exception:
        return None

    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM sprintler ORDER BY sira ASC")
        sprint_rows = cur.fetchall()
        if not sprint_rows:
            return None

        # Meta oku
        baseline_end = None
        created_at = None
        updated_at = None
        try:
            cur.execute("SELECT deger FROM studio_state WHERE anahtar = 'pano_meta'")
            row = cur.fetchone()
            if row and row["deger"]:
                meta = json.loads(row["deger"])
                baseline_end = meta.get("baseline_end")
                created_at = meta.get("created_at")
                updated_at = meta.get("updated_at")
        except Exception:
            pass

        sprints = []
        for sr in sprint_rows:
            sid = sr["id"]
            cur.execute("SELECT * FROM pano_gorevleri WHERE sprint_id = ? ORDER BY id ASC", (sid,))
            task_rows = cur.fetchall()
            tasks = []
            for tr in task_rows:
                outputs = []
                if tr["ciktilar"]:
                    try:
                        outputs = json.loads(tr["ciktilar"])
                    except Exception:
                        outputs = [tr["ciktilar"]]
                depends_on = []
                if tr["bagimlilik"]:
                    try:
                        depends_on = json.loads(tr["bagimlilik"])
                    except Exception:
                        depends_on = []

                tasks.append({
                    "id": tr["id"],
                    "title": tr["baslik"] or "",
                    "description": tr["aciklama"] or "",
                    "role": tr["rol"] or "",
                    "phase": tr["phase"] or "develop",
                    "outputs": outputs,
                    "depends_on": depends_on,
                    "status": tr["durum"] or TODO,
                    "attempts": tr["deneme"] or 0,
                    "note": tr["not_"] or "",
                    "started_at": tr["baslangic"],
                    "finished_at": tr["bitis"],
                    "duration_s": tr["sure_s"],
                })

            sprints.append({
                "id": sr["id"],
                "name": sr["ad"] or "",
                "goal": sr["hedef"] or "",
                "planned_days": sr["planlanan_gun"] or 1,
                "order": sr["sira"] if sr["sira"] is not None else len(sprints),
                "status": sr["durum"] or TODO,
                "planned_start": sr["planlanan_baslangic"],
                "planned_end": sr["planlanan_bitis"],
                "actual_start": sr["gercek_baslangic"],
                "actual_end": sr["gercek_bitis"],
                "tasks": tasks
            })

        board = {"sprints": sprints}
        if baseline_end:
            board["baseline_end"] = baseline_end
        if created_at:
            board["created_at"] = created_at
        if updated_at:
            board["updated_at"] = updated_at
        return board
    except Exception:
        return None
    finally:
        conn.close()


def db_save_board(board: dict):
    if not DB_PATH.exists():
        return
    conn = db_conn()
    try:
        cur = conn.cursor()
        meta = {
            "baseline_end": board.get("baseline_end"),
            "created_at": board.get("created_at"),
            "updated_at": board.get("updated_at"),
        }
        cur.execute(
            "INSERT OR REPLACE INTO studio_state (anahtar, deger) VALUES (?, ?)",
            ("pano_meta", json.dumps(meta, ensure_ascii=False))
        )

        for s in board.get("sprints", []):
            sid = s["id"]
            cur.execute("""
                INSERT OR REPLACE INTO sprintler
                (id, ad, hedef, planlanan_gun, sira, durum,
                 planlanan_baslangic, planlanan_bitis, gercek_baslangic, gercek_bitis)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sid,
                s.get("name") or "",
                s.get("goal") or "",
                s.get("planned_days") or 1,
                s.get("order", 0),
                s.get("status") or TODO,
                s.get("planned_start"),
                s.get("planned_end"),
                s.get("actual_start"),
                s.get("actual_end"),
            ))

            for t in s.get("tasks", []):
                tid = t["id"]
                ciktilar = json.dumps(t.get("outputs", []), ensure_ascii=False)
                bagimlilik = json.dumps(t.get("depends_on", []), ensure_ascii=False)
                cur.execute("""
                    INSERT OR REPLACE INTO pano_gorevleri
                    (id, sprint_id, baslik, aciklama, rol, phase, ciktilar, bagimlilik,
                     durum, deneme, not_, baslangic, bitis, sure_s)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    tid,
                    sid,
                    t.get("title") or "",
                    t.get("description") or "",
                    t.get("role") or "",
                    t.get("phase") or "develop",
                    ciktilar,
                    bagimlilik,
                    t.get("status") or TODO,
                    t.get("attempts", 0),
                    t.get("note", ""),
                    t.get("started_at"),
                    t.get("finished_at"),
                    t.get("duration_s"),
                ))

        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------- yükle/kaydet
def load(path: Path = BOARD_FILE) -> dict:
    # 1. Önce studio.db'den yüklemeyi dene
    db_board = db_load_board()
    if db_board and db_board.get("sprints"):
        # Eğer aktif bir koşucu yoksa, olası yetim (RUNNING) görevleri akıllıca kurtar
        if not is_runner_active():
            if recover_orphans(db_board):
                refresh(db_board)
                db_save_board(db_board)
        return db_board

    # 2. DB boşsa JSON dosyasından dene
    if path.exists():
        board = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(board, dict) and "sprints" in board:
            try:
                db_save_board(board)
            except Exception:
                pass
            return board

    raise FileNotFoundError(
        f"Sprint panosu bulunamadı (ne studio.db'de ne de {path.name}'de var). "
        f"Önce planlayıcıyı çalıştırın: python studio_engine.py --plan"
    )


def save(board: dict, path: Path = BOARD_FILE):
    board["updated_at"] = datetime.now().isoformat(timespec="seconds")
    # 1. studio.db'ye yaz (Primary source of truth)
    try:
        db_save_board(board)
    except Exception as e:
        print(f"  [UYARI] studio.db pano yazma hatası: {e}", file=sys.stderr)

    # 2. Geriye dönük uyumluluk için JSON'a da yaz (Dual-write)
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


def task_outputs_exist(task: dict) -> bool:
    """Görevin tanımlı tüm çıktılarının diskte oluşturulup oluşturulmadığını doğrular."""
    outputs = task.get("outputs", [])
    if not outputs or not isinstance(outputs, list):
        return False
    for out in outputs:
        p = ROOT / out if not Path(out).is_absolute() else Path(out)
        if not p.exists():
            return False
        if p.is_file() and p.stat().st_size == 0:
            return False
        if p.is_dir() and not any(p.iterdir()):
            return False
    return True


def recover_orphans(board: dict) -> bool:
    """Kapanmış veya çökmüş koşulardan arta kalan RUNNING durumundaki görevleri akıllıca kurtarır."""
    if is_runner_active():
        return False
    changed = False
    for s in board.get("sprints", []):
        for t in s.get("tasks", []):
            if t.get("status") == RUNNING:
                if task_outputs_exist(t):
                    t["status"] = DONE
                    t["note"] = (t.get("note") or "") + " [çıktılar mevcut, otomatik tamamlandı]"
                    if not t.get("finished_at"):
                        t["finished_at"] = time.time()
                else:
                    t["status"] = READY
                    t["note"] = (t.get("note") or "") + " [süreç kapandı, hazır duruma alındı]"
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
            # Dışarıda çalışan aktif bir koşucu yoksa RUNNING kalmış yetim görevleri akıllıca kurtar
            if t["status"] == RUNNING and not active:
                if task_outputs_exist(t):
                    t["status"] = DONE
                    t["note"] = (t.get("note") or "") + " [çıktılar doğrulandı]"
                    if not t.get("finished_at"):
                        t["finished_at"] = time.time()
                else:
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

    # studio.db'ye anında yansıt
    try:
        conn = db_conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                UPDATE pano_gorevleri
                SET durum = ?, not_ = ?, deneme = ?, baslangic = ?, bitis = ?, sure_s = ?
                WHERE id = ?
            """, (
                t["status"],
                t.get("note", ""),
                t.get("attempts", 0),
                t.get("started_at"),
                t.get("finished_at"),
                t.get("duration_s"),
                task_id,
            ))
            if s.get("actual_start"):
                cur.execute(
                    "UPDATE sprintler SET gercek_baslangic = ? WHERE id = ?",
                    (s["actual_start"], s["id"])
                )

            # Sprint durumunu da hesapla ve studio.db'ye anında yansıt
            s_tasks = s.get("tasks", [])
            s_statuses = {item["status"] for item in s_tasks}
            if s_statuses and s_statuses <= TERMINAL:
                s["status"] = DONE
                if not s.get("actual_end"):
                    s["actual_end"] = datetime.now().isoformat(timespec="seconds")
                cur.execute(
                    "UPDATE sprintler SET durum = ?, gercek_bitis = ? WHERE id = ?",
                    (DONE, s["actual_end"], s["id"])
                )
            elif RUNNING in s_statuses:
                s["status"] = RUNNING
                cur.execute("UPDATE sprintler SET durum = ? WHERE id = ?", (RUNNING, s["id"]))

            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass

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
    # 1. Önce studio.db'den oku
    try:
        conn = db_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM gunluk_kota WHERE tarih = ?", (_bugun(),))
            row = cur.fetchone()
            if row:
                d["gorev"] = row["gorev"] or 0
                d["maliyet"] = row["maliyet"] or 0.0
                d["ek_gorev"] = row["ek_gorev"] or 0
                d["ek_butce"] = row["ek_butce"] or 0.0
                return d
        finally:
            conn.close()
    except Exception:
        pass

    # 2. JSON fallback
    if LEDGER.exists():
        try:
            saved = json.loads(LEDGER.read_text(encoding="utf-8"))
            if saved.get("tarih") == _bugun():      # yeni gün = sıfırdan başla
                d.update(saved)
                # DB'ye de yaz
                ledger_write(d)
        except (json.JSONDecodeError, OSError):
            pass
    return d


def ledger_write(d: dict):
    d["tarih"] = _bugun()
    # 1. studio.db'ye yaz
    try:
        conn = db_conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO gunluk_kota (tarih, gorev, maliyet, ek_gorev, ek_butce)
                VALUES (?, ?, ?, ?, ?)
            """, (
                d["tarih"],
                d.get("gorev", 0),
                d.get("maliyet", 0.0),
                d.get("ek_gorev", 0),
                d.get("ek_butce", 0.0),
            ))
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"  [UYARI] studio.db kota yazma hatası: {e}", file=sys.stderr)

    # 2. JSON'a yaz (Dual-write)
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
