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
import socket
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT / "workspace"
# Tek doğruluk kaynağı studio.db'dir. Eski sürümlerde pano.json kullanılıyordu;
# dosya bulunursa BİR KEZ studio.db'ye aktarılıp _arsiv/ altına taşınır.
LEGACY_BOARD = WORKSPACE / "pano.json"
DB_PATH = WORKSPACE / "studio.db"
_LEGACY_DB_PATH = ROOT / "studio.db"

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
    sure_s      REAL,
    oncelik     INTEGER DEFAULT 0,
    sira        INTEGER DEFAULT 0,
    talep_id    TEXT
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

CREATE TABLE IF NOT EXISTS talepler (
    id                  TEXT PRIMARY KEY,
    tarih               TEXT,
    tur                 TEXT,
    oncelik             TEXT,
    baslik              TEXT NOT NULL,
    aciklama            TEXT,
    sayfa_url           TEXT,
    durum               TEXT,
    gorevli_rol         TEXT,
    studio_notu         TEXT,
    github_issue_number INTEGER,
    github_issue_url    TEXT,
    cozum_plani         TEXT,
    faz_id              TEXT,
    efor                TEXT,
    triage_notu         TEXT,
    gecmis              TEXT
);

CREATE TABLE IF NOT EXISTS cozum_planlari (
    talep_id    TEXT PRIMARY KEY REFERENCES talepler(id),
    icerik      TEXT,
    guncelleme  TEXT
);

CREATE TABLE IF NOT EXISTS fazlar (
    id              TEXT PRIMARY KEY,
    ad              TEXT NOT NULL,
    aciklama        TEXT,
    durum           TEXT,
    hedef_tarih     TEXT,
    kilitli         INTEGER DEFAULT 0,
    onkosul_faz     TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    zaman       TEXT,
    kaynak      TEXT,
    olay        TEXT,
    gorev_id    TEXT,
    talep_id    TEXT,
    detay       TEXT
);

CREATE TABLE IF NOT EXISTS sohbet_oturumlari (
    id              TEXT PRIMARY KEY,
    olusturma       TEXT,
    son_aktivite    TEXT,
    durum           TEXT
);

CREATE TABLE IF NOT EXISTS sohbet_mesajlari (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    oturum_id   TEXT REFERENCES sohbet_oturumlari(id),
    zaman       TEXT,
    gonderen    TEXT,
    icerik      TEXT,
    taslak      TEXT,
    talep_id    TEXT
);
"""

_SCHEMA_INITIALIZED = False


def db_conn() -> sqlite3.Connection:
    global _SCHEMA_INITIALIZED
    # Eski sürümlerde studio.db repo kökündeydi; çalışma alanı kuralı gereği
    # workspace/ altına taşınır (tek seferlik, -shm/-wal eşlikçileriyle).
    if _LEGACY_DB_PATH.exists() and not DB_PATH.exists():
        try:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            _LEGACY_DB_PATH.replace(DB_PATH)
            for ek in ("-shm", "-wal"):
                eski = _LEGACY_DB_PATH.parent / (_LEGACY_DB_PATH.name + ek)
                if eski.exists():
                    eski.replace(DB_PATH.parent / (DB_PATH.name + ek))
        except OSError:
            pass
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    if not _SCHEMA_INITIALIZED:
        try:
            conn.executescript(SCHEMA_INIT)
            _db_migrate(conn)
            conn.commit()
            _SCHEMA_INITIALIZED = True
        except Exception:
            pass
    return conn


def _db_migrate(conn: sqlite3.Connection):
    """Var olan veritabanlarına sonradan eklenen kolonları ekler."""
    cur = conn.cursor()
    try:
        cur.execute("PRAGMA table_info(pano_gorevleri)")
        mevcut = {r["name"] for r in cur.fetchall()}
        for col, tip in (("oncelik", "INTEGER NOT NULL DEFAULT 0"),
                         ("sira", "INTEGER NOT NULL DEFAULT 0"),
                         ("talep_id", "TEXT")):
            if col not in mevcut:
                cur.execute(f"ALTER TABLE pano_gorevleri ADD COLUMN {col} {tip}")
    except Exception:
        pass
    try:
        cur.execute("PRAGMA table_info(talepler)")
        mevcut = {r["name"] for r in cur.fetchall()}
        # Triage/plan alanları eskiden yalnızca JSON'da yaşardı; DB'ye taşındı.
        for col in ("cozum_plani", "faz_id", "efor", "triage_notu"):
            if col not in mevcut:
                cur.execute(f"ALTER TABLE talepler ADD COLUMN {col} TEXT")
    except Exception:
        pass


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
            cur.execute("SELECT * FROM pano_gorevleri WHERE sprint_id = ? "
                        "ORDER BY sira ASC, id ASC", (sid,))
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
                    "priority": tr["oncelik"] or 0,
                    "order": tr["sira"] or 0,
                    "talep_id": tr["talep_id"],
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
                     durum, deneme, not_, baslangic, bitis, sure_s, oncelik, sira, talep_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    t.get("priority", 0),
                    t.get("order", 0),
                    t.get("talep_id"),
                ))

        # Panodan kaldırılan sprint/görev satırlarını temizle: DB tek kaynak.
        # FK nedeniyle önce görevler (çocuk), sonra sprint'ler (ebeveyn) silinir.
        sprint_ids = [s["id"] for s in board.get("sprints", [])]
        task_ids = [t["id"] for _, t in all_tasks(board)]
        if task_ids:
            cur.execute(
                f"DELETE FROM pano_gorevleri WHERE id NOT IN ({','.join('?' * len(task_ids))})",
                task_ids)
        else:
            cur.execute("DELETE FROM pano_gorevleri")
        if sprint_ids:
            cur.execute(
                f"DELETE FROM sprintler WHERE id NOT IN ({','.join('?' * len(sprint_ids))})",
                sprint_ids)
        else:
            cur.execute("DELETE FROM sprintler")

        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------- yükle/kaydet
def _migrate_legacy_board():
    """Eski sürümden kalan workspace/pano.json varsa studio.db'ye aktarır.

    Dosya tek seferde _arsiv/ altına taşınır; pano.json artık hiçbir yerde
    okunmaz/yazılmaz — tek doğruluk kaynağı studio.db'dir.
    """
    if not LEGACY_BOARD.exists():
        return
    try:
        board = json.loads(LEGACY_BOARD.read_text(encoding="utf-8"))
        if isinstance(board, dict) and board.get("sprints"):
            db_save_board(board)
            print("  [i] Eski pano.json studio.db'ye aktarıldı.")
    except Exception as e:
        print(f"  [UYARI] pano.json içe aktarılamadı: {e}", file=sys.stderr)
    try:
        arsiv = ROOT / "_arsiv"
        arsiv.mkdir(parents=True, exist_ok=True)
        hedef = arsiv / f"pano-{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        LEGACY_BOARD.replace(hedef)
    except OSError:
        LEGACY_BOARD.unlink(missing_ok=True)


def board_exists() -> bool:
    """studio.db'de geçerli bir sprint panosu var mı?"""
    _migrate_legacy_board()
    board = db_load_board()
    return bool(board and board.get("sprints"))


def load() -> dict:
    _migrate_legacy_board()
    board = db_load_board()
    if board and board.get("sprints"):
        return board
    raise FileNotFoundError(
        "Sprint panosu bulunamadı (studio.db'de sprint kaydı yok). "
        "Önce planlayıcıyı çalıştırın: python studio_engine.py --plan"
    )


def save(board: dict):
    board["updated_at"] = datetime.now().isoformat(timespec="seconds")
    try:
        db_save_board(board)
    except Exception as e:
        print(f"  [UYARI] studio.db pano yazma hatası: {e}", file=sys.stderr)


def board_reset():
    """--sifirla: pano tablolarını ve meta kaydını tamamen temizler."""
    try:
        conn = db_conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM pano_gorevleri")
            cur.execute("DELETE FROM sprintler")
            cur.execute("DELETE FROM studio_state WHERE anahtar = 'pano_meta'")
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"  [UYARI] studio.db pano sıfırlanamadı: {e}", file=sys.stderr)


# ---------------------------------------------------------------- audit log
# Sistemin 'kim ne yaptı, ne zaman' günlüğü. Motor, kontrol ekranı, web paneli
# ve müşteri kanalları aynı tabloya yazar; paneldeki Audit sekmesi okur.
def audit(kaynak: str, olay: str, gorev_id: str = None,
          talep_id: str = None, detay=None):
    try:
        conn = db_conn()
        try:
            conn.execute(
                "INSERT INTO audit_log (zaman, kaynak, olay, gorev_id, talep_id, detay) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    datetime.now().isoformat(timespec="seconds"),
                    kaynak, olay, gorev_id, talep_id,
                    json.dumps(detay, ensure_ascii=False) if detay is not None else None,
                ))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def audit_list(limit: int = 200, kaynak: str = None, olay: str = None) -> list[dict]:
    try:
        conn = db_conn()
        try:
            sql = "SELECT * FROM audit_log"
            where, params = [], []
            if kaynak:
                where.append("kaynak = ?")
                params.append(kaynak)
            if olay:
                where.append("olay = ?")
                params.append(olay)
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(int(limit))
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception:
        return []


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
        for ti, t in enumerate(s["tasks"]):
            t.setdefault("status", TODO)
            t.setdefault("depends_on", [])
            t.setdefault("attempts", 0)
            t.setdefault("note", "")
            t.setdefault("priority", 0)
            t.setdefault("order", ti)
            t.setdefault("talep_id", None)
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
    """Yürütülecek tek bir görev döndürür (öncelik ve faz sırasına saygı duyarak)."""
    for s in sorted(board["sprints"], key=lambda x: x["order"]):
        ready = [t for t in s["tasks"] if t["status"] == READY]
        if ready:
            # Önce kullanıcı önceliği (büyük önce koşar), sonra faz ve pano sırası.
            ready.sort(key=lambda t: (-(t.get("priority") or 0),
                                      PHASE_ORDER.get(t["phase"], 9),
                                      t.get("order", 0), t["id"]))
            return s, ready[0]
        if any(t["status"] not in TERMINAL for t in s["tasks"]):
            return None, None      # bu sprint bitmeden sonrakine geçilmez
    return None, None


def find_running(board: dict):
    """Şu an RUNNING durumundaki ilk görevi (sprint, görev) döndürür."""
    for s, t in all_tasks(board):
        if t["status"] == RUNNING:
            return s, t
    return None, None


# ---------------------------------------------------------------- öncelik/sıra
# Bunlar doğrudan studio.db üzerinde çalışır; koşucu 'reload' bayrağını görünce
# panoyu yeniden yükler. Böylece koşu sırasında bellekteki pano ezilmez.
def set_priority(task_id: str, value: int) -> bool:
    """Görev önceliğini ayarlar. Büyük değer = daha önce koşar (varsayılan 0)."""
    conn = db_conn()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE pano_gorevleri SET oncelik = ? WHERE id = ?",
                    (int(value), task_id))
        ok = cur.rowcount > 0
        conn.commit()
        if ok:
            audit("kontrol", "oncelik_onerisi", gorev_id=task_id,
                  detay={"oncelik": int(value)})
        return ok
    finally:
        conn.close()


def reorder_task(task_id: str, new_pos: int) -> bool:
    """Görevi kendi sprint'i içinde <new_pos>. sıraya taşır (0 tabanlı)."""
    conn = db_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT sprint_id FROM pano_gorevleri WHERE id = ?", (task_id,))
        row = cur.fetchone()
        if not row:
            return False
        sid = row["sprint_id"]
        cur.execute("SELECT id FROM pano_gorevleri WHERE sprint_id = ? "
                    "ORDER BY sira ASC, id ASC", (sid,))
        ids = [r["id"] for r in cur.fetchall()]
        if task_id not in ids:
            return False
        ids.remove(task_id)
        pos = max(0, min(int(new_pos), len(ids)))
        ids.insert(pos, task_id)
        for i, tid in enumerate(ids):
            cur.execute("UPDATE pano_gorevleri SET sira = ? WHERE id = ?", (i, tid))
        conn.commit()
        audit("kontrol", "gorev_sirala", gorev_id=task_id,
              detay={"sprint": sid, "pozisyon": pos})
        return True
    finally:
        conn.close()


def reorder_sprint(sprint_id: str, new_pos: int) -> bool:
    """Sprint'i <new_pos>. sıraya taşır (0 tabanlı); diğerleri kayar."""
    conn = db_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM sprintler ORDER BY sira ASC, id ASC")
        ids = [r["id"] for r in cur.fetchall()]
        if sprint_id not in ids:
            return False
        ids.remove(sprint_id)
        pos = max(0, min(int(new_pos), len(ids)))
        ids.insert(pos, sprint_id)
        for i, sid in enumerate(ids):
            cur.execute("UPDATE sprintler SET sira = ? WHERE id = ?", (i, sid))
        conn.commit()
        audit("kontrol", "sprint_sirala", detay={"sprint": sprint_id, "pozisyon": pos})
        return True
    finally:
        conn.close()


def task_summary(task_id: str) -> dict | None:
    """CLI çıktıları için tek görevin özetini döndürür."""
    try:
        board = load()
    except Exception:
        return None
    s, t = find_task(board, task_id)
    if t is None:
        return None
    return {"sprint": s["id"], "id": t["id"], "title": t.get("title", ""),
            "status": t["status"], "priority": t.get("priority", 0),
            "order": t.get("order", 0)}


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
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass

    audit("engine", "gorev_durum", gorev_id=task_id,
          detay={"durum": status, "sprint": s["id"],
                 "deneme": t.get("attempts", 0), "not": (note or "")[:200]})
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


# ---------------------------------------------------------------- canlı ortam
# UAT/ziyaretçi testleri canlı sisteme ihtiyaç duyar (canli.sh):
# frontend localhost:3000 (Nuxt), backend localhost:3001 (Fastify).
LIVE_PORTS = (3000, 3001)


def live_status() -> dict:
    """Canlı ortam portlarının durumu: {3000: bool, 3001: bool}."""
    out = {}
    for port in LIVE_PORTS:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                out[port] = True
        except OSError:
            out[port] = False
    return out


def live_up() -> bool:
    return all(live_status().values())


def needs_live(task: dict) -> bool:
    """Görev canlı sistem gerektiriyor mu? (UAT ve ziyaretçi/test sürüşleri)"""
    role = (task.get("role") or "").lower()
    txt = f"{task.get('title', '')} {task.get('description', '')}".lower()
    return ("uat" in role or "uat" in txt
            or "visitor" in role or "ziyaret" in txt
            or "screen_" in role)


# ---------------------------------------------------------------- kontrol
# Çalışan bir çağrı yarıda kesilemez (para harcanmış olur), ama iki çağrı
# ARASINDA durdurulabilir. Kontrol ekranı buraya dosya bırakır, koşucu okur.
CONTROL_DIR = ROOT / "workspace" / ".control"


def _flag(name: str) -> Path:
    return CONTROL_DIR / name


def request(name: str, value: str = "1", kaynak: str = "sistem"):
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    _flag(name).write_text(value, encoding="utf-8")
    audit(kaynak, "kontrol_istek", detay={"flag": name, "deger": value})


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
        "goto": value_of("goto"),
        "force": is_set("force"),
        "reload": is_set("reload"),
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
    audit("kontrol", "kota_onay", detay={"ek_gorev": d["ek_gorev"], "ek_butce": d["ek_butce"]})
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


# ---------------------------------------------------------------------------
# Framework güncelleme bildirimi
# ---------------------------------------------------------------------------
# Bir proje (elektriklioto-gemini vb.) digital-software-studio'yu kullanırken
# framework'te yeni sürüm çıkıp çıkmadığını buradan öğrenir. Sonuç
# workspace/.studio_update_check.json'a TTL'li yazılır — ctl/web/motor aynı
# önbelleği paylaşır, her render'da ağa çıkılmaz.

UPDATE_CHECK_FILE = WORKSPACE / ".studio_update_check.json"
UPDATE_CHECK_TTL = int(os.getenv("STUDIO_UPDATE_TTL", "3600"))  # saniye
DS_VERSION_NAME = "studio.version"
LOCAL_VERSION_NAME = ".studio-version"
DS_GITHUB_RAW = os.getenv(
    "STUDIO_DS_RAW",
    "https://raw.githubusercontent.com/cihan53/digital-software-studio/main")


def _ver_tuple(v) -> tuple:
    try:
        return tuple(int(x) for x in str(v or "").split("."))
    except ValueError:
        return (0,)


def _studio_version_jsonu_bul() -> tuple[dict | None, str]:
    """DS'nin studio.version'ını bul: önce yerel dizin, yoksa GitHub raw."""
    adaylar = []
    env = os.getenv("STUDIO_REPO")
    if env:
        adaylar.append(Path(env))
    adaylar.append(ROOT.parent / "digital-software-studio")
    for p in adaylar:
        vf = p / DS_VERSION_NAME
        if vf.is_file():
            try:
                return json.loads(vf.read_text(encoding="utf-8")), "yerel"
            except Exception:
                continue
    try:
        import urllib.request
        with urllib.request.urlopen(
                f"{DS_GITHUB_RAW}/{DS_VERSION_NAME}", timeout=3) as r:
            return json.loads(r.read().decode("utf-8")), "github"
    except Exception:
        return None, ""


def _framework_update_hesapla() -> dict | None:
    # Bu dizin framework'ün kendisiyse (studio.version var, .studio-version yok)
    # bildirim anlamsız — karşılaştırma yapma.
    if (ROOT / DS_VERSION_NAME).exists() and not (ROOT / LOCAL_VERSION_NAME).exists():
        return None
    local_ver = "0.0.0"
    lv = ROOT / LOCAL_VERSION_NAME
    if lv.exists():
        try:
            local_ver = json.loads(lv.read_text(encoding="utf-8")).get("version") or "0.0.0"
        except Exception:
            pass
    ds, kaynak = _studio_version_jsonu_bul()
    if not ds:
        return None
    remote_ver = ds.get("version", "0.0.0")
    yeni = _ver_tuple(remote_ver) > _ver_tuple(local_ver)
    degisenler = []
    if yeni:
        for e in ds.get("changelog", []):
            if _ver_tuple(e.get("version")) > _ver_tuple(local_ver):
                degisenler.extend(e.get("changes", []))
    return {"local": local_ver, "remote": remote_ver,
            "update": yeni, "released": ds.get("released"),
            "changes": degisenler, "kaynak": kaynak}


def framework_update_info(ttl: int = UPDATE_CHECK_TTL) -> dict | None:
    """DS framework'te yeni sürüm varsa bildirim bilgisi döndürür.

    {'local','remote','update','released','changes','kaynak'} veya None
    (framework'ün kendisi / DS'ye ulaşılamadı). Sonuç dosya önbelleğinde
    `ttl` saniye tutulur; ağ erişimi yoksa sessizce None döner.
    """
    try:
        c = json.loads(UPDATE_CHECK_FILE.read_text(encoding="utf-8"))
        if time.time() - c.get("checked_at", 0) < ttl:
            return c.get("info")
    except Exception:
        pass
    try:
        info = _framework_update_hesapla()
    except Exception:
        info = None
    try:
        UPDATE_CHECK_FILE.parent.mkdir(parents=True, exist_ok=True)
        UPDATE_CHECK_FILE.write_text(
            json.dumps({"checked_at": time.time(), "info": info},
                       ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return info
