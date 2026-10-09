#!/usr/bin/env python3
"""Brief görüşmesi (issue #173): müşteri temsilcisi, ürün sahibi ve CTO ile iletişimle proje_kapsami.md genişler.

Kullanıcı kısa/insani bir tohum brief yazar. Roller sırayla TEK, kısa soru sorar; kullanıcı cevaplar; cevap kullanıcının KENDİ SÖZLERİYLE
rol etiketli blok olarak brief'e işlenir (rol yalnızca bir konu başlığı ve kısa bir not ekler, yeni olgu eklemez).
Durum: workspace/docs/brief_gorusme.json. Model çağrısı: studio_engine.query_claude (rolün motoru: org_chart > panel override > varsayılan).
LLM yoksa (STUDIO_SOHBET_AGENT=0 ya da hata) soru yedek listeden gelir, not boş kalır; cevap yine brief'e işlenir.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

STATE = ROOT / "workspace" / "docs" / "brief_gorusme.json"
ROLLER = ["musteri_temsilcisi", "product_owner", "cto"]
UNVAN = {"musteri_temsilcisi": "Müşteri Temsilcisi", "product_owner": "Ürün Sahibi", "cto": "CTO"}
ODAK = {
    "musteri_temsilcisi": "iş hedefi, kimin için, ne zaman, neyin başarı sayılacağı, vazgeçilmezler ve istenmeyenler",
    "product_owner": "kapsam sınırı, öncelik sırası, kabul ölçütü, hangi ekran/özellik ilk, neyi bilerek dışarıda bırakırız",
    "cto": "teknik kısıtlar, entegrasyonlar, veri kaynakları, güvenlik/gizlilik, performans, riskler ve bağımlılıklar",
}
YEDEK_SORULAR = {
    "musteri_temsilcisi": "Bu proje bittiğinde sizin için en önemli sonuç ne olacak, neye bakıp 'oldu' diyeceksiniz?",
    "product_owner": "Hangi ekranlar/özellikler ilk gelmeli, hangilerini bilerek sona veya dışarıda bırakabiliriz?",
    "cto": "Uyulması gereken teknik bir kısıt, entegrasyon ya da güvenlik kuralı var mı?",
}
KURALLAR = (
    "Gerçek bir meslektaş gibi konuş: sıcak, doğal, kısa. Resmî şablon, madde işaretli ders ve jargon yok. "
    "Kullanıcı bir yazılım ekibinin müşterisidir; sorunu ona anlayacağı dille sor. TEK soru sor (en fazla iki cümle). "
    "Brief'te veya önceki cevaplarda zaten cevaplanmış şeyi sorma. Gerekirse 2-3 kısa seçenek öner ama serbest cevaba açık bırak. "
    "Bilmediğin şeyi uydurma, varsayımı varsayım diye söyle."
)


def _simdi() -> str:
    return datetime.now().isoformat(timespec="seconds")


def brief_yolu() -> Path:
    for p in (ROOT / "workspace" / "docs" / "proje_kapsami.md", ROOT / "proje_kapsami.md"):
        if p.exists():
            return p
    return ROOT / "workspace" / "docs" / "proje_kapsami.md"


def yukle() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"durum": "acik", "turlar": [], "olusturma": _simdi()}


def kaydet(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")


def _llm(rol: str, system: str, user: str) -> str:
    """Rolün motoruyla tek çağrı. Testlerde değiştirilir."""
    if os.getenv("STUDIO_SOHBET_AGENT", "1") == "0":
        raise RuntimeError("LLM kapalı")
    import studio_engine as E
    org = json.loads(E.resolve_doc("org_chart.json").read_text(encoding="utf-8"))
    agent = next((a for a in org["hierarchy"] if a["id"] == rol), {"id": rol, "title": UNVAN[rol], "stage": "service"})
    backend, model, effort, _ = E.resolve_engine(agent, {})
    meta = {"seq": E._trace_seq(), "role": rol, "title": UNVAN[rol], "target": "brief_gorusme", "backend": backend, "model": model, "tools": []}
    return E.query_claude(system, user, backend, model, effort, meta, tools=None)


def _json(ham: str) -> dict:
    t = (ham or "").strip().strip("`")
    t = t[4:] if t.lower().startswith("json") else t
    i, j = t.find("{"), t.rfind("}")
    if i == -1 or j <= i:
        raise ValueError("JSON yok")
    return json.loads(t[i:j + 1])


def _gecmis(s: dict) -> str:
    return "\n".join(f"[{UNVAN[t['rol']]}] {t['soru']}\n[Kullanıcı] {t.get('cevap') or '(cevaplanmadı)'}" for t in s["turlar"][-12:]) or "(henüz görüşme yok)"


def siradaki_rol(s: dict) -> str:
    return ROLLER[len(s["turlar"]) % len(ROLLER)]


def _kontrol_noktasi() -> None:
    """Brief kararları verildi: durum git'e commit + etiket olarak gönderilir (geri dönüş noktası, #275)."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import kontrol_noktasi as KN
        KN.olustur("brief-karari", "brief görüşmesi tamamlandı", Path(__file__).resolve().parent.parent)
    except Exception:
        pass


def soru_uret() -> dict:
    """Bekleyen cevapsız soru varsa onu döndürür; yoksa sıradaki rol yeni bir soru sorar. {tur|None, bitti}"""
    s = yukle()
    if s["durum"] == "tamam":
        return {"tur": None, "bitti": True}
    for t in s["turlar"]:
        if t.get("cevap") is None:
            return {"tur": t, "bitti": False}
    rol = siradaki_rol(s)
    brief = brief_yolu().read_text(encoding="utf-8")[:30_000] if brief_yolu().exists() else ""
    sistem = (f"Sen yazılım stüdyosunun {UNVAN[rol]} rolüsün. Odağın: {ODAK[rol]}. {KURALLAR}\n"
              'Yanıtın yalnızca JSON: {"soru": "...", "secenekler": ["..."], "bitti": false}. '
              'Brief artık yeterince netse {"bitti": true, "soru": ""} döndür.')
    kullanici = f"===== BRIEF =====\n{brief}\n\n===== ŞU ANA KADARKİ GÖRÜŞME =====\n{_gecmis(s)}\n\nSıradaki tek sorunu üret."
    try:
        v = _json(_llm(rol, sistem, kullanici))
    except Exception:
        v = {"soru": YEDEK_SORULAR[rol], "secenekler": [], "bitti": False}
    if v.get("bitti") and len(s["turlar"]) >= len(ROLLER):
        s["durum"] = "tamam"
        kaydet(s)
        _kontrol_noktasi()
        return {"tur": None, "bitti": True}
    tur = {"id": len(s["turlar"]) + 1, "rol": rol, "soru": str(v.get("soru") or YEDEK_SORULAR[rol]).strip()[:600],
           "secenekler": [str(x)[:120] for x in (v.get("secenekler") or [])][:3], "cevap": None, "zaman": _simdi()}
    s["turlar"].append(tur)
    kaydet(s)
    return {"tur": tur, "bitti": False}


def _brief_ekle(rol: str, konu: str, cevap: str, not_: str) -> None:
    p = brief_yolu()
    metin = p.read_text(encoding="utf-8") if p.exists() else ""
    isaret = f"<!-- rol: {rol} -->"
    satir = f"- **{konu}:** {cevap.strip()}" + (f"\n  - _{UNVAN[rol]} notu:_ {not_.strip()}" if not_.strip() else "")
    if f"## Görüşmeden eklenenler" not in metin:
        metin = metin.rstrip("\n") + "\n\n## Görüşmeden eklenenler\n"
    metin = metin.rstrip("\n") + f"\n{isaret}\n{satir}\n"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(metin, encoding="utf-8")


def cevapla(cevap: str) -> dict:
    cevap = (cevap or "").strip()
    if not cevap:
        return {"ok": False, "mesaj": "cevap boş"}
    s = yukle()
    tur = next((t for t in s["turlar"] if t.get("cevap") is None), None)
    if tur is None:
        return {"ok": False, "mesaj": "cevaplanacak soru yok"}
    sistem = (f"Sen {UNVAN[tur['rol']]} rolündesin. Kullanıcının cevabını brief'e işlemek için iki şey üret: kısa bir konu başlığı (en fazla 5 kelime) "
              "ve rolünün bakışıyla en fazla 30 kelimelik bir not (risk, bağımlılık ya da netleştirme). Kullanıcının söylemediği HİÇBİR olguyu ekleme. "
              'Yanıtın yalnızca JSON: {"konu": "...", "not": "..."}.')
    try:
        v = _json(_llm(tur["rol"], sistem, f"Soru: {tur['soru']}\nKullanıcının cevabı: {cevap}"))
    except Exception:
        v = {}
    konu = str(v.get("konu") or " ".join(tur["soru"].split()[:5])).strip().rstrip("?.:")[:60]
    not_ = str(v.get("not") or "").strip()[:300]
    tur.update(cevap=cevap, konu=konu, **{"not": not_}, cevap_zaman=_simdi())
    _brief_ekle(tur["rol"], konu, cevap, not_)
    kaydet(s)
    return {"ok": True, "tur": tur}


def bitir(durum: str = "tamam") -> dict:
    s = yukle()
    s["durum"] = durum
    kaydet(s)
    if durum == "tamam":
        _kontrol_noktasi()
    return {"ok": True}


def sifirla() -> dict:
    if STATE.exists():
        STATE.rename(STATE.with_suffix(f".{datetime.now():%Y%m%d%H%M%S}.json"))
    return {"ok": True}


def ozet() -> dict:
    s = yukle()
    p = brief_yolu()
    return {"durum": s["durum"], "turlar": s["turlar"], "brief_yol": str(p.relative_to(ROOT)) if p.exists() else "",
            "brief_kb": round(p.stat().st_size / 1024, 1) if p.exists() else 0}


if __name__ == "__main__":
    print(json.dumps(ozet(), ensure_ascii=False, indent=1))
