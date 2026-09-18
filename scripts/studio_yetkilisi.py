#!/usr/bin/env python3
"""
scripts/studio_yetkilisi.py
Digital Software Studio — Studio Yetkilisi & Çözüm Koordinasyon Motoru

Müşterinin (proje sahibi) ilettiği istek ve hataları inceler, teknik ve mimari
kök neden analizini yapar, sorumlu ekibi (Web, Backend, QA vb.) görevlendirir
ve adım adım çözüm planı oluşturur.
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLANS_DIR = ROOT / "workspace" / "docs" / "cozum_planlari"

# İlgili kütüphaneyi içeri aktar
sys.path.insert(0, str(ROOT / "scripts"))
import musteri_talepleri as MT
try:
    import github_issue_bridge as GH
except ImportError:
    GH = None


def tespit_et_rol_ve_bilesen(talep: dict) -> tuple[str, list[str], str]:
    """Talep metnine göre en uygun geliştirici rolünü, dosyaları ve bileşen türünü saptar."""
    metin = f"{talep.get('baslik', '')} {talep.get('aciklama', '')} {talep.get('sayfa_url', '')}".lower()
    
    # 1. Backend / API / Veritabanı
    if any(k in metin for k in ["api", "backend", "fastify", "postgis", "veritabanı", "endpoint", "sql", "seed", "tohumlama", "swagger", "404 not found (route"]):
        rol = "backend_engineer"
        bilesen = "Backend API & Servis Katmanı"
        dosyalar = [
            "workspace/src/backend/src/modules/",
            "workspace/src/backend/src/app.ts"
        ]
    # 2. DevOps / Dağıtım / Sunucu
    elif any(k in metin for k in ["docker", "deploy", "sunucu", "nginx", "node sürümü", "ci/cd", "infra", "hosting"]):
        rol = "devops_engineer"
        bilesen = "Altyapı & Dağıtım (Infra)"
        dosyalar = [
            "workspace/infra/",
            "Dockerfile",
            "docker-compose.yml"
        ]
    # 3. Tasarım / Stil / Renk / Tipografi
    elif any(k in metin for k in ["renk", "font", "tipografi", "padding", "margin", "logo", "ikon", "tema", "tasarım"]):
        rol = "ui_designer"
        bilesen = "Arayüz Tasarım Sistemi & Tailwind"
        dosyalar = [
            "workspace/src/frontend/assets/",
            "workspace/src/frontend/tailwind.config.js"
        ]
    # 4. Web Frontend (Varsayılan web hataları / harita / butonlar)
    else:
        rol = "web_engineer"
        bilesen = "Nuxt 3 Web Frontend & Harita Arayüzü"
        dosyalar = [
            "workspace/src/frontend/components/",
            "workspace/src/frontend/pages/"
        ]

    # Sayfaya göre dosya özelleştirme
    sayfa = talep.get("sayfa_url", "")
    if sayfa == "/" or "harita" in metin:
        dosyalar.append("workspace/src/frontend/components/StationMap.vue")
        dosyalar.append("workspace/src/frontend/pages/index.vue")
    elif "/r/" in sayfa or "rota" in metin or "köprü" in metin:
        dosyalar.append("workspace/src/frontend/pages/r/[payload].vue")
        dosyalar.append("workspace/src/backend/src/modules/route-bridge/route-bridge.routes.ts")
    elif "istasyon" in sayfa or "detay" in metin:
        dosyalar.append("workspace/src/frontend/components/StationDetailModal.vue")

    return rol, list(dict.fromkeys(dosyalar)), bilesen


def cozum_plani_olustur(talep_id: str) -> str:
    """Belirtilen talep için Studio Yetkilisi detaylı çözüm planını hazırlar."""
    talep = MT.getir(talep_id)
    if not talep:
        raise ValueError(f"Talep bulunamadı: {talep_id}")

    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    plan_rel_path = f"workspace/docs/cozum_planlari/{talep_id}.md"
    plan_abs_path = ROOT / plan_rel_path

    rol, dosyalar, bilesen = tespit_et_rol_ve_bilesen(talep)
    
    rol_unvanlari = {
        "web_engineer": "Kıdemli Web Frontend Mühendisi (Nuxt 3 & Vue)",
        "backend_engineer": "Backend & API Mühendisi (Fastify & PostGIS)",
        "ui_designer": "Arayüz ve Tasarım Uzmanı (UI/UX)",
        "devops_engineer": "DevOps & Dağıtım Mühendisi",
        "uat_auditor": "UAT & Canlı Kabul Testçisi"
    }
    unvan = rol_unvanlari.get(rol, rol)

    plan_md = f"""# Studio Yetkilisi Çözüm Planı: {talep_id}

> **Talep:** [{talep_id}] {talep.get('baslik')}  
> **Müşteri / Bildiren:** Proje Sahibi  
> **Bildirim Tarihi:** {talep.get('tarih')}  
> **Öncelik:** {talep.get('oncelik')} | **Tür:** {talep.get('tur')}  
> **Koordinatör:** Studio Yetkilisi & Teknik Liderlik  
> **Görevlendirilen Rol:** `{rol}` ({unvan})  

---

## 1. Müşteri Talebi ve Problem Tanımı
Müşteri (proje sahibi) denetimi sırasında aşağıdaki durumu tespit etti:
> **Açıklama:**  
> {talep.get('aciklama')}

- **Etkilenen Ekran / URL:** `{talep.get('sayfa_url')}`
- **Hedef Bileşen Grubu:** {bilesen}

---

## 2. Kök Neden & Mimari Analiz
1. **İnceleme:** Gelen geri bildirim, sistemin kullanıcı deneyimi ve iş mantığı açısından değerlendirilmiştir.
2. **Kritik Nokta:** İlgili davranışın çözülmesi için `{bilesen}` üzerinde gerekli kod ve şablon düzenlemeleri yapılacaktır.
3. **İlgili Dosyalar & Modüller:**
"""
    for d in dosyalar:
        plan_md += f"   - `{d}`\n"

    plan_md += f"""
---

## 3. Ekip İçin Adım Adım Aksiyon Planı

### Aşama A: İnceleme ve Hazırlık (`{rol}`)
- İlgili dosyalardaki mevcut state, rota parametreleri ve bileşen event akışını kontrol et.
- Sorunun canlı veya lokal ortamda (`./canli.sh` -> 3000 / 3001) yeniden üretilebilirliğini teyit et.

### Aşama B: Kodlama ve Çözüm
- İlgili bileşende gerekli refactor / hata düzeltmesini yap.
- Varsa tip uyuşmazlığı, null/undefined kontrolleri (`optional chaining`) ve reaktif değişkenleri koru.
- Sayfa yüklenirken veya aksiyon gerçekleşirken UI tepkisiz kalmamalı, gerekirse yükleniyor göstergesi ekle.

### Aşama C: Test ve Ziyaretçi Doğrulaması (`uat_auditor` / `qa_lead`)
- Değişiklik sonrası tarayıcı konsolunda hata (0 TypeError, 0 Uncaught) oluşmadığını doğrula.
- Kullanıcı senaryosunu baştan sona (tıklama, arama, filtreleme veya veri akışı) tekrar dene.

---

## 4. Kabul Kriterleri (Definition of Done)
- [ ] Müşterinin bildirdiği hata veya eksiklik tamamen ortadan kalktı.
- [ ] İlgili ekranda (`{talep.get('sayfa_url')}`) görsel veya işlevsel bir kırılma yaşanmadı.
- [ ] Mevcut çalışan diğer rotalar ve özellikler bozulmadan korundu.
- [ ] Değişiklik tamamlandıktan sonra talep durumu `COZULDU` olarak güncellendi.
"""

    plan_abs_path.write_text(plan_md, encoding="utf-8")

    # Müşteri talepleri veritabanını güncelle
    studio_notu = f"Talep Studio Yetkilisi tarafından incelendi. {unvan} ({rol}) görevlendirildi. Çözüm planı '{plan_rel_path}' oluşturuldu."
    MT.guncelle(talep_id, durum="PLANLANDI", gorevli_rol=rol,
                studio_notu=studio_notu, cozum_plani=plan_rel_path)

    # GitHub Issue varsa çözüm planını yorum olarak ilet
    if GH and talep.get("github_issue_number"):
        comment_body = f"### 📋 Studio Yetkilisi Çözüm Planı Hazırlandı\n\n- **Görevli Rol:** `{rol}` ({unvan})\n- **Hedef Bileşen:** {bilesen}\n\n---\n\n{plan_md}"
        GH.github_issue_yorum_ekle(talep["github_issue_number"], comment_body)
        print(f"  🐙 GitHub Issue #{talep['github_issue_number']} çözüm planı yorumu eklendi.")

    return plan_rel_path


def tum_bekleyenleri_planla():
    """Tüm 'BEKLEMEDE' durumundaki talepleri otomatik olarak planlar."""
    data = MT.load_data()
    bekleyenler = [t for t in data.get("talepler", []) if t.get("durum") == "BEKLEMEDE"]
    if not bekleyenler:
        print("[i] Bekleyen talep bulunmuyor. Tüm talepler zaten planlanmış veya çözülmüş.")
        return []

    uretilenler = []
    print(f"\n── Studio Yetkilisi: {len(bekleyenler)} Talep Analiz Ediliyor ────────────")
    for t in bekleyenler:
        tid = t["id"]
        path = cozum_plani_olustur(tid)
        uretilenler.append((tid, path))
        print(f" ✓ [{tid}] Analiz tamamlandı -> {path}")
    print()
    return uretilenler


def otomatik_musteri_talepleri_senkronize_et() -> int:
    """Bekleyen tüm müşteri taleplerini algılar:
    1. Planı çıkmamış olanlara plan çıkarır ve GitHub issue altına postalar.
    2. Panoya (pano.json) henüz eklenmemiş olanlar için yeni bir sprint fazı açıp
       geliştirme ve UAT doğrulama görevlerini ekler.
    3. Eklenen talep sayısını döner.
    """
    sys.path.insert(0, str(ROOT))
    import studio_board as B
    board = B.load()
    if not board:
        return 0

    data = MT.load_data()
    talepler = data.get("talepler", [])
    if not talepler:
        return 0

    # Mevcut panodaki görevlerde kayıtlı talep ID'leri
    mevcut_talep_idler = set()
    for _, task in B.all_tasks(board):
        if task.get("talep_id"):
            mevcut_talep_idler.add(task["talep_id"])
        m = re.search(r"TALEP-\d+", task.get("title", ""))
        if m:
            mevcut_talep_idler.add(m.group(0))

    # Yalnızca aktif faza ait onaylanmış talepler ve acil HATA (Bug) bildirimleri sprinte alınır
    isleme_alinacaklar = []
    for t in talepler:
        tid = t.get("id")
        durum = t.get("durum", "BEKLEMEDE")
        tur = t.get("tur", "HATA").upper()
        faz_id = t.get("faz_id", "FAZ-1")

        if durum in ("COZULDU", "IPTAL", "DEGERLENDIRMEDE", "FAZ_BEKLIYOR"):
            continue
        if tid in mevcut_talep_idler:
            continue

        # Sadece HATA olanlar veya Faz 1 onaylı olanlar aktif sprinte girebilir
        if tur != "HATA" and faz_id != "FAZ-1":
            continue

        # Planı yoksa önce plan çıkar
        if not t.get("cozum_plani"):
            cozum_plani_olustur(tid)
            t = MT.getir(tid) or t
        isleme_alinacaklar.append(t)

    if not isleme_alinacaklar:
        return 0

    print(f"\n⚡ [MÜŞTERİ TALEPLERİ SENKRONİZASYONU (TRIAGE ONAYLI)]")
    print(f"  {len(isleme_alinacaklar)} adet talep aktif sprint panosuna ekleniyor...")

    sid = f"S{len(board.get('sprints', [])) + 1}"
    tasks = []
    task_counter = 1

    for t in isleme_alinacaklar:
        tid = t["id"]
        rol = t.get("gorevli_rol") or "web_engineer"
        _, ham_dosyalar, _ = tespit_et_rol_ve_bilesen(t)
        plan_dosyasi = t.get("cozum_plani") or f"workspace/docs/cozum_planlari/{tid}.md"

        # Çıktı yollarının mutlak olarak workspace/ altında kaldığını garanti et
        guvenli_dosyalar = [d for d in ham_dosyalar if d.startswith("workspace/")]
        if not guvenli_dosyalar:
            guvenli_dosyalar = ["workspace/src/frontend/"]

        # 1. Geliştirme Görevi
        dev_task_id = f"{sid}-T{task_counter}"
        task_counter += 1
        dev_task = {
            "id": dev_task_id,
            "title": f"[{tid}] {t.get('baslik')}",
            "description": f"Müşteri Talebi: {t.get('aciklama')}\nÇözüm Planı: {plan_dosyasi}",
            "role": rol,
            "phase": "develop",
            "outputs": guvenli_dosyalar[:2],
            "depends_on": [],
            "talep_id": tid
        }
        tasks.append(dev_task)

        # 2. UAT & Canlı Doğrulama Görevi
        uat_task_id = f"{sid}-T{task_counter}"
        task_counter += 1
        uat_task = {
            "id": uat_task_id,
            "title": f"[{tid}] Müşteri Kabulü & UAT Doğrulama Denetimi",
            "description": f"{tid} için yapılan düzeltmenin canlı sistemde çalıştığını ve 0 konsol hatası olduğunu doğrula.",
            "role": "uat_auditor",
            "phase": "test",
            "outputs": ["workspace/docs/uat_kabul_raporu.md"],
            "depends_on": [dev_task_id],
            "talep_id": tid
        }
        tasks.append(uat_task)

        # Durumu GELISTIRILIYOR yap
        MT.guncelle(tid, durum="GELISTIRILIYOR",
                    studio_notu=f"Sprint {sid} panosuna eklendi ({dev_task_id} ve {uat_task_id}). Geliştirme başladı.")

        # GitHub Issue varsa yorum ekle
        if GH and t.get("github_issue_number"):
            GH.github_issue_yorum_ekle(
                t["github_issue_number"],
                f"🚀 **Sprint Panosuna Eklendi!**\n- Sprint: `{sid}`\n- Geliştirme Görevi: `{dev_task_id}` (`{rol}`)\n- Doğrulama Görevi: `{uat_task_id}` (`uat_auditor`)"
            )

    new_sprint = {
        "id": sid,
        "name": f"Müşteri Denetimi & Saha Onarımları ({', '.join(t['id'] for t in isleme_alinacaklar)})",
        "goal": f"Site sahibinin ilettiği {len(isleme_alinacaklar)} adet müşteri talebinin çözülmesi ve UAT ile kabul edilmesi.",
        "planned_days": max(1, len(tasks) // 2),
        "tasks": tasks
    }

    B.append_sprint(board, new_sprint)
    B.save(board)
    print(f"  ✓ {len(isleme_alinacaklar)} talep Sprint {sid} olarak panoya başarıyla eklendi!\n")
    return len(isleme_alinacaklar)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Studio Yetkilisi Çözüm Motoru")
    parser.add_argument("--planla", type=str, help="Belirli bir talep ID'si için plan üret")
    parser.add_argument("--hepsini-planla", action="store_true", help="Tüm bekleyen talepler için plan üret")
    parser.add_argument("--cozum-onayla", type=str, help="Talebi çözüldü olarak işaretle")

    args = parser.parse_args()

    if args.planla:
        try:
            p = cozum_plani_olustur(args.planla)
            print(f"✓ [{args.planla}] Plan başarıyla oluşturuldu: {p}")
        except Exception as e:
            sys.exit(f"Hata: {e}")
        return

    if args.hepsini_planla:
        tum_bekleyenleri_planla()
        return

    if args.cozum_onayla:
        if MT.guncelle(args.cozum_onayla, durum="COZULDU",
                       studio_notu=f"{datetime.now().strftime('%Y-%m-%d %H:%M')} itibarıyla ekip tarafından çözüldü ve müşteri onayına sunuldu."):
            print(f"✓ [{args.cozum_onayla}] ÇÖZÜLDÜ olarak işaretlendi.")
        else:
            sys.exit(f"Hata: {args.cozum_onayla} bulunamadı.")


if __name__ == "__main__":
    main()
