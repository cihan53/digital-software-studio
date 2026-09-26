#!/usr/bin/env python3
"""
elektriklioto.com — JSON → SQLite Migration Scripti
=====================================================
Mevcut JSON ve MD dosyalarındaki tüm studio verisini studio.db'ye aktarır.

Tablolar:
  - talepler       : musteri_talepleri.json
  - cozum_planlari : cozum_planlari/TALEP-XXX.md (TEXT olarak)
  - sprintler      : pano.json → sprints
  - pano_gorevleri : pano.json → sprints[].tasks
  - ekip_rolleri   : org_chart.json → hierarchy

Kullanım:
  python3 scripts/migrate_to_sqlite.py
  python3 scripts/migrate_to_sqlite.py --kontrol   (sadece rapor, yazmaz)
"""

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "studio.db"
TALEP_JSON = ROOT / "workspace/docs/musteri_talepleri.json"
PANO_JSON = ROOT / "workspace/pano.json"
ORG_CHART = ROOT / "org_chart.json"
COZUM_DIR = ROOT / "workspace/docs/cozum_planlari"
STATE_JSON = ROOT / "workspace/.state.json"
KOTA_JSON = ROOT / "workspace/.gunluk.json"
FAZLAR_JSON = ROOT / "workspace/docs/fazlar.json"
COSTS_JSONL = ROOT / "workspace/metrics/costs.jsonl"

KONTROL_MODU = "--kontrol" in sys.argv

GREEN = "\033[32m"; YELLOW = "\033[33m"; CYAN = "\033[36m"
RED = "\033[31m"; BOLD = "\033[1m"; NC = "\033[0m"

def log(emoji, mesaj, renk=NC):
    print(f"  {emoji}  {renk}{mesaj}{NC}")


# ==============================================================================
# SCHEMA
# ==============================================================================

SCHEMA = """
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
    gecmis              TEXT    -- JSON string olarak saklanır
);

CREATE TABLE IF NOT EXISTS cozum_planlari (
    talep_id    TEXT PRIMARY KEY REFERENCES talepler(id),
    icerik      TEXT,           -- MD dosyası içeriği
    guncelleme  TEXT            -- dosya mtime
);

CREATE TABLE IF NOT EXISTS sprintler (
    id              TEXT PRIMARY KEY,
    ad              TEXT,
    hedef           TEXT,
    planlanan_gun   INTEGER,
    sira            INTEGER,
    durum           TEXT,
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
    ciktilar    TEXT,   -- JSON string
    bagimlilik  TEXT,   -- JSON string
    durum       TEXT,
    deneme      INTEGER,
    not_        TEXT,
    baslangic   TEXT,
    bitis       TEXT,
    sure_s      REAL
);

CREATE TABLE IF NOT EXISTS ekip_rolleri (
    id              TEXT PRIMARY KEY,
    unvan           TEXT,
    sistem_promptu  TEXT,
    girdiler        TEXT,   -- JSON string
    ciktilar        TEXT,   -- JSON string
    sahne           TEXT,
    backend         TEXT,
    model           TEXT,
    max_kelime      INTEGER
);

CREATE TABLE IF NOT EXISTS studio_state (
    anahtar         TEXT PRIMARY KEY,
    deger           TEXT    -- JSON string veya text
);

CREATE TABLE IF NOT EXISTS gunluk_kota (
    tarih           TEXT PRIMARY KEY,
    gorev           INTEGER DEFAULT 0,
    maliyet         REAL DEFAULT 0.0,
    ek_gorev        INTEGER DEFAULT 0,
    ek_butce        REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS maliyet_kayitlari (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tarih           TEXT,
    rol             TEXT,
    backend         TEXT,
    model           TEXT,
    cost_usd        REAL,
    detay           TEXT
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
"""


def veritabani_olustur(conn):
    conn.executescript(SCHEMA)
    conn.commit()
    log("🗄️", "Tablolar oluşturuldu / doğrulandı.", GREEN)


# ==============================================================================
# TALEPLER
# ==============================================================================

def talepler_aktar(conn):
    if not TALEP_JSON.exists():
        log("⚠️", f"Bulunamadı: {TALEP_JSON}", YELLOW)
        return 0

    with open(TALEP_JSON, encoding="utf-8") as f:
        veri = json.load(f)

    talepler = veri.get("talepler", [])
    n = 0
    for t in talepler:
        gecmis = json.dumps(t.get("gecmis", []), ensure_ascii=False)
        conn.execute("""
            INSERT OR REPLACE INTO talepler
            (id, tarih, tur, oncelik, baslik, aciklama, sayfa_url, durum,
             gorevli_rol, studio_notu, github_issue_number, github_issue_url,
             cozum_plani, faz_id, efor, triage_notu, gecmis)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            t.get("id"),
            t.get("tarih"),
            t.get("tur"),
            t.get("oncelik"),
            t.get("baslik"),
            t.get("aciklama"),
            t.get("sayfa_url"),
            t.get("durum"),
            t.get("gorevli_rol"),
            t.get("studio_notu"),
            t.get("github_issue_number"),
            t.get("github_issue_url"),
            t.get("cozum_plani"),
            t.get("faz_id"),
            t.get("efor"),
            t.get("triage_notu"),
            gecmis,
        ))
        n += 1

    conn.commit()
    log("📋", f"{n} talep aktarıldı → talepler tablosu", GREEN)
    return n


# ==============================================================================
# ÇÖZÜM PLANLARI
# ==============================================================================

def cozum_planlari_aktar(conn):
    if not COZUM_DIR.exists():
        log("⚠️", f"Bulunamadı: {COZUM_DIR}", YELLOW)
        return 0

    md_dosyalari = sorted(COZUM_DIR.glob("TALEP-*.md"))
    n = 0
    for md in md_dosyalari:
        talep_id = md.stem  # TALEP-001
        icerik = md.read_text(encoding="utf-8")
        mtime = str(md.stat().st_mtime)
        conn.execute("""
            INSERT OR REPLACE INTO cozum_planlari (talep_id, icerik, guncelleme)
            VALUES (?,?,?)
        """, (talep_id, icerik, mtime))
        n += 1

    conn.commit()
    log("📄", f"{n} çözüm planı aktarıldı → cozum_planlari tablosu", GREEN)
    return n


# ==============================================================================
# SPRİNTLER & PANO GÖREVLERİ
# ==============================================================================

def pano_aktar(conn):
    if not PANO_JSON.exists():
        log("⚠️", f"Bulunamadı: {PANO_JSON}", YELLOW)
        return 0, 0

    with open(PANO_JSON, encoding="utf-8") as f:
        veri = json.load(f)

    sprints = veri.get("sprints", [])
    ns, nt = 0, 0

    for s in sprints:
        conn.execute("""
            INSERT OR REPLACE INTO sprintler
            (id, ad, hedef, planlanan_gun, sira, durum,
             planlanan_baslangic, planlanan_bitis, gercek_baslangic, gercek_bitis)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (
            s.get("id"),
            s.get("name"),
            s.get("goal"),
            s.get("planned_days"),
            s.get("order"),
            s.get("status"),
            s.get("planned_start"),
            s.get("planned_end"),
            s.get("actual_start"),
            s.get("actual_end"),
        ))
        ns += 1

        for t in s.get("tasks", []):
            conn.execute("""
                INSERT OR REPLACE INTO pano_gorevleri
                (id, sprint_id, baslik, aciklama, rol, phase, ciktilar, bagimlilik,
                 durum, deneme, not_, baslangic, bitis, sure_s)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                t.get("id"),
                s.get("id"),
                t.get("title"),
                t.get("description"),
                t.get("role"),
                t.get("phase"),
                json.dumps(t.get("outputs", []), ensure_ascii=False),
                json.dumps(t.get("depends_on", []), ensure_ascii=False),
                t.get("status"),
                t.get("attempts"),
                t.get("note"),
                t.get("started_at"),
                t.get("finished_at"),
                t.get("duration_s"),
            ))
            nt += 1

    conn.commit()
    log("📊", f"{ns} sprint + {nt} görev aktarıldı → sprintler, pano_gorevleri tabloları", GREEN)
    return ns, nt


# ==============================================================================
# EKİP ROLLERİ
# ==============================================================================

def ekip_rolleri_aktar(conn):
    if not ORG_CHART.exists():
        log("⚠️", f"Bulunamadı: {ORG_CHART}", YELLOW)
        return 0

    with open(ORG_CHART, encoding="utf-8") as f:
        veri = json.load(f)

    hierarchy = veri.get("hierarchy", [])
    n = 0
    for r in hierarchy:
        conn.execute("""
            INSERT OR REPLACE INTO ekip_rolleri
            (id, unvan, sistem_promptu, girdiler, ciktilar, sahne, backend, model, max_kelime)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            r.get("id"),
            r.get("title"),
            r.get("system_prompt"),
            json.dumps(r.get("inputs", []), ensure_ascii=False),
            json.dumps(r.get("outputs", []), ensure_ascii=False),
            r.get("stage"),
            r.get("backend"),
            r.get("model"),
            r.get("max_words"),
        ))
        n += 1

    conn.commit()
    log("👥", f"{n} ekip rolü aktarıldı → ekip_rolleri tablosu", GREEN)
    return n


# ==============================================================================
# MOTOR STATE, KOTA, FAZLAR, MALİYETLER
# ==============================================================================

def state_aktar(conn):
    if not STATE_JSON.exists():
        return 0
    try:
        data = json.loads(STATE_JSON.read_text(encoding="utf-8"))
        for k, v in data.items():
            conn.execute(
                "INSERT OR REPLACE INTO studio_state (anahtar, deger) VALUES (?, ?)",
                (k, json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else str(v))
            )
        conn.commit()
        log("🔄", f"Motor state ({len(data)} anahtar) aktarıldı → studio_state tablosu", GREEN)
        return len(data)
    except Exception as e:
        log("⚠️", f"State aktarım hatası: {e}", YELLOW)
        return 0


def kota_aktar(conn):
    if not KOTA_JSON.exists():
        return 0
    try:
        data = json.loads(KOTA_JSON.read_text(encoding="utf-8"))
        tarih = data.get("tarih")
        if tarih:
            conn.execute("""
                INSERT OR REPLACE INTO gunluk_kota (tarih, gorev, maliyet, ek_gorev, ek_butce)
                VALUES (?, ?, ?, ?, ?)
            """, (
                tarih,
                data.get("gorev", 0),
                data.get("maliyet", 0.0),
                data.get("ek_gorev", 0),
                data.get("ek_butce", 0.0)
            ))
            conn.commit()
            log("💰", f"Günlük kota ({tarih}) aktarıldı → gunluk_kota tablosu", GREEN)
            return 1
    except Exception as e:
        log("⚠️", f"Kota aktarım hatası: {e}", YELLOW)
    return 0


def fazlar_aktar(conn):
    if not FAZLAR_JSON.exists():
        return 0
    try:
        data = json.loads(FAZLAR_JSON.read_text(encoding="utf-8"))
        fazlar = data.get("fazlar", [])
        for f in fazlar:
            conn.execute("""
                INSERT OR REPLACE INTO fazlar (id, ad, aciklama, durum, hedef_tarih, kilitli, onkosul_faz)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                f.get("id"),
                f.get("ad"),
                f.get("aciklama"),
                f.get("durum"),
                f.get("hedef_tarih"),
                1 if f.get("kilitli") else 0,
                f.get("onkosul_faz")
            ))
        conn.commit()
        log("🎯", f"{len(fazlar)} faz aktarıldı → fazlar tablosu", GREEN)
        return len(fazlar)
    except Exception as e:
        log("⚠️", f"Faz aktarım hatası: {e}", YELLOW)
        return 0


def maliyetler_aktar(conn):
    if not COSTS_JSONL.exists():
        return 0
    n = 0
    try:
        with open(COSTS_JSONL, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                c = json.loads(line)
                conn.execute("""
                    INSERT INTO maliyet_kayitlari (tarih, rol, backend, model, cost_usd, detay)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    c.get("timestamp") or c.get("tarih"),
                    c.get("role") or c.get("rol"),
                    c.get("backend"),
                    c.get("model"),
                    c.get("cost_usd") or 0.0,
                    json.dumps(c, ensure_ascii=False)
                ))
                n += 1
        conn.commit()
        if n:
            log("💵", f"{n} maliyet kaydı aktarıldı → maliyet_kayitlari tablosu", GREEN)
        return n
    except Exception as e:
        log("⚠️", f"Maliyet aktarım hatası: {e}", YELLOW)
        return 0


# ==============================================================================
# RAPOR
# ==============================================================================

def rapor_yazdir(conn):
    print(f"\n  {BOLD}{CYAN}── Veritabanı Özeti ({DB_PATH.name}) ────────────────────{NC}")
    tablolar = [
        "talepler", "cozum_planlari", "sprintler", "pano_gorevleri",
        "ekip_rolleri", "studio_state", "gunluk_kota", "maliyet_kayitlari", "fazlar"
    ]
    for tablo in tablolar:
        try:
            sayi = conn.execute(f"SELECT COUNT(*) FROM {tablo}").fetchone()[0]
            print(f"  {GREEN}✓{NC}  {tablo:<25} {sayi:>4} kayıt")
        except Exception as e:
            print(f"  {RED}✗{NC}  {tablo:<25} HATA: {e}")

    # Örnek sorgu
    print(f"\n  {BOLD}Örnek sorgu — Açık talepler:{NC}")
    rows = conn.execute("""
        SELECT id, oncelik, baslik FROM talepler
        WHERE durum NOT IN ('COZULDU', 'KAPATILDI')
        ORDER BY tarih DESC
        LIMIT 5
    """).fetchall()
    for r in rows:
        print(f"    {r[0]}  [{r[1]}]  {r[2][:60]}")

    print(f"\n  {BOLD}Örnek sorgu — Son sprint durumu:{NC}")
    rows = conn.execute("""
        SELECT s.id, s.ad, COUNT(g.id) as gorev, s.durum
        FROM sprintler s
        LEFT JOIN pano_gorevleri g ON g.sprint_id = s.id
        GROUP BY s.id ORDER BY s.sira DESC LIMIT 3
    """).fetchall()
    for r in rows:
        print(f"    {r[0]}  {str(r[1])[:40]:<40}  {r[2]} görev  [{r[3]}]")
    print()


# ==============================================================================
# ANA AKIŞ
# ==============================================================================

def main():
    print(f"\n{BOLD}{CYAN}╔══════════════════════════════════════════════════════╗")
    print(f"║  🗄️   elektriklioto — JSON → SQLite Migration        ║")
    print(f"╚══════════════════════════════════════════════════════╝{NC}\n")

    if KONTROL_MODU:
        log("ℹ️", "KONTROL MODU — veritabanına yazılmayacak.", YELLOW)
        log("ℹ️", f"Hedef: {DB_PATH}", CYAN)
        print()

    conn = sqlite3.connect(DB_PATH if not KONTROL_MODU else ":memory:")
    conn.execute("PRAGMA journal_mode=WAL")   # Eş zamanlı erişim güvenliği
    conn.execute("PRAGMA foreign_keys=ON")

    veritabani_olustur(conn)
    talepler_aktar(conn)
    cozum_planlari_aktar(conn)
    pano_aktar(conn)
    ekip_rolleri_aktar(conn)
    state_aktar(conn)
    kota_aktar(conn)
    fazlar_aktar(conn)
    maliyetler_aktar(conn)

    rapor_yazdir(conn)
    conn.close()

    if KONTROL_MODU:
        log("✅", "Kontrol tamamlandı. Gerçek migration için --kontrol bayrağını kaldırın.", GREEN)
    else:
        log("✅", f"Migration tamamlandı → {DB_PATH}", GREEN)
        log("💡", "JSON dosyaları korundu. İleride _arsiv/ altına taşıyabilirsiniz.", CYAN)
    print()


if __name__ == "__main__":
    main()
