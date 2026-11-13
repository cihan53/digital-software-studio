#!/usr/bin/env python3
"""Brief görüşmesi (issue #173 & #336): müşteri temsilcisi, ürün sahibi, CTO ve DevOps ile iletişimle proje_kapsami.md genişler.

Kullanıcı kısa/insani bir tohum brief yazar. Roller sırayla TEK, kısa soru sorar; kullanıcı cevaplar; cevap kullanıcının KENDİ SÖZLERİYLE
rol etiketli blok olarak brief'e işlenir (rol yalnızca bir konu başlığı ve kısa bir not ekler, yeni olgu eklemez).
Canlı süreçte deploy veya altyapı kısıtları için mod='devops' ile DevOps & CTO turu başlatılabilir.
Durum: workspace/docs/brief_gorusme.json. Model çağrısı: studio_engine.query_claude (rolün motoru: org_chart > panel override > varsayılan).
LLM yoksa (STUDIO_SOHBET_AGENT=0 ya da hata) soru yedek listeden gelir, not boş kalır; cevap yine brief'e işlenir.
"""
from __future__ import annotations

import argparse
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

ROLLER_MODLAR = {
    "genel": ["musteri_temsilcisi", "product_owner", "cto"],
    "devops": ["devops_engineer", "cto"],
}
ROLLER = ROLLER_MODLAR["genel"]

UNVAN = {
    "musteri_temsilcisi": "Müşteri Temsilcisi",
    "product_owner": "Ürün Sahibi",
    "cto": "CTO",
    "devops_engineer": "DevOps Mühendisi",
}

ODAK = {
    "musteri_temsilcisi": "iş hedefi, kimin için, ne zaman, neyin başarı sayılacağı, vazgeçilmezler ve istenmeyenler",
    "product_owner": "kapsam sınırı, öncelik sırası, kabul ölçütü, hangi ekran/özellik ilk, neyi bilerek dışarıda bırakırız",
    "cto": "teknik kısıtlar, entegrasyonlar, veri kaynakları, güvenlik/gizlilik, performans, riskler ve bağımlılıklar",
    "devops_engineer": "CI/CD hatları, derleme (build) ve deploy hataları, ortam değişkenleri, sunucu altyapısı ve container gereksinimleri",
}

YEDEK_SORULAR = {
    "musteri_temsilcisi": "Bu proje bittiğinde sizin için en önemli sonuç ne olacak, neye bakıp 'oldu' diyeceksiniz?",
    "product_owner": "Hangi ekranlar/özellikler ilk gelmeli, hangilerini bilerek sona veya dışarıda bırakabiliriz?",
    "cto": "Uyulması gereken teknik bir kısıt, entegrasyon ya da güvenlik kuralı var mı?",
    "devops_engineer": "Dağıtım (deploy) veya altyapı sürecinde karşılaştığınız sorun ya da kısıt tam olarak nedir?",
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
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"durum": "acik", "mod": "genel", "turlar": [], "olusturma": _simdi()}


def kaydet(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")


def yeni_gorusme(mod: str = "genel") -> dict:
    """Belirtilen mod ile (genel veya devops) yeni bir görüşme oturumu başlatır."""
    s = {"durum": "acik", "mod": mod, "turlar": [], "olusturma": _simdi()}
    kaydet(s)
    return s


def _llm(rol: str, system: str, user: str) -> str:
    """Rolün motoruyla tek çağrı. Testlerde değiştirilir."""
    if os.getenv("STUDIO_SOHBET_AGENT", "1") == "0":
        raise RuntimeError("LLM kapalı")
    import studio_engine as E
    org = json.loads(E.resolve_doc("org_chart.json").read_text(encoding="utf-8"))
    agent = next((a for a in org["hierarchy"] if a["id"] == rol), {"id": rol, "title": UNVAN.get(rol, rol), "stage": "service"})
    backend, model, effort, _ = E.resolve_engine(agent, {})
    meta = {"seq": E._trace_seq(), "role": rol, "title": UNVAN.get(rol, rol), "target": "brief_gorusme", "backend": backend, "model": model, "tools": []}
    return E.query_claude(system, user, backend, model, effort, meta, tools=None)


def _json(ham: str) -> dict:
    t = (ham or "").strip().strip("`")
    t = t[4:] if t.lower().startswith("json") else t
    i, j = t.find("{"), t.rfind("}")
    if i == -1 or j <= i:
        raise ValueError("JSON yok")
    return json.loads(t[i:j + 1])


def _gecmis(s: dict) -> str:
    return "\n".join(f"[{UNVAN.get(t['rol'], t['rol'])}] {t['soru']}\n[Kullanıcı] {t.get('cevap') or '(cevaplanmadı)'}" for t in s.get("turlar", [])[-12:]) or "(henüz görüşme yok)"


def siradaki_rol(s: dict) -> str:
    mod = s.get("mod", "genel")
    roller = ROLLER_MODLAR.get(mod, ROLLER_MODLAR["genel"])
    return roller[len(s.get("turlar", [])) % len(roller)]


def _kontrol_noktasi() -> None:
    """Brief kararları verildi: durum git'e commit + etiket olarak gönderilir (geri dönüş noktası, #275)."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import kontrol_noktasi as KN
        KN.olustur("brief-karari", "brief görüşmesi tamamlandı", Path(__file__).resolve().parent.parent)
    except Exception:
        pass


def _devops_talebi_olustur(s: dict) -> str | None:
    """DevOps brief görüşmesi tamamlandığında stüdyoya otomatik TALEP-XXX açar."""
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import musteri_talepleri as MT
        cevaplar = [f"- {t.get('konu', 'Ayrıntı')}: {t.get('cevap', '')}" for t in s.get("turlar", []) if t.get("cevap")]
        aciklama = "DevOps & Dağıtım Brief Görüşmesi sonucu belirlenen isterler:\n" + "\n".join(cevaplar)
        t = MT.yeni_talep(
            tur="HATA" if any("hata" in c.lower() or "sorun" in c.lower() for c in cevaplar) else "ISTEK",
            baslik="DevOps & Dağıtım İyileştirmesi (Brief)",
            aciklama=aciklama,
            oncelik="YUKSEK",
            sayfa_url="/ci-cd"
        )
        if t and t.get("id"):
            MT.guncelle(t["id"], gorevli_rol="devops_engineer")
            return t["id"]
    except Exception:
        pass
    return None


def soru_uret(mod: str | None = None) -> dict:
    """Bekleyen cevapsız soru varsa onu döndürür; yoksa sıradaki rol yeni bir soru sorar. {tur|None, bitti}"""
    s = yukle()
    if mod and s.get("mod") != mod:
        s = yeni_gorusme(mod)

    if s.get("durum") == "tamam":
        return {"tur": None, "bitti": True}
    for t in s.get("turlar", []):
        if t.get("cevap") is None:
            return {"tur": t, "bitti": False}

    rol = siradaki_rol(s)
    mod_adi = s.get("mod", "genel")
    roller = ROLLER_MODLAR.get(mod_adi, ROLLER_MODLAR["genel"])
    brief = brief_yolu().read_text(encoding="utf-8")[:30_000] if brief_yolu().exists() else ""
    sistem = (f"Sen yazılım stüdyosunun {UNVAN.get(rol, rol)} rolüsün. Odağın: {ODAK.get(rol, '')}. {KURALLAR}\n"
              'Yanıtın yalnızca JSON: {"soru": "...", "secenekler": ["..."], "bitti": false}. '
              'Brief artık yeterince netse {"bitti": true, "soru": ""} döndür.')
    kullanici = f"===== BRIEF =====\n{brief}\n\n===== ŞU ANA KADARKİ GÖRÜŞME =====\n{_gecmis(s)}\n\nSıradaki tek sorunu üret."
    try:
        v = _json(_llm(rol, sistem, kullanici))
    except Exception:
        v = {"soru": YEDEK_SORULAR.get(rol, "Eklemek istediğiniz kısıt veya not var mı?"), "secenekler": [], "bitti": False}

    if v.get("bitti") and len(s.get("turlar", [])) >= len(roller):
        s["durum"] = "tamam"
        kaydet(s)
        _kontrol_noktasi()
        if s.get("mod") == "devops":
            _devops_talebi_olustur(s)
        return {"tur": None, "bitti": True}

    tur = {"id": len(s.get("turlar", [])) + 1, "rol": rol, "soru": str(v.get("soru") or YEDEK_SORULAR.get(rol, "")).strip()[:600],
           "secenekler": [str(x)[:120] for x in (v.get("secenekler") or [])][:3], "cevap": None, "zaman": _simdi()}
    s.setdefault("turlar", []).append(tur)
    kaydet(s)
    return {"tur": tur, "bitti": False}


def _brief_ekle(rol: str, konu: str, cevap: str, not_: str, mod: str = "genel") -> None:
    p = brief_yolu()
    metin = p.read_text(encoding="utf-8") if p.exists() else ""
    isaret = f"<!-- rol: {rol} -->"
    unvan_str = UNVAN.get(rol, rol)
    satir = f"- **{konu}:** {cevap.strip()}" + (f"\n  - _{unvan_str} notu:_ {not_.strip()}" if not_.strip() else "")
    
    baslik = "## DevOps ve Dağıtım Notları" if mod == "devops" else "## Görüşmeden eklenenler"
    if baslik not in metin:
        metin = metin.rstrip("\n") + f"\n\n{baslik}\n"
    metin = metin.rstrip("\n") + f"\n{isaret}\n{satir}\n"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(metin, encoding="utf-8")


def cevapla(cevap: str) -> dict:
    cevap = (cevap or "").strip()
    if not cevap:
        return {"ok": False, "mesaj": "cevap boş"}
    s = yukle()
    tur = next((t for t in s.get("turlar", []) if t.get("cevap") is None), None)
    if tur is None:
        return {"ok": False, "mesaj": "cevaplanacak soru yok"}
    rol_unvani = UNVAN.get(tur['rol'], tur['rol'])
    sistem = (f"Sen {rol_unvani} rolündesin. Kullanıcının cevabını brief'e işlemek için iki şey üret: kısa bir konu başlığı (en fazla 5 kelime) "
              "ve rolünün bakışıyla en fazla 30 kelimelik bir not (risk, bağımlılık ya da netleştirme). Kullanıcının söylemediği HİÇBİR olguyu ekleme. "
              'Yanıtın yalnızca JSON: {"konu": "...", "not": "..."}.')
    try:
        v = _json(_llm(tur["rol"], sistem, f"Soru: {tur['soru']}\nKullanıcının cevabı: {cevap}"))
    except Exception:
        v = {}
    konu = str(v.get("konu") or " ".join(tur["soru"].split()[:5])).strip().rstrip("?.:")[:60]
    not_ = str(v.get("not") or "").strip()[:300]
    tur.update(cevap=cevap, konu=konu, **{"not": not_}, cevap_zaman=_simdi())
    _brief_ekle(tur["rol"], konu, cevap, not_, s.get("mod", "genel"))
    kaydet(s)
    return {"ok": True, "tur": tur}


def bitir(durum: str = "tamam") -> dict:
    s = yukle()
    s["durum"] = durum
    kaydet(s)
    if durum == "tamam":
        _kontrol_noktasi()
        if s.get("mod") == "devops":
            _devops_talebi_olustur(s)
    return {"ok": True}


def sifirla() -> dict:
    if STATE.exists():
        STATE.rename(STATE.with_suffix(f".{datetime.now():%Y%m%d%H%M%S}.json"))
    return {"ok": True}


def ozet() -> dict:
    s = yukle()
    p = brief_yolu()
    return {"durum": s.get("durum", "acik"), "mod": s.get("mod", "genel"), "turlar": s.get("turlar", []),
            "brief_yol": str(p.relative_to(ROOT)) if p.exists() else "",
            "brief_kb": round(p.stat().st_size / 1024, 1) if p.exists() else 0}


def interaktif_terminal(mod: str = "genel") -> None:
    """Terminal üzerinden interaktif brief görüşmesi yürütür."""
    print(f"\n⚡ Digital Software Studio — {'DevOps & Dağıtım' if mod == 'devops' else 'Proje Kapsamı'} Brief Görüşmesi")
    print("─" * 70)
    
    s = yukle()
    if s.get("durum") == "tamam" or s.get("mod") != mod:
        yeni_gorusme(mod)

    while True:
        res = soru_uret(mod)
        if res.get("bitti"):
            print("\n✓ Brief görüşmesi tamamlandı. Alınan kararlar proje kapsamına işlendi.\n")
            break
        tur = res.get("tur")
        if not tur:
            break
        unvan_str = UNVAN.get(tur['rol'], tur['rol'])
        print(f"\n💬 [{unvan_str}] {tur['soru']}")
        if tur.get("secenekler"):
            print("   Önerilen seçenekler: " + " | ".join(tur["secenekler"]))
        
        try:
            cevap = input("\nCevabınız (Bitirmek için 'q'): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGörüşme duraklatıldı.")
            break
        
        if cevap.lower() in ("q", "quit", "bitti", "tamam"):
            bitir("tamam")
            print("\n✓ Görüşme sonlandırıldı.")
            break
        
        c_res = cevapla(cevap)
        if not c_res.get("ok"):
            print(f"Hata: {c_res.get('mesaj')}")


def main():
    parser = argparse.ArgumentParser(description="Digital Software Studio — Brief Görüşmesi")
    parser.add_argument("--soru", action="store_true", help="Sıradaki soruyu üretir")
    parser.add_argument("--cevap", type=str, help="Bekleyen soruyu cevaplar")
    parser.add_argument("--devops", action="store_true", help="DevOps & Dağıtım Brief Görüşmesi başlatır")
    parser.add_argument("--sifirla", action="store_true", help="Görüşme durumunu sıfırlar")
    parser.add_argument("--ozet", action="store_true", help="Görüşme özetini JSON döner")
    args = parser.parse_args()

    if args.sifirla:
        sifirla()
        print("Brief durumu sıfırlandı.")
        sys.exit(0)

    if args.ozet:
        print(json.dumps(ozet(), ensure_ascii=False, indent=1))
        sys.exit(0)

    if args.cevap:
        res = cevapla(args.cevap)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        sys.exit(0)

    if args.soru:
        res = soru_uret("devops" if args.devops else "genel")
        print(json.dumps(res, ensure_ascii=False, indent=1))
        sys.exit(0)

    # Parametresiz çağrı: İnteraktif terminal modu
    interaktif_terminal("devops" if args.devops else "genel")


if __name__ == "__main__":
    main()
