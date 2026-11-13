#!/usr/bin/env python3
"""Mod 2 — Müşteri İstekleri, Teknik/UX Öneri Paketi, Ortak Karar & Eklemeli Planlama (issue #321).

Akış:
  1. İstek alma        → müşteri yeni istek/şikayet/öncelik ekler.
  2. Öneri üretimi     → analiz bulguları + müşteri istekleri birleştirilir; teknik/UX önerisi,
                         alternatif ve risk bilgisiyle madde listesi oluşturulur.
  3. Ortak karar       → her madde için ONAYLANDI / REDDEDILDI / REVIZE kararı verilir.
                         Onaylanmadan planlamaya geçilmez.
  4. Eklemeli planlama → mevcut `workspace/studio.db` geçmişini bozmadan `append_sprint` ve
                         gerekiyorsa `musteri_talepleri.yeni_talep` ile panoya eklenir.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

KARARLAR = ("BEKLIYOR", "ONAYLANDI", "REDDEDILDI", "REVIZE")


def _simdi() -> str:
    return datetime.now().isoformat(timespec="seconds")


def durum_yolu(kok: Path = ROOT) -> Path:
    return kok / "workspace" / "docs" / "mod2_mutabakat.json"


def analiz_yolu(kok: Path = ROOT) -> Path:
    return kok / "workspace" / "docs" / "mevcut_proje_durumu.json"


def yukle(kok: Path = ROOT) -> dict:
    p = durum_yolu(kok)
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {
        "durum": "ACIK",        # ACIK | ONERI_HAZIR | MUTABAKAT_TAMAM | PLANLANDI
        "istekler": [],
        "maddeler": [],
        "planlanan_sprintler": [],
        "planlanan_talepler": [],
        "guncelleme": _simdi(),
    }


def kaydet(veri: dict, kok: Path = ROOT) -> None:
    veri["guncelleme"] = _simdi()
    p = durum_yolu(kok)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(veri, ensure_ascii=False, indent=2), encoding="utf-8")


def istek_ekle(metin: str, tur: str = "ISTEK", oncelik: str = "NORMAL", kok: Path = ROOT) -> dict:
    metin = (metin or "").strip()
    if not metin:
        return {"ok": False, "mesaj": "İstek metni boş olamaz."}
    s = yukle(kok)
    istek = {
        "id": f"I{len(s['istekler']) + 1}",
        "tur": (tur or "ISTEK").upper(),
        "oncelik": (oncelik or "NORMAL").upper(),
        "metin": metin[:1000],
        "zaman": _simdi(),
    }
    s["istekler"].append(istek)
    kaydet(s, kok)
    return {"ok": True, "istek": istek}


def _llm_oneri(baslik: str, detay: str, tip: str) -> dict | None:
    if os.getenv("STUDIO_SOHBET_AGENT", "1") == "0":
        return None
    try:
        import studio_engine as E
        org = json.loads(E.resolve_doc("org_chart.json").read_text(encoding="utf-8"))
        agent = next((a for a in org.get("hierarchy", []) if a["id"] in ("cto", "product_owner")), None)
        if not agent:
            return None
        backend, model, effort, _ = E.resolve_engine(agent, {})
        meta = {"seq": E._trace_seq(), "role": agent["id"], "title": agent.get("title", "CTO"),
                "target": "mod2_oneri", "backend": backend, "model": model, "tools": []}
        sistem = (
            "Var olan bir yazılım projesini devralan stüdyonun CTO/PO'susun. "
            'Yanıtın yalnızca JSON: {"oneri": "...", "alternatif": "...", "risk": "...", "rol": "backend_engineer|web_engineer|qa_lead|devops_engineer"}.'
        )
        ham = E.query_claude(sistem, f"Tip: {tip}\nBaşlık: {baslik}\nDetay: {detay}", backend, model, effort, meta, tools=None)
        t = (ham or "").strip().strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
        i, j = t.find("{"), t.rfind("}")
        if i != -1 and j > i:
            return json.loads(t[i:j + 1])
    except Exception:
        pass
    return None


def _varsayilan_oneri(tip: str, baslik: str, detay: str) -> dict:
    tip_l = (tip or "").lower()
    if tip_l in ("bug", "hata"):
        return {
            "oneri": f"Kök nedeni doğrulayıp test ekleyerek düzelt: {baslik}",
            "alternatif": "Geçici olarak özellik bayrağı / fallback ile etkiyi sınırla",
            "risk": "Mevcut çalışan akışlarda regresyon riski; regresyon testi zorunlu",
            "rol": "backend_engineer",
        }
    if tip_l in ("tutarsizlik", "iyilestirme"):
        return {
            "oneri": f"Mevcut koda dokunmadan kademeli iyileştirme uygula: {baslik}",
            "alternatif": "Yalnızca dokümantasyon/izleme ekleyip sonraki faza ertele",
            "risk": "Kapsam kayması riski; küçük adımlarla ilerlenmeli",
            "rol": "web_engineer",
        }
    return {
        "oneri": f"Mevcut mimariyle uyumlu artımlı geliştirme paketi olarak ekle: {baslik}",
        "alternatif": "MVP kapsamını daraltıp sonraki sprinte böl",
        "risk": "Mevcut manuel değişikliklerle çakışma ihtimali; ön test gerekli",
        "rol": "web_engineer",
    }


def oneri_paketi_olustur(kok: Path = ROOT, yeniden: bool = False) -> dict:
    """Analiz bulguları ile müşteri isteklerini öneri maddelerine dönüştürür."""
    s = yukle(kok)
    if s["maddeler"] and not yeniden:
        return {"ok": True, "maddeler": s["maddeler"], "durum": s["durum"]}

    analiz = {}
    ap = analiz_yolu(kok)
    if ap.is_file():
        try:
            analiz = json.loads(ap.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            analiz = {}

    maddeler: list[dict] = []
    sayac = 1

    def ekle_madde(kaynak: str, tip: str, siddet: str, baslik: str, detay: str):
        nonlocal sayac
        zengin = _llm_oneri(baslik, detay, tip) or _varsayilan_oneri(tip, baslik, detay)
        maddeler.append({
            "id": f"M{sayac}",
            "kaynak": kaynak,
            "tip": tip,
            "siddet": siddet,
            "baslik": baslik,
            "detay": detay,
            "oneri": zengin.get("oneri", ""),
            "alternatif": zengin.get("alternatif", ""),
            "risk": zengin.get("risk", ""),
            "rol": zengin.get("rol", "web_engineer"),
            "karar": "BEKLIYOR",
            "karar_notu": "",
        })
        sayac += 1

    for i in s["istekler"]:
        ekle_madde(f"musteri:{i['id']}", i["tur"].lower(), i["oncelik"].lower(), i["metin"][:80], i["metin"])

    for b in analiz.get("bulgular", []):
        ekle_madde(f"analiz:{b['id']}", b.get("tip", "iyilestirme"), b.get("siddet", "orta"),
                   b.get("baslik", ""), b.get("detay", ""))

    s["maddeler"] = maddeler
    s["durum"] = "ONERI_HAZIR" if maddeler else "ACIK"
    kaydet(s, kok)
    return {"ok": True, "maddeler": maddeler, "durum": s["durum"]}


def karar_ver(madde_id: str, karar: str, not_: str = "", kok: Path = ROOT) -> dict:
    karar_u = (karar or "").strip().upper()
    if karar_u not in ("ONAYLANDI", "REDDEDILDI", "REVIZE"):
        return {"ok": False, "mesaj": f"Geçersiz karar: {karar}. ONAYLANDI/REDDEDILDI/REVIZE beklenir."}
    s = yukle(kok)
    hedef = next((m for m in s["maddeler"] if m["id"] == madde_id), None)
    if hedef is None:
        return {"ok": False, "mesaj": f"Madde bulunamadı: {madde_id}"}
    hedef["karar"] = karar_u
    hedef["karar_notu"] = (not_ or "").strip()[:400]
    hedef["karar_zaman"] = _simdi()
    if s.get("durum") != "PLANLANDI":
        if mutabakat_hazir_mi(s):
            s["durum"] = "MUTABAKAT_TAMAM"
        else:
            s["durum"] = "ONERI_HAZIR"
    kaydet(s, kok)
    return {"ok": True, "madde": hedef, "mutabakat_hazir": mutabakat_hazir_mi(s)}


def mutabakat_hazir_mi(s: dict) -> bool:
    maddeler = s.get("maddeler") or []
    if not maddeler:
        return False
    onayli = [m for m in maddeler if m.get("karar") == "ONAYLANDI"]
    bekleyen = [m for m in maddeler if m.get("karar") in ("BEKLIYOR", "REVIZE")]
    return len(onayli) > 0 and len(bekleyen) == 0


def planlamaya_aktar(kok: Path = ROOT) -> dict:
    """Onaylanan maddeleri mevcut `studio.db` geçmişini bozmadan sprint ve taleplere dönüştürür."""
    s = yukle(kok)
    if s.get("durum") == "PLANLANDI":
        return {"ok": False, "mesaj": "Bu mutabakat zaten panoya planlandı. Tekrar planlanamaz.",
                "sprintler": s.get("planlanan_sprintler", []),
                "talepler": s.get("planlanan_talepler", [])}
    if not mutabakat_hazir_mi(s):
        return {"ok": False, "mesaj": "Ortak karar tamamlanmadı: bekleyen/revize maddeler var veya onaylı madde yok."}

    onaylilar = [m for m in s["maddeler"] if m.get("karar") == "ONAYLANDI"]
    import studio_board as B

    if B.board_exists():
        board = B.load()
    else:
        board = {"project": kok.name, "sprints": [], "baseline_end": None}

    gorevler = []
    talep_idler = []

    for idx, m in enumerate(onaylilar, 1):
        tip_l = (m.get("tip") or "").lower()
        gorev_not = f"[{m['id']}] {m.get('oneri', '')}"
        if m.get("karar_notu"):
            gorev_not += f" | Müşteri notu: {m['karar_notu']}"

        if tip_l in ("bug", "hata"):
            try:
                import musteri_talepleri as MT
                t = MT.yeni_talep("HATA", m["baslik"][:100], f"{m.get('detay', '')}\n\n{gorev_not}",
                                  oncelik="YUKSEK" if m.get("siddet") == "yuksek" else "NORMAL")
                if isinstance(t, dict) and t.get("id"):
                    talep_idler.append(t["id"])
            except Exception:
                pass

        gorevler.append({
            "title": m["baslik"][:120],
            "description": f"{m.get('detay', '')}\nÖneri: {m.get('oneri', '')}\nRisk: {m.get('risk', '')}".strip()[:600],
            "role": m.get("rol") or "web_engineer",
            "phase": "develop",
            "outputs": ["workspace/docs/mevcut_proje_analizi.md"],
            "depends_on": [],
            "note": gorev_not[:300],
        })

    # Sonuna doğrulama / test görevi ekle
    gorevler.append({
        "title": "Mod 2 iyileştirme paketi regresyon ve UAT doğrulaması",
        "description": "Eklenen düzeltme ve iyileştirmelerin mevcut çalışan işlevleri bozmadığını doğrula.",
        "role": "qa_lead",
        "phase": "test",
        "outputs": ["workspace/docs/uat_kabul_raporu.md"],
        "depends_on": [],
    })

    yeni_sprint = {
        "name": "Mod 2 — Mutabakat İyileştirme Sprinti",
        "goal": "Onaylanan mevcut proje düzeltmeleri ve yeni müşteri isteklerinin güvenli entegrasyonu.",
        "tasks": gorevler,
    }
    B.append_sprint(board, yeni_sprint)
    B.save(board)
    B.audit("mod2", "mutabakat_planlandi", detay={
        "sprint_id": yeni_sprint["id"],
        "madde_sayisi": len(onaylilar),
        "talepler": talep_idler,
    })

    s["durum"] = "PLANLANDI"
    s["planlanan_sprintler"].append(yeni_sprint["id"])
    s["planlanan_talepler"].extend(talep_idler)
    kaydet(s, kok)
    return {"ok": True, "sprint_id": yeni_sprint["id"], "gorev_sayisi": len(gorevler), "talepler": talep_idler}


def terminal_wizard(kok: Path = ROOT) -> int:
    """Mod 2 için terminalde interaktif analiz, öneri sunumu ve müşteri ortak karar sihirbazı."""
    import mevcut_proje_analizi as MPA
    print("\n" + "═" * 60)
    print("  🔍  MOD 2 — MEVCUT PROJE ANALİZİ & ORTAK KARAR SİHİRBAZI")
    print("═" * 60)
    print("  [1/3] Mevcut kod tabanı ve proje sağlığı analiz ediliyor...")
    durum = MPA.analiz_calistir(kok)
    print(f"  ✓ Analiz tamamlandı: {len(durum.get('bulgular', []))} bulgu tespit edildi.")

    print("\n  [2/3] CTO ve Product Owner öneri paketi hazırlanıyor...")
    oneri_paketi_olustur(kok)
    s = yukle(kok)
    maddeler = s.get("maddeler") or []

    print("\n" + "─" * 60)
    print(f"  💡  TESPİT EDİLEN BULGULAR VE STÜDYO ÖNERİLERİ ({len(maddeler)} madde)")
    print("─" * 60)
    for m in maddeler:
        karar_renk = "✓ ONAYLANDI" if m.get("karar") == "ONAYLANDI" else ("✗ REDDEDİLDİ" if m.get("karar") == "REDDEDILDI" else "⏳ BEKLİYOR")
        print(f"\n  [{m['id']}] {m['baslik']} ({m.get('siddet', '').upper()}) — [{karar_renk}]")
        print(f"       💡 Öneri  : {m.get('oneri', '')}")
        print(f"       ⚠️ Risk   : {m.get('risk', '')}")
        print(f"       👤 Rol    : {m.get('rol', 'web_engineer')}")
    print("─" * 60)

    if mutabakat_hazir_mi(s):
        print("\n  ✓ Tüm maddeler karara bağlanmış durumda.")
        if s.get("durum") != "PLANLANDI":
            res = planlamaya_aktar(kok)
            print(f"  🚀 Sprint planlandı: {res.get('sprint_id')} ({res.get('gorev_sayisi')} görev)")
        return 0

    while True:
        print("\nNe yapmak istersiniz?")
        print("  [1] Tüm önerileri ONAYLA ve geliştirme sprintini planla")
        print("  [2] Yeni bir müşteri isteği ekle")
        print("  [3] Maddeleri tek tek incele / karar ver")
        print("  [4] Çıkış (kararı ertele)")
        try:
            secim = input("\nSeçiminiz (1-4): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nÇıkıldı.")
            return 2

        if secim == "1":
            for m in maddeler:
                karar_ver(m["id"], "ONAYLANDI", kok=kok)
            res = planlamaya_aktar(kok)
            if res.get("ok"):
                print(f"\n  🚀 Harika! Ortak karar sağlandı ve sprint planlandı: {res.get('sprint_id')}")
                return 0
            else:
                print(f"  ✗ Planlama hatası: {res.get('mesaj')}")
                return 1
        elif secim == "2":
            try:
                istek = input("\nMüşteri isteğinizi yazın: ").strip()
            except (EOFError, KeyboardInterrupt):
                continue
            if istek:
                istek_ekle(istek, kok=kok)
                print("  ✓ İstek kaydedildi, öneri paketi güncelleniyor...")
                oneri_paketi_olustur(kok, yeniden=True)
                s = yukle(kok)
                maddeler = s.get("maddeler") or []
        elif secim == "3":
            for m in maddeler:
                print(f"\n[{m['id']}] {m['baslik']}")
                print(f"Öneri: {m.get('oneri', '')}")
                try:
                    k = input("Kararınız ([O]nay / [R]ed / [A]tla): ").strip().upper()
                except (EOFError, KeyboardInterrupt):
                    break
                if k in ("O", "ONAY", "1"):
                    karar_ver(m["id"], "ONAYLANDI", kok=kok)
                elif k in ("R", "RED", "2"):
                    karar_ver(m["id"], "REDDEDILDI", kok=kok)
            s = yukle(kok)
            if mutabakat_hazir_mi(s):
                res = planlamaya_aktar(kok)
                print(f"\n  🚀 Ortak karar sağlandı! Sprint planlandı: {res.get('sprint_id')}")
                return 0
        elif secim == "4":
            print("\nÇıkıldı. İstediğiniz zaman `./basla.sh --mod 2` veya Web (/musteri) üzerinden devam edebilirsiniz.")
            return 2


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Mod 2 Mutabakat Yönetimi")
    ap.add_argument("--wizard", action="store_true", help="İnteraktif terminal sihirbazını başlat")
    ap.add_argument("--onayla-hepsi", action="store_true", help="Tüm maddeleri onayla ve planla")
    args = ap.parse_args()

    if args.onayla_hepsi:
        oneri_paketi_olustur(ROOT)
        s = yukle(ROOT)
        for m in s.get("maddeler", []):
            karar_ver(m["id"], "ONAYLANDI", kok=ROOT)
        r = planlamaya_aktar(ROOT)
        print(f"Planlama sonucu: {r}")
        sys.exit(0 if r.get("ok") else 1)
    elif args.wizard or sys.stdin.isatty():
        sys.exit(terminal_wizard(ROOT))
    else:
        ap.print_help()
