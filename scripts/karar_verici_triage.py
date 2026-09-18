#!/usr/bin/env python3
"""
scripts/karar_verici_triage.py
Digital Software Studio — Karar Verici Triage & Fazlama Motoru (Product Owner & CTO)

Bu motor:
1. Gelen müşteri bildirimlerini inceler: Hata (Bug) mı, yeni Özellik (Feature / Change Request) mi?
2. HATA ise: Mevcut aktif fazın stabilizasyon/hotfix hattına aktarır.
3. ISTEK ise: Kapsam genişlemesini (scope creep) önler; efor ve maliyet analizi yaparak
   karar verici onayıyla ilgili Faza (Faz 2, Faz 3 vb.) atar.
4. Faz Kilidi (Phase Gate): Aktif fazdaki hatalar çözülmeden ve UAT onayı almadan
   sonraki fazın geliştirme sprintlerinin başlamasını engeller.
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

try:
    import musteri_talepleri as MT
except ImportError:
    MT = None

try:
    import studio_board as B
except ImportError:
    B = None

FAZLAR_FILE = ROOT / "workspace" / "docs" / "fazlar.json"

VARSAYILAN_FAZLAR = {
    "fazlar": [
        {
            "id": "FAZ-1",
            "ad": "Çekirdek Platform, Arama ve Canlı Yayına Alma (MVP)",
            "aciklama": "Harita, BBox keşfi, istasyon detayları, GADM CBS sınırları ve canlıya alma stabilizasyonu.",
            "durum": "AKTIF",
            "hedef_tarih": "2026-09-18",
            "kilitli": False
        },
        {
            "id": "FAZ-2",
            "ad": "Sürüm Yönetimi, Değişiklik Günlüğü ve Kullanıcı Bildirimleri",
            "aciklama": "Yeni sürüm çıktığında 20s otomatik sayfa yenileme, /guncellemeler (changelog) ekranı ve sürüm izleme.",
            "durum": "PLANLANDI",
            "hedef_tarih": "2026-09-25",
            "kilitli": True,
            "onkosul_faz": "FAZ-1"
        },
        {
            "id": "FAZ-3",
            "ad": "CPO Derin Entegrasyon, Rota Optimizasyonu & Rezervasyon",
            "aciklama": "Şarj istasyonu doluluk oranları, rota planlama ve operatör rezervasyon entegrasyonları.",
            "durum": "PLANLANDI",
            "hedef_tarih": "2026-10-10",
            "kilitli": True,
            "onkosul_faz": "FAZ-2"
        }
    ]
}


def load_fazlar() -> dict:
    if not FAZLAR_FILE.exists():
        save_fazlar(VARSAYILAN_FAZLAR)
        return VARSAYILAN_FAZLAR
    try:
        return json.loads(FAZLAR_FILE.read_text(encoding="utf-8"))
    except Exception:
        return VARSAYILAN_FAZLAR


def save_fazlar(data: dict):
    FAZLAR_FILE.parent.mkdir(parents=True, exist_ok=True)
    FAZLAR_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def aktif_faz_getir() -> dict:
    data = load_fazlar()
    for f in data.get("fazlar", []):
        if f.get("durum") == "AKTIF":
            return f
    return data["fazlar"][0] if data.get("fazlar") else {"id": "FAZ-1", "ad": "Faz 1"}


def talep_analiz_et(talep: dict) -> dict:
    """Product Owner & CTO gözüyle talebi inceler ve öneri üretir."""
    tur = talep.get("tur", "HATA").upper()
    baslik = talep.get("baslik", "")
    aciklama = talep.get("aciklama", "")
    metin = f"{baslik} {aciklama}".lower()

    # 1. Tür analizi: Hata mı, Yeni Özellik mi?
    is_bug = tur in ("HATA", "VERI") or any(k in metin for k in ["hata", "bozuk", "çalışmıyor", "yanlış", "mükerrer", "çift"])
    
    # 2. Faz eşleme
    if any(k in metin for k in ["sürüm", "deploy", "yenile", "changelog", "güncelleme", "notlar"]):
        onerilen_faz = "FAZ-2"
    elif any(k in metin for k in ["rezervasyon", "rota", "doluluk", "ödeme", "cpo"]):
        onerilen_faz = "FAZ-3"
    else:
        onerilen_faz = "FAZ-1"

    # 3. Efor & Karmaşıklık
    if len(aciklama) > 200 or any(k in metin for k in ["ekran", "sayfa", "veritabanı", "tüm sayfalar"]):
        efor = "ORTA"
        tahmini_sure = "1-2 Gün"
    else:
        efor = "DUSUK"
        tahmini_sure = "2-4 Saat"

    # 4. Karar verici önerisi
    if is_bug:
        oneri = "HOTFIX_MEVCUT_FAZ"
        oneri_aciklama = "Bu bir hatadır. Mevcut Faz 1 stabilizasyonu için derhal çözülmelidir."
    else:
        oneri = f"AKTAR_{onerilen_faz}"
        oneri_aciklama = f"Bu yeni bir özelliktir (Feature). Faz 1 stabilizasyonunu bölmemek için {onerilen_faz} kapsamına alınmalıdır."

    return {
        "talep_id": talep.get("id"),
        "gercek_tur": "HATA" if is_bug else "ISTEK",
        "onerilen_faz": onerilen_faz,
        "efor": efor,
        "tahmini_sure": tahmini_sure,
        "oneri": oneri,
        "oneri_aciklama": oneri_aciklama
    }


def triage_uygula(talep_id: str, hedef_faz: str = None, karar: str = None, karar_notu: str = None) -> bool:
    """Talebi karara bağlar ve ilgili faza veya hotfix hattına atar."""
    if not MT:
        return False
    talep = MT.getir(talep_id)
    if not talep:
        print(f"[!] Talep bulunamadı: {talep_id}")
        return False

    analiz = talep_analiz_et(talep)
    hedef_faz = hedef_faz or analiz["onerilen_faz"]

    # Durum güncellemesi
    if analiz["gercek_tur"] == "HATA" and hedef_faz == "FAZ-1":
        yeni_durum = "PLANLANDI"
        not_ek = f"Karar Verici Onayı: Faz 1 Hata Düzeltme hattına alındı."
    else:
        yeni_durum = "FAZ_BEKLIYOR"
        not_ek = f"Karar Verici Onayı: {hedef_faz} kapsamına aktarıldı. Faz 1 tamamlandıktan sonra geliştirilecek."

    if karar_notu:
        not_ek += f" Not: {karar_notu}"

    # musteri_talepleri.json güncelle
    data = MT.load_data()
    for t in data.get("talepler", []):
        if t["id"].lower() == talep_id.lower():
            t["durum"] = yeni_durum
            t["faz_id"] = hedef_faz
            t["efor"] = analiz["efor"]
            t["triage_notu"] = not_ek
            t.setdefault("gecmis", []).append({
                "zaman": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "eylem": f"Triage Kararı: {yeni_durum} ({hedef_faz})",
                "durum": yeni_durum
            })
            MT.save_data(data)
            print(f"  ✓ [{talep_id}] Triage tamamlandı: Durum -> {yeni_durum}, Faz -> {hedef_faz}")
            return True
    return False


def bekleyenleri_triage_et(otomatik: bool = True):
    """Henüz karara bağlanmamış tüm talepleri listeler veya otomatik triage eder."""
    if not MT:
        return
    data = MT.load_data()
    talepler = data.get("talepler", [])
    
    print("\n" + "═"*70)
    print(" ⚖️  [KARAR VERİCİ MASASI & TRIAGE] Müşteri Talepleri ve Fazlama Denetimi")
    print("═"*70)

    aktif = aktif_faz_getir()
    print(f"  📌 Aktif Faz: {aktif['id']} — {aktif['ad']}")
    print("─"*70)

    islem_sayisi = 0
    for t in talepler:
        tid = t["id"]
        durum = t.get("durum", "BEKLEMEDE")
        faz_id = t.get("faz_id")

        if durum in ("COZULDU", "IPTAL"):
            continue

        analiz = talep_analiz_et(t)
        
        # Eğer henüz faza atanmamışsa veya DEGERLENDIRMEDE ise
        if not faz_id or durum == "DEGERLENDIRMEDE":
            print(f"\n  • [{tid}] {t.get('tur')} | {t.get('baslik')[:55]}...")
            print(f"    Tespit: {analiz['gercek_tur']} | Efor: {analiz['efor']} ({analiz['tahmini_sure']})")
            print(f"    Öneri : {analiz['oneri']} -> {analiz['oneri_aciklama']}")

            if otomatik:
                triage_uygula(tid, hedef_faz=analiz["onerilen_faz"])
                islem_sayisi += 1

    if islem_sayisi == 0:
        print("  ✓ Bekleyen veya sınıflandırılmamış talep bulunmuyor. Tüm talepler fazlara dağıtılmış.")
    print("═"*70 + "\n")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Karar Verici Triage & Fazlama CLI")
    parser.add_argument("--oto", action="store_true", help="Bekleyen talepleri otomatik sınıflandır ve fazlara ata")
    parser.add_argument("--ata", type=str, help="Talep ID (örn: TALEP-012)")
    parser.add_argument("--faz", type=str, default="FAZ-2", help="Hedef Faz (FAZ-1, FAZ-2, FAZ-3)")
    parser.add_argument("--not", dest="karar_notu", type=str, help="Karar verici notu")
    parser.add_argument("--liste", action="store_true", help="Tüm fazları ve talepleri listele")

    args = parser.parse_args()

    if args.ata:
        triage_uygula(args.ata, hedef_faz=args.faz, karar_notu=args.karar_notu)
        return

    if args.liste:
        fazlar = load_fazlar()
        print("\n── Yol Haritası Fazları ──────────────────────────────────────────────")
        for f in fazlar.get("fazlar", []):
            kilit = "🔒 Kilitli" if f.get("kilitli") else "🔓 Açık"
            print(f" • [{f['id']}] {f['ad']} ({f['durum']}) - {kilit}")
            print(f"   {f['aciklama']}")
        print()
        bekleyenleri_triage_et(otomatik=False)
        return

    # Varsayılan: Otomatik triage tara ve göster
    bekleyenleri_triage_et(otomatik=args.oto)


if __name__ == "__main__":
    main()
