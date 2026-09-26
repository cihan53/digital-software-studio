#!/usr/bin/env python3
"""
scripts/musteri_talepleri.py
Digital Software Studio — Müşteri İstek & Şikayet Takip Motoru

Müşteri (proje sahibi/denetçi) bildirimleri yalnızca studio.db'de (talepler
tablosu) yaşar — tek doğruluk kaynağı budur. Eski sürümlerdeki
workspace/docs/musteri_talepleri.json bulunursa BİR KEZ studio.db'ye aktarılıp
_arsiv/ altına taşınır; artık JSON'a okuma/yazma yapılmaz.
musteri_talepleri.md yalnızca insan-okur export olarak üretilir.
"""

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# GitHub Issue Entegrasyonu
try:
    import github_issue_bridge as GH
except ImportError:
    GH = None

import studio_board as B

DOCS_DIR = ROOT / "workspace" / "docs"
LEGACY_JSON = DOCS_DIR / "musteri_talepleri.json"
MD_FILE = DOCS_DIR / "musteri_talepleri.md"
PLANS_DIR = DOCS_DIR / "cozum_planlari"

# Desteklenen Türler ve Öncelikler
TURLER = {
    "HATA": "Hata / Bug",
    "ISTEK": "Yeni İstek / Özellik",
    "UX": "Tasarım & Kullanıcı Deneyimi",
    "VERI": "Veri & İstasyon Tutarlılığı",
    "PERFORMANS": "Performans & Hız"
}

ONCELIKLER = {
    "KRITIK": "Kritik (P1)",
    "YUKSEK": "Yüksek (P2)",
    "NORMAL": "Normal (P3)",
    "DUSUK": "Düşük (P4)"
}

DURUMLAR = {
    "DEGERLENDIRMEDE": "⚖️ Değerlendirmede (Triage)",
    "FAZ_BEKLIYOR": "📦 Faz Bekliyor",
    "BEKLEMEDE": "⏳ Beklemede",
    "PLANLANDI": "📋 Planlandı",
    "GELISTIRILIYOR": "🔨 Geliştiriliyor",
    "TESTTE": "🧪 Testte",
    "COZULDU": "✅ Çözüldü",
    "IPTAL": "❌ İptal Edildi"
}


# ==============================================================================
# SQLite yardımcıları
# ==============================================================================

def db_conn() -> sqlite3.Connection:
    """studio.db bağlantısı — şema (talepler dahil) studio_board garantisinde."""
    return B.db_conn()


def _talep_to_db(cur: sqlite3.Cursor, t: dict):
    """Tek bir talep dict'ini talepler tablosuna UPSERT eder."""
    gecmis_json = json.dumps(t.get("gecmis", []), ensure_ascii=False)
    cur.execute("""
        INSERT INTO talepler
            (id, tarih, tur, oncelik, baslik, aciklama, sayfa_url,
             durum, gorevli_rol, studio_notu, github_issue_number,
             github_issue_url, cozum_plani, faz_id, efor, triage_notu, gecmis)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
            tarih               = excluded.tarih,
            tur                 = excluded.tur,
            oncelik             = excluded.oncelik,
            baslik              = excluded.baslik,
            aciklama            = excluded.aciklama,
            sayfa_url           = excluded.sayfa_url,
            durum               = excluded.durum,
            gorevli_rol         = excluded.gorevli_rol,
            studio_notu         = excluded.studio_notu,
            github_issue_number = excluded.github_issue_number,
            github_issue_url    = excluded.github_issue_url,
            cozum_plani         = excluded.cozum_plani,
            faz_id              = excluded.faz_id,
            efor                = excluded.efor,
            triage_notu         = excluded.triage_notu,
            gecmis              = excluded.gecmis
    """, (
        t.get("id"), t.get("tarih"), t.get("tur"), t.get("oncelik"),
        t.get("baslik"), t.get("aciklama"), t.get("sayfa_url"),
        t.get("durum"), t.get("gorevli_rol"), t.get("studio_notu"),
        t.get("github_issue_number"), t.get("github_issue_url"),
        t.get("cozum_plani"), t.get("faz_id"), t.get("efor"),
        t.get("triage_notu"), gecmis_json
    ))


def _db_to_talep(row: sqlite3.Row) -> dict:
    """DB satırını talep dict'ine çevirir."""
    t = dict(row)
    try:
        t["gecmis"] = json.loads(t.get("gecmis") or "[]")
    except Exception:
        t["gecmis"] = []
    return t


def db_tum_talepler() -> list[dict]:
    """studio.db'den tüm talepleri döndürür."""
    conn = db_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM talepler ORDER BY tarih")
        rows = cur.fetchall()
        return [_db_to_talep(r) for r in rows]
    finally:
        conn.close()


def _migrate_legacy_json():
    """Eski musteri_talepleri.json varsa studio.db'ye aktarıp arşivler.

    Dosya tek seferde _arsiv/ altına taşınır; artık hiçbir yerde
    okunmaz/yazılmaz — tek doğruluk kaynağı studio.db'dir.
    """
    if not LEGACY_JSON.exists():
        return
    try:
        veri = json.loads(LEGACY_JSON.read_text(encoding="utf-8"))
        talepler = veri.get("talepler", []) if isinstance(veri, dict) else []
        if talepler:
            conn = db_conn()
            try:
                cur = conn.cursor()
                for t in talepler:
                    _talep_to_db(cur, t)
                conn.commit()
            finally:
                conn.close()
            print(f"  [i] {len(talepler)} eski talep musteri_talepleri.json'dan studio.db'ye aktarıldı.")
    except Exception as e:
        print(f"  [UYARI] musteri_talepleri.json içe aktarılamadı: {e}", file=sys.stderr)
    try:
        arsiv = ROOT / "_arsiv"
        arsiv.mkdir(parents=True, exist_ok=True)
        hedef = arsiv / f"musteri_talepleri-{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        LEGACY_JSON.replace(hedef)
    except OSError:
        LEGACY_JSON.unlink(missing_ok=True)


# ==============================================================================
# Veri yükleme / kaydetme
# ==============================================================================

def load_data() -> dict:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_json()
    talepler = db_tum_talepler()
    return {
        "son_guncelleme": datetime.now().isoformat(),
        "toplam_talep": len(talepler),
        "talepler": talepler
    }


def save_data(data: dict):
    data["son_guncelleme"] = datetime.now().isoformat()
    data["toplam_talep"] = len(data.get("talepler", []))

    conn = db_conn()
    try:
        cur = conn.cursor()
        for t in data.get("talepler", []):
            _talep_to_db(cur, t)
        conn.commit()
    finally:
        conn.close()

    render_markdown(data)


def render_markdown(data: dict):
    talepler = data.get("talepler", [])
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    md = [
        "# Digital Software Studio — Müşteri Denetim & Talep Havuzu",
        "",
        f"> **Son Güncelleme:** {now_str}  ",
        f"> **Toplam Bildirim:** {len(talepler)}  ",
        "",
        "Bu doküman, proje sahibinin / müşterinin yaptığı denetimler sonucunda iletilen istek, hata ve geri bildirimleri içerir.",
        "",
        "---",
        "",
        "## 1. Genel Durum Özeti",
        "",
        "| ID | Tür | Öncelik | Durum | Başlık | Ekran / URL | İlgili Rol | GitHub Issue | Plan |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    if not talepler:
        md.append("| — | — | — | — | *Henüz kayıtlı talep bulunmamaktadır.* | — | — | — | — |")
    else:
        for t in reversed(talepler):
            tid = t.get("id")
            tur = TURLER.get(t.get("tur"), t.get("tur"))
            oncelik = ONCELIKLER.get(t.get("oncelik"), t.get("oncelik"))
            durum = DURUMLAR.get(t.get("durum"), t.get("durum"))
            baslik = t.get("baslik", "").replace("|", "-")
            sayfa = t.get("sayfa_url", "Genel").replace("|", "-")
            rol = t.get("gorevli_rol", "—")
            plan_file = t.get("cozum_plani")
            plan_link = f"[Plan Oku]({plan_file})" if plan_file and (ROOT / plan_file).exists() else "—"
            issue_col = f"[#{t.get('github_issue_number')}]({t.get('github_issue_url')})" if t.get("github_issue_url") else "—"
            md.append(f"| **{tid}** | {tur} | {oncelik} | {durum} | {baslik} | `{sayfa}` | `{rol}` | {issue_col} | {plan_link} |")

    md.extend([
        "",
        "---",
        "",
        "## 2. Talep Detayları ve Geri Bildirim Notları",
        ""
    ])

    if not talepler:
        md.append("*Kayıtlı detay bulunmuyor.*")
    else:
        for t in reversed(talepler):
            tid = t.get("id")
            durum = DURUMLAR.get(t.get("durum"), t.get("durum"))
            md.extend([
                f"### [{tid}] {t.get('baslik')} ({durum})",
                f"- **Bildirim Tarihi:** {t.get('tarih')}",
                f"- **Tür / Öncelik:** {TURLER.get(t.get('tur'), t.get('tur'))} / {ONCELIKLER.get(t.get('oncelik'), t.get('oncelik'))}",
                f"- **İlgili Ekran / Sayfa:** `{t.get('sayfa_url', 'Genel')}`",
                f"- **Görevli Rol:** `{t.get('gorevli_rol', 'Studio Yetkilisi Tarafından Atanacak')}`",
            ])
            if t.get("github_issue_url"):
                md.append(f"- 🐙 **GitHub Issue:** [#{t.get('github_issue_number')}]({t.get('github_issue_url')})")
            md.extend([
                "",
                "**Müşteri Açıklaması / Hata Adımları:**",
                f"> {t.get('aciklama', 'Açıklama belirtilmedi.')}",
                ""
            ])
            if t.get("studio_notu"):
                md.extend([
                    "**Studio Yetkilisi Notu:**",
                    f"> {t.get('studio_notu')}",
                    ""
                ])
            if t.get("cozum_plani"):
                md.append(f"- 📄 **Çözüm Planı:** [{t.get('cozum_plani')}]({t.get('cozum_plani')})\n")
            md.append("---")

    MD_FILE.write_text("\n".join(md), encoding="utf-8")


def _sonraki_talep_no() -> int:
    """DB'deki en yüksek TALEP numarası + 1 (eşzamanlı kayıtta çakışmaz)."""
    conn = db_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM talepler")
        en_buyuk = 0
        for (tid,) in cur.fetchall():
            if tid and tid.upper().startswith("TALEP-"):
                try:
                    en_buyuk = max(en_buyuk, int(tid.split("-", 1)[1]))
                except (ValueError, IndexError):
                    pass
        return en_buyuk + 1
    finally:
        conn.close()


def yeni_talep(tur: str, baslik: str, aciklama: str, oncelik: str = "NORMAL", sayfa_url: str = "/") -> dict:
    data = load_data()
    mevcut = data.get("talepler", [])

    # ID Üretimi: TALEP-001, TALEP-002...
    talep_id = f"TALEP-{_sonraki_talep_no():03d}"
    
    tur_upper = tur.upper() if tur.upper() in TURLER else "HATA"
    oncelik_upper = oncelik.upper() if oncelik.upper() in ONCELIKLER else "NORMAL"
    
    yeni = {
        "id": talep_id,
        "tarih": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "tur": tur_upper,
        "oncelik": oncelik_upper,
        "baslik": baslik.strip(),
        "aciklama": aciklama.strip(),
        "sayfa_url": sayfa_url.strip() or "/",
        "durum": "BEKLEMEDE",
        "gorevli_rol": None,
        "studio_notu": None,
        "cozum_plani": None,
        "github_issue_number": None,
        "github_issue_url": None,
        "gecmis": [
            {
                "zaman": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "eylem": "Kayıt oluşturuldu",
                "durum": "BEKLEMEDE"
            }
        ]
    }
    
    # GitHub Issue Açma Entegrasyonu
    if GH and GH.gh_mevcut_mu():
        print(f"  🐙 GitHub Issue açılıyor ({talep_id})...")
        issue_res = GH.github_issue_olustur(yeni)
        if issue_res:
            num, url = issue_res
            yeni["github_issue_number"] = num
            yeni["github_issue_url"] = url
            yeni["gecmis"].append({
                "zaman": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "eylem": f"GitHub Issue oluşturuldu: #{num}",
                "durum": "BEKLEMEDE"
            })
            print(f"  ✓ GitHub Issue hazır: #{num} ({url})")

    mevcut.append(yeni)
    data["talepler"] = mevcut
    save_data(data)
    B.audit("musteri", "talep_olustu", talep_id=talep_id,
            detay={"tur": tur_upper, "oncelik": oncelik_upper,
                   "baslik": yeni["baslik"][:120]})

    # Otomatik Triage ve Planlama (Hata vs Özellik Ayrımı)
    try:
        sys.path.insert(0, str(ROOT))
        sys.path.insert(0, str(ROOT / "scripts"))
        import karar_verici_triage as KVT
        import studio_yetkilisi as SY

        analiz = KVT.talep_analiz_et(yeni)
        yeni["faz_id"] = analiz["onerilen_faz"]
        yeni["efor"] = analiz["efor"]

        if analiz["gercek_tur"] == "HATA":
            yeni["durum"] = "BEKLEMEDE"
            print(f"  ⚡ [BUG/HOTFIX HATTI] Hata tespit edildi, çözüm planı hazırlanıyor ({talep_id})...")
            SY.cozum_plani_olustur(talep_id)
            SY.otomatik_musteri_talepleri_senkronize_et()
            B.ledger_approve(gorev=2)
            print(f"  ✓ {talep_id} (Hata) aktif sprint panosuna stabilizasyon görevi olarak eklendi!")
        else:
            yeni["durum"] = "DEGERLENDIRMEDE"
            yeni["triage_notu"] = f"Yeni Özellik (Feature) olarak sınıflandırıldı. Önerilen Faz: {analiz['onerilen_faz']} (Efor: {analiz['efor']})."
            print(f"  ⚖️  [KARAR VERİCİ TRİAGE] Yeni Özellik (Feature) algılandı: {talep_id}")
            print(f"      • Doğrudan aktif sprinte eklenmedi (kapsam genişlemesi önlendi).")
            print(f"      • Atanan Havuz: {analiz['onerilen_faz']} Backlog (Efor: {analiz['efor']}, Süre: {analiz['tahmini_sure']})")
            print(f"      • Faz 1 hataları kapandıktan sonra karar verici onayı ile devreye girecektir.")
            SY.cozum_plani_olustur(talep_id)

        # Güncel alanları kaydet
        save_data(data)
    except Exception as e:
        print(f"  [UYARI] Triage / Planlama tetiklenirken hata: {e}")

    return yeni


def getir(talep_id: str) -> dict | None:
    """Talebi studio.db'den getirir."""
    conn = db_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM talepler WHERE lower(id) = lower(?)", (talep_id,))
        row = cur.fetchone()
        if row:
            return _db_to_talep(row)
    finally:
        conn.close()
    return None


def guncelle(talep_id: str, durum: str = None, gorevli_rol: str = None,
             studio_notu: str = None, cozum_plani: str = None) -> bool:
    data = load_data()
    for t in data.get("talepler", []):
        if t["id"].lower() == talep_id.lower():
            if durum:
                t["durum"] = durum.upper()
                t.setdefault("gecmis", []).append({
                    "zaman": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "eylem": f"Durum güncellendi: {durum}",
                    "durum": durum.upper()
                })
                # Eğer talep çözüldüyse GitHub Issue'yu otomatik kapat
                if durum.upper() == "COZULDU":
                    if t.get("github_issue_number") and GH:
                        kapanis_aciklama = studio_notu or f"Talep {datetime.now().strftime('%Y-%m-%d %H:%M')} itibarıyla stüdyo ekibi tarafından başarıyla çözüldü."
                        GH.github_issue_kapat(t["github_issue_number"], kapanis_notu=kapanis_aciklama)
                        print(f"  ✓ GitHub Issue #{t['github_issue_number']} başarıyla kapatıldı.")

                    # Opsiyonel Otomatik Commit & Push (Varsayılan: Aktif)
                    auto_deploy = os.getenv("STUDIO_AUTO_DEPLOY", "1").strip().lower() in ("1", "true", "yes", "on")
                    if auto_deploy:
                        try:
                            print(f"  🚀 [OTOMATİK YAYINLAMA] {talep_id} çözüldü, commit ve push başlatılıyor...")
                            issue_ref = f" (closes #{t['github_issue_number']})" if t.get('github_issue_number') else ""
                            commit_msg = f"fix({talep_id.lower()}): {t.get('baslik', 'Hata giderildi')}{issue_ref}"
                            
                            subprocess.run(["git", "add", "-A"], cwd=ROOT, check=True)
                            status_res = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
                            if status_res.stdout.strip():
                                subprocess.run(["git", "commit", "-m", commit_msg], cwd=ROOT, check=True)
                                print(f"  ✓ Değişiklikler commit edildi: '{commit_msg}'")
                                push_res = subprocess.run(["git", "push", "origin", "master"], cwd=ROOT, capture_output=True, text=True)
                                if push_res.returncode == 0:
                                    print("  ✓ origin/master dalına başarıyla pushlandı. GitHub Actions CI/CD otomatik dağıtımı başlattı!")
                                else:
                                    print(f"  ⚠️ Push uyarısı: {push_res.stderr.strip()[:200]}")
                            else:
                                print("  ℹ️ Commit edilecek dosya değişikliği bulunamadı.")
                        except Exception as e:
                            print(f"  ⚠️ Otomatik commit/push sırasında hata: {e}")

            if gorevli_rol:
                t["gorevli_rol"] = gorevli_rol
            if studio_notu:
                t["studio_notu"] = studio_notu
            if cozum_plani:
                t["cozum_plani"] = cozum_plani
            save_data(data)
            B.audit("musteri", "talep_guncelle", talep_id=t["id"],
                    detay={"durum": t.get("durum"),
                           "gorevli_rol": t.get("gorevli_rol")})
            return True
    return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Müşteri Talepleri CLI")
    parser.add_argument("--yeni", action="store_true", help="Yeni talep ekle")
    parser.add_argument("--tur", default="HATA", choices=list(TURLER.keys()))
    parser.add_argument("--oncelik", default="NORMAL", choices=list(ONCELIKLER.keys()))
    parser.add_argument("--baslik", default="")
    parser.add_argument("--aciklama", default="")
    parser.add_argument("--sayfa", default="/")
    parser.add_argument("--liste", action="store_true", help="Tüm talepleri listele")
    parser.add_argument("--goster", type=str, help="Belirli talep ID'sini göster")
    parser.add_argument("--guncelle", type=str, help="Talep ID")
    parser.add_argument("--durum", type=str, help="Yeni durum (BEKLEMEDE, PLANLANDI, GELISTIRILIYOR, TESTTE, COZULDU)")

    args = parser.parse_args()

    if args.yeni:
        if not args.baslik:
            sys.exit("Hata: --baslik zorunludur.")
        t = yeni_talep(args.tur, args.baslik, args.aciklama, args.oncelik, args.sayfa)
        print(f"✓ [{t['id']}] Başarıyla kaydedildi: {t['baslik']}")
        return

    if args.liste:
        data = load_data()
        talepler = data.get("talepler", [])
        if not talepler:
            print("\n[i] Henüz kayıtlı müşteri talebi veya hata bildirimi yok.\n")
            return
        print(f"\n── Müşteri Bildirim Havuzu ({len(talepler)} Talep) ──────────────────────")
        for t in talepler:
            durum_goster = DURUMLAR.get(t.get("durum"), t.get("durum"))
            onc = t.get("oncelik", "NORMAL")
            print(f" • [{t['id']}] {durum_goster} [{onc}] {t['baslik']}")
            print(f"   Sayfa: {t.get('sayfa_url')} | Rol: {t.get('gorevli_rol') or 'Atanmadı'}")
            if t.get("github_issue_url"):
                print(f"   Issue: #{t.get('github_issue_number')} ({t.get('github_issue_url')})")
            if t.get("cozum_plani"):
                print(f"   Plan : {t.get('cozum_plani')}")
        print()
        return

    if args.goster:
        t = getir(args.goster)
        if not t:
            sys.exit(f"Hata: {args.goster} bulunamadı.")
        print(json.dumps(t, indent=2, ensure_ascii=False))
        return

    if args.guncelle and args.durum:
        if guncelle(args.guncelle, durum=args.durum):
            print(f"✓ {args.guncelle} durumu güncellendi: {args.durum}")
        else:
            sys.exit(f"Hata: {args.guncelle} bulunamadı.")


if __name__ == "__main__":
    main()
