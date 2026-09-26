#!/usr/bin/env python3
"""
scripts/musteri_temsilcisi.py
Digital Software Studio — Müşteri Sohbet Odası Temsilcisi

Müşteriyle doğal bir sohbet yürüterek talebi netleştirir. Netleşen talep
'taslak' olarak müşteriye sunulur; müşteri ONAYLAYINCA musteri_talepleri
yeni_talep() üzerinden havuza girer ve mevcut triage/planlama zinciri
değişmeden işler.

Veriler studio.db'de tutulur: sohbet_oturumlari + sohbet_mesajlari.

Çevre değişkenleri:
  STUDIO_SOHBET_AGENT=0  → LLM devre dışı; mesaj doğrudan taslak talebe çevrilir.
"""

import json
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import studio_board as B
import musteri_talepleri as MT

ROL_ID = "musteri_temsilcisi"
SOHBET_AGENT = __import__("os").getenv("STUDIO_SOHBET_AGENT", "1") != "0"

VARSAYILAN_AGENT = {
    "id": ROL_ID,
    "title": "Müşteri Temsilcisi",
    "system_prompt": (
        "Sen Digital Software Studio'nun müşteri temsilcisisin. Müşteriyle "
        "sohbet ederek talebini netleştirirsin. Yanıtın her zaman geçerli JSON: "
        '{"yanit": "...", "taslak": null | {"tur": "HATA", "oncelik": "NORMAL", '
        '"sayfa_url": "/", "baslik": "...", "aciklama": "..."}}'
    ),
    "outputs": [],
    "stage": "service",
}


def _simdi() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _agent() -> dict:
    """org_chart.json'daki musteri_temsilcisi rolü; yoksa varsayılan."""
    try:
        org = json.loads((ROOT / "org_chart.json").read_text(encoding="utf-8"))
        for a in org.get("hierarchy", []):
            if a.get("id") == ROL_ID:
                return a
    except Exception:
        pass
    return VARSAYILAN_AGENT


# ---------------------------------------------------------------- oturum

def oturum_ac(musteri_adi: str = "") -> str:
    oid = uuid.uuid4().hex[:12]
    conn = B.db_conn()
    try:
        conn.execute(
            "INSERT INTO sohbet_oturumlari (id, olusturma, son_aktivite, durum) "
            "VALUES (?, ?, ?, 'ACIK')",
            (oid, _simdi(), _simdi()))
        conn.commit()
    finally:
        conn.close()
    B.audit("sohbet", "oturum_acildi", detay={"oturum": oid, "musteri": musteri_adi})
    return oid


def _oturum_var(oid: str) -> bool:
    conn = B.db_conn()
    try:
        row = conn.execute(
            "SELECT id FROM sohbet_oturumlari WHERE id = ?", (oid,)).fetchone()
        return row is not None
    finally:
        conn.close()


def mesajlar(oid: str) -> list[dict]:
    conn = B.db_conn()
    try:
        rows = conn.execute(
            "SELECT id, zaman, gonderen, icerik, taslak, talep_id "
            "FROM sohbet_mesajlari WHERE oturum_id = ? ORDER BY id",
            (oid,)).fetchall()
        out = []
        for r in rows:
            m = dict(r)
            if m.get("taslak"):
                try:
                    m["taslak"] = json.loads(m["taslak"])
                except Exception:
                    m["taslak"] = None
            out.append(m)
        return out
    finally:
        conn.close()


def _mesaj_ekle(oid: str, gonderen: str, icerik: str,
                taslak: dict | None = None, talep_id: str = None) -> int:
    conn = B.db_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO sohbet_mesajlari "
            "(oturum_id, zaman, gonderen, icerik, taslak, talep_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (oid, _simdi(), gonderen, icerik,
             json.dumps(taslak, ensure_ascii=False) if taslak else None,
             talep_id))
        conn.execute(
            "UPDATE sohbet_oturumlari SET son_aktivite = ? WHERE id = ?",
            (_simdi(), oid))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# ---------------------------------------------------------------- ajan

def _gecmis_promptu(oid: str, sinir: int = 24) -> str:
    satirlar = []
    for m in mesajlar(oid)[-sinir:]:
        kim = "Müşteri" if m["gonderen"] == "musteri" else "Temsilci"
        satirlar.append(f"{kim}: {m['icerik']}")
        if m.get("taslak"):
            satirlar.append(f"[Taslak gösterildi: {json.dumps(m['taslak'], ensure_ascii=False)}]")
    return "\n".join(satirlar)


def _ajan_cagri(oid: str) -> dict:
    """LLM temsilcisini çağırır; {yanit, taslak} döner."""
    agent = _agent()
    try:
        import studio_engine as E
        backend, model, effort, tools = E.resolve_engine(agent)
        user = (
            "===== SOHBET GEÇMİŞİ =====\n"
            f"{_gecmis_promptu(oid)}\n\n"
            "===== GÖREV =====\n"
            "Yukarıdaki sohbete göre müşteriye vereceğin yanıtı JSON olarak üret. "
            "Talep yeterince netleştiyse 'taslak'ı doldur; değilse null bırakıp "
            "netleştirici soru sor."
        )
        meta = {"seq": E._trace_seq(), "role": ROL_ID,
                "title": agent.get("title", "Müşteri Temsilcisi"),
                "target": f"sohbet:{oid}", "backend": backend,
                "model": model, "tools": []}
        ham = E.query_claude(agent["system_prompt"], user,
                             backend, model, effort, meta, tools=None)
    except Exception as e:
        raise RuntimeError(f"Temsilci yanıtı alınamadı: {e}")

    temiz = ham.strip()
    if temiz.startswith("```"):
        temiz = temiz.strip("`")
        if temiz.lower().startswith("json"):
            temiz = temiz[4:]
    i, j = temiz.find("{"), temiz.rfind("}")
    if i == -1 or j <= i:
        return {"yanit": ham.strip()[:2000], "taslak": None}
    try:
        veri = json.loads(temiz[i:j + 1])
    except json.JSONDecodeError:
        return {"yanit": ham.strip()[:2000], "taslak": None}

    taslak = veri.get("taslak")
    if not isinstance(taslak, dict) or not (taslak.get("baslik") and taslak.get("aciklama")):
        taslak = None
    else:
        if str(taslak.get("tur", "")).upper() not in MT.TURLER:
            taslak["tur"] = "HATA"
        if str(taslak.get("oncelik", "")).upper() not in MT.ONCELIKLER:
            taslak["oncelik"] = "NORMAL"
    return {"yanit": str(veri.get("yanit") or "").strip() or "(boş yanıt)",
            "taslak": taslak}


def mesaj_gonder(oid: str, icerik: str) -> dict:
    """Müşteri mesajını işler, temsilci yanıtını üretir ve saklar."""
    if not oid or not _oturum_var(oid):
        oid = oturum_ac()
    icerik = (icerik or "").strip()
    if not icerik:
        raise ValueError("Boş mesaj.")

    _mesaj_ekle(oid, "musteri", icerik)

    if SOHBET_AGENT:
        try:
            sonuc = _ajan_cagri(oid)
        except Exception as e:
            sonuc = {
                "yanit": (f"Temsilciye şu an ulaşılamıyor ({e}). "
                          "Mesajınız kaydedildi; dilerseniz yine de "
                          "'Talep Olarak Kaydet' ile havuza düşürebilirsiniz."),
                "taslak": None,
            }
    else:
        sonuc = {
            "yanit": ("Mesajınız alındı. (Sohbet asistanı kapalı — "
                      "STUDIO_SOHBET_AGENT=0) Aşağıdaki taslağı onaylayarak "
                      "talebinizi havuza gönderebilirsiniz."),
            "taslak": {"tur": "HATA", "oncelik": "NORMAL",
                       "sayfa_url": "/", "baslik": icerik[:80],
                       "aciklama": icerik},
        }

    yanit_metni = sonuc["yanit"]
    if sonuc.get("taslak"):
        t = sonuc["taslak"]
        yanit_metni += (
            "\n\n📋 Taslak talep hazır:"
            f"\n• Tür: {t.get('tur')} · Öncelik: {t.get('oncelik')} · Sayfa: {t.get('sayfa_url')}"
            f"\n• Başlık: {t.get('baslik')}"
            "\nOnaylıyor musunuz? (Onayla / düzeltme isteği yazın)"
        )
    mid = _mesaj_ekle(oid, "asistan", yanit_metni, taslak=sonuc.get("taslak"))
    B.audit("sohbet", "mesaj", detay={"oturum": oid, "taslak": bool(sonuc.get("taslak"))})
    return {"oturum_id": oid, "mesaj_id": mid, **sonuc}


# ---------------------------------------------------------------- taslak onay

def _mesaj_getir(mesaj_id: int) -> dict | None:
    conn = B.db_conn()
    try:
        row = conn.execute(
            "SELECT * FROM sohbet_mesajlari WHERE id = ?", (mesaj_id,)).fetchone()
        if not row:
            return None
        m = dict(row)
        if m.get("taslak"):
            try:
                m["taslak"] = json.loads(m["taslak"])
            except Exception:
                m["taslak"] = None
        return m
    finally:
        conn.close()


def taslak_onayla(oid: str, mesaj_id: int) -> dict:
    """Taslak talebi müşteri onayıyla talep havuzuna aktarır."""
    m = _mesaj_getir(mesaj_id)
    if not m or m.get("oturum_id") != oid or not m.get("taslak"):
        raise ValueError("Onaylanacak taslak bulunamadı.")

    t = m["taslak"]
    yeni = MT.yeni_talep(
        t.get("tur", "HATA"), t.get("baslik", "Sohbet talebi"),
        t.get("aciklama", ""), oncelik=t.get("oncelik", "NORMAL"),
        sayfa_url=t.get("sayfa_url", "/"))

    conn = B.db_conn()
    try:
        conn.execute(
            "UPDATE sohbet_mesajlari SET talep_id = ?, taslak = NULL WHERE id = ?",
            (yeni["id"], mesaj_id))
        conn.commit()
    finally:
        conn.close()

    _mesaj_ekle(oid, "sistem",
                f"✅ Talebiniz havuza alındı: {yeni['id']} — \"{yeni['baslik']}\". "
                "Stüdyo ekibi triage ve planlamayı otomatik yürütecek; "
                "durumunu Taleplerim listesinden izleyebilirsiniz.",
                talep_id=yeni["id"])
    B.audit("sohbet", "taslak_onaylandi", talep_id=yeni["id"],
            detay={"oturum": oid})
    return {"talep_id": yeni["id"], "talep": yeni}


def taslak_reddet(oid: str, mesaj_id: int) -> dict:
    """Taslak talebi iptal eder."""
    m = _mesaj_getir(mesaj_id)
    if not m or m.get("oturum_id") != oid or not m.get("taslak"):
        raise ValueError("İptal edilecek taslak bulunamadı.")

    conn = B.db_conn()
    try:
        conn.execute(
            "UPDATE sohbet_mesajlari SET taslak = NULL WHERE id = ?",
            (mesaj_id,))
        conn.commit()
    finally:
        conn.close()

    _mesaj_ekle(oid, "sistem",
                "Taslak iptal edildi. Talebinizi yeniden anlatabilir veya "
                "düzeltme yapabilirsiniz.")
    B.audit("sohbet", "taslak_reddedildi", detay={"oturum": oid})
    return {"ok": True}


def musteri_talepleri() -> list[dict]:
    """Sohbet odasından açılmış talepler (oturum üzerinden ilişkili)."""
    conn = B.db_conn()
    try:
        rows = conn.execute(
            "SELECT DISTINCT m.talep_id FROM sohbet_mesajlari m "
            "WHERE m.talep_id IS NOT NULL").fetchall()
        ids = [r["talep_id"] for r in rows]
    finally:
        conn.close()
    return [t for t in (MT.getir(i) for i in ids) if t]
