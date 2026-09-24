#!/usr/bin/env python3
"""
scripts/studio_yetkilisi.py
Digital Software Studio — Studio Yetkilisi & Çözüm Koordinasyon Motoru

Müşterinin (proje sahibi) ilettiği istek ve hataları inceler, teknik ve mimari
kök neden analizini yapar, sorumlu ekibi (Web, Backend, Data, DevOps, QA vb.)
görevlendirir ve adım adım çözüm planı oluşturur.

v2.0 — Akıllı Kategori Motoru + AI Danışma Katmanı (AGY / Claude)
"""

import json
import os
import re
import subprocess
import sys
import textwrap
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


# ==============================================================================
# KATEGORİ & ROL TESPİT SİSTEMİ — v2.0
# Öncelik sırasına göre eşleştirme yapılır (ilk eşleşen kazanır)
# ==============================================================================

KATEGORILER = [
    {
        "id": "data_engineer",
        "unvan": "Veri & ETL Mühendisi (Python Pipeline & Scraper)",
        "bilesen": "Veri Kazıma & ETL Pipeline (Python)",
        "anahtar_kelimeler": [
            "scraper", "crawler", "etl", "pipeline", "import", "curl",
            "veri çek", "veri al", "veri kaynağı", "kaynak", "epdk",
            "api entegrasyon", "data-pipeline",
            "curl_input", "fetch", "download", "sync", "senkron",
            "canlı kaynak", "gerçek siteden", "web sitesinden",
        ],
        "dosyalar": [
            "scripts/",
            "server-scripts/",
            "curl_input.txt",
        ],
        "plan_asamalari": """\
### Aşama A: Kaynak & Ortam Analizi (`data_engineer`)
- `curl_input.txt` dosyasını incele — hangi kaynaklar tanımlı (`kaynak: curl ...` formatı)?
- İlgili scraper/fetcher scriptlerinin session ve auth yönetimini gözden geçir.
- Mevcut `load_json_dataset()` veya eşdeğeri kaynak öncelik zincirini anla.

### Aşama B: Kodlama & Entegrasyon (`data_engineer`)
- `curl_input.txt`'i multi-source (`kaynak: curl ...`) formatında okuyacak bir parser modülü yaz/güncelle.
- Her kaynak için (`epdk`, `voltrun`, `zes`) ayrı bir scraper/fetcher fonksiyonu tanımla veya güncelle.
- Kaynak fallback zincirini güncelle: önce yerel cache, sonra canlı API, en son statik fallback.
- Session süresi dolduğunda sistem açıkça uyarsın ve `curl_input.txt` güncellemesini rehberlik etsin.

### Aşama C: Test & Doğrulama (`data_engineer` + `qa_lead`)
- Test verisiyle tüm kaynak zincirini uçtan uca çalıştır.
- Boş veri gelmesi durumunda mevcut `cpo_stations.json`'ın EZİLMEDİĞİNİ doğrula (sıfır-kayıt kalkanı).
- Scraper çıktı JSON dosyasının pipeline tarafından doğru okunduğunu kontrol et.\
""",
        "kabul_kriterleri": [
            "EPDK verisi doğrudan EPDK sitesinden (`epdk_scraper.py` aracılığıyla) çekiliyor.",
            "Voltrun verisi Voltrun API'sinden (`curl_input.txt`'teki `voltrun:` bloğu kullanılarak) çekiliyor.",
            "`curl_input.txt` multi-source formatı (`kaynak: curl ...`) doğru parse ediliyor.",
            "Hiçbir canlı kaynaktan veri gelmediğinde mevcut `cpo_stations.json` korunuyor.",
            "Yeni kaynak eklemek için sadece `curl_input.txt`'e satır eklemek yeterli.",
        ],
    },
    {
        "id": "devops_engineer",
        "unvan": "DevOps & Zamanlama Mühendisi",
        "bilesen": "Altyapı, Zamanlama & Dağıtım (Infra)",
        "anahtar_kelimeler": [
            "docker", "cpanel", "deploy", "sunucu", "nginx", "node sürümü",
            "ci/cd", "infra", "cron", "zamanlanmış", "otomatik çalış",
            "schedule", "plist", "launchd", "systemd", "otomasyonu",
        ],
        "dosyalar": [
            "studio.tick.plist",
            "studio_schedule.sh",
            "canli.sh",
            "cpanel_nuxt_entry.cjs",
            "cpanel_api_entry.cjs",
        ],
        "plan_asamalari": """\
### Aşama A: Ortam & Zamanlama Analizi (`devops_engineer`)
- Mevcut `studio.tick.plist` ve `studio_schedule.sh` konfigürasyonunu incele.
- Sunucu ortamını (cPanel / Linux / macOS LaunchAgent) doğrula.

### Aşama B: Kodlama & Çözüm
- İlgili zamanlanmış görev veya dağıtım script'ini güncelle.
- Ortam değişkenlerini ve path'leri doğru ayarla.

### Aşama C: Test & Doğrulama (`devops_engineer`)
- Manuel tetikleme ile script'in doğru çalıştığını doğrula.
- Log dosyalarını kontrol et, hata olmadığını teyit et.\
""",
        "kabul_kriterleri": [
            "Zamanlanmış görev veya dağıtım adımı beklenen şekilde çalışıyor.",
            "Log dosyalarında hata bulunmuyor.",
            "Mevcut diğer görevler etkilenmemiş.",
        ],
    },
    {
        "id": "backend_engineer",
        "unvan": "Backend & API Mühendisi (Fastify & PostGIS)",
        "bilesen": "Backend API & Servis Katmanı",
        "anahtar_kelimeler": [
            "api", "backend", "fastify", "postgis", "veritabanı", "endpoint",
            "sql", "seed", "tohumlama", "swagger", "404 not found (route",
            "route", "servis", "rest",
        ],
        "dosyalar": [
            "workspace/src/backend/src/modules/",
            "workspace/src/backend/src/app.ts",
        ],
        "plan_asamalari": """\
### Aşama A: İnceleme ve Hazırlık (`backend_engineer`)
- İlgili Fastify modülündeki rota tanımı ve handler mantığını incele.
- Sorunun lokal ortamda (`./canli.sh` → 3001) yeniden üretilebilirliğini teyit et.

### Aşama B: Kodlama ve Çözüm
- İlgili route veya servis katmanında gerekli düzeltmeyi yap.
- Tip uyuşmazlığı, null/undefined kontrolleri ve async hataları kontrol et.
- Swagger/OpenAPI belgesi gerekiyorsa güncelle.

### Aşama C: Test ve Doğrulama (`uat_auditor` / `qa_lead`)
- API endpoint'ini `curl` veya Swagger UI üzerinden manuel test et.
- Tarayıcı konsolunda 0 hata olduğunu doğrula.\
""",
        "kabul_kriterleri": [
            "İlgili API endpoint'i beklenen yanıtı döndürüyor.",
            "Tarayıcı konsolunda TypeError veya Uncaught hatası bulunmuyor.",
            "Mevcut çalışan rotalar bozulmamış.",
        ],
    },
    {
        "id": "ui_designer",
        "unvan": "Arayüz ve Tasarım Uzmanı (UI/UX)",
        "bilesen": "Arayüz Tasarım Sistemi & Tailwind",
        "anahtar_kelimeler": [
            "renk", "font", "tipografi", "padding", "margin", "logo",
            "ikon", "tema", "tasarım", "görünüm", "mobil", "responsive",
            "css", "tailwind", "animasyon",
        ],
        "dosyalar": [
            "workspace/src/frontend/assets/",
            "workspace/src/frontend/tailwind.config.js",
        ],
        "plan_asamalari": """\
### Aşama A: Görsel İnceleme (`ui_designer`)
- İlgili bileşeni tarayıcıda incele, sorunu görsel olarak belgele.
- Tailwind config ve mevcut tasarım token'larını gözden geçir.

### Aşama B: Tasarım Uygulama
- İlgili Vue bileşeninde / CSS dosyasında gerekli stil düzeltmesini yap.
- Mobil ve masaüstü breakpoint'lerinde test et.

### Aşama C: Görsel Doğrulama (`uat_auditor`)
- Değişikliği farklı ekran boyutlarında (mobile / tablet / desktop) kontrol et.\
""",
        "kabul_kriterleri": [
            "Tasarım sorunu görsel olarak giderildi.",
            "Mobil ve masaüstünde düzgün görünüyor.",
            "Diğer bileşenler etkilenmemiş.",
        ],
    },
    {
        # Varsayılan — hiçbiri eşleşmezse
        "id": "web_engineer",
        "unvan": "Kıdemli Web Frontend Mühendisi (Nuxt 3 & Vue)",
        "bilesen": "Nuxt 3 Web Frontend & Harita Arayüzü",
        "anahtar_kelimeler": [],  # varsayılan — her zaman eşleşir
        "dosyalar": [
            "workspace/src/frontend/components/",
            "workspace/src/frontend/pages/",
        ],
        "plan_asamalari": """\
### Aşama A: İnceleme ve Hazırlık (`web_engineer`)
- İlgili Vue bileşenindeki mevcut state, props ve event akışını kontrol et.
- Sorunun lokal ortamda (`./canli.sh` → 3000) yeniden üretilebilirliğini teyit et.

### Aşama B: Kodlama ve Çözüm
- İlgili bileşende gerekli refactor / hata düzeltmesini yap.
- Varsa tip uyuşmazlığı, null/undefined kontrolleri (`optional chaining`) ve reaktif değişkenleri koru.
- Sayfa yüklenirken veya aksiyon gerçekleşirken UI tepkisiz kalmamalı, gerekirse yükleniyor göstergesi ekle.

### Aşama C: Test ve Ziyaretçi Doğrulaması (`uat_auditor` / `qa_lead`)
- Değişiklik sonrası tarayıcı konsolunda hata (0 TypeError, 0 Uncaught) oluşmadığını doğrula.
- Kullanıcı senaryosunu baştan sona (tıklama, arama, filtreleme veya veri akışı) tekrar dene.\
""",
        "kabul_kriterleri": [
            "Müşterinin bildirdiği hata veya eksiklik tamamen ortadan kalktı.",
            "Tarayıcı konsolunda sıfır hata.",
            "Mevcut çalışan rotalar ve özellikler bozulmamış.",
        ],
    },
]


# ==============================================================================
# AI DANIŞMA KATMANI — AGY → Claude → Sessiz Fallback
# ==============================================================================

def ai_danisma(talep: dict, kategori_id: str) -> str:
    """
    Talebi analiz etmek için sırayla AGY (agy), Devin (devin) ve Claude (claude)
    CLI'ye danışır.
    Hiçbiri mevcut değilse veya hata oluşursa boş string döner (sistem çökmez).

    Mevcut AI kaynakları (yerel):
      - agy    : Google Antigravity / Gemini tabanlı
      - devin  : Cognition Devin AI tabanlı
      - claude : Anthropic Claude tabanlı
    """
    prompt = textwrap.dedent(f"""
        Sen bir senior software architect'sin ve Studio Yetkilisi rolündesin.
        Aşağıdaki müşteri talebini analiz et.

        Kategori   : {kategori_id}
        Başlık     : {talep.get('baslik', '')}
        Açıklama   : {talep.get('aciklama', '')}
        Sayfa/URL  : {talep.get('sayfa_url', '')}
        Tür        : {talep.get('tur', '')}

        Şu iki soruya kısa ve uygulanabilir cevaplar ver:
        1. Kök Neden: Bu sorunun teknik kök nedeni ne?
        2. Kritik Riskler: Nelere dikkat edilmeli?

        Cevabını Türkçe yaz. 3-5 cümle yeterli.
    """).strip()

    ai_araclari = [
        {
            "ad": "AGY",
            "komut": ["agy", "ask", "--no-interactive", prompt],
        },
        {
            "ad": "Devin",
            "komut": ["devin", "-p", prompt, "--respect-workspace-trust", "false"],
        },
        {
            "ad": "Claude",
            "komut": ["claude", "--print", prompt],
        },
    ]

    for arac in ai_araclari:
        try:
            result = subprocess.run(
                arac["komut"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(ROOT),
            )
            if result.returncode == 0 and result.stdout.strip():
                cevap = result.stdout.strip()
                print(f"  🤖 [{arac['ad']}] AI analizi alındı ({len(cevap)} karakter).")
                return f"**{arac['ad']} Analizi:**\n\n{cevap}"
        except FileNotFoundError:
            # CLI aracı kurulu değil — sessizce sonrakine geç
            continue
        except subprocess.TimeoutExpired:
            print(f"  ⏱️  [{arac['ad']}] Zaman aşımı (30 sn). Sonraki kaynak deneniyor...")
            continue
        except Exception as e:
            print(f"  ⚠️  [{arac['ad']}] Hata: {e}. Sonraki kaynak deneniyor...")
            continue

    # Hiçbir AI mevcut değil — sessiz fallback
    return ""


# ==============================================================================
# KATEGORİ TESPİT FONKSİYONU — v2.0
# ==============================================================================

def tespit_et_kategori(talep: dict) -> dict:
    """
    Talep metnini analiz ederek en uygun kategoriyi seçer.
    Öncelik sırası: KATEGORILER listesindeki sıra.
    """
    metin = " ".join([
        talep.get("baslik", ""),
        talep.get("aciklama", ""),
        talep.get("sayfa_url", ""),
    ]).lower()

    for kat in KATEGORILER:
        anahtar = kat["anahtar_kelimeler"]
        if not anahtar:
            # Varsayılan kategori — her zaman eşleşir
            return kat
        if any(k in metin for k in anahtar):
            return kat

    # Güvenlik: son kategoriye (web_engineer) düş
    return KATEGORILER[-1]


def tespit_et_rol_ve_bilesen(talep: dict) -> tuple:
    """
    Geriye dönük uyumluluk için korunuyor.
    Yeni kod `tespit_et_kategori()` kullanmalı.
    """
    kat = tespit_et_kategori(talep)
    return kat["id"], kat["dosyalar"], kat["bilesen"]


# ==============================================================================
# ÇÖZÜM PLANI OLUŞTURUCU — v2.0
# ==============================================================================

def cozum_plani_olustur(talep_id: str) -> str:
    """Belirtilen talep için Studio Yetkilisi detaylı çözüm planını hazırlar."""
    talep = MT.getir(talep_id)
    if not talep:
        raise ValueError(f"Talep bulunamadı: {talep_id}")

    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    plan_rel_path = f"workspace/docs/cozum_planlari/{talep_id}.md"
    plan_abs_path = ROOT / plan_rel_path

    # Kategori tespiti
    kat = tespit_et_kategori(talep)
    rol      = kat["id"]
    unvan    = kat["unvan"]
    bilesen  = kat["bilesen"]
    dosyalar = kat["dosyalar"]

    print(f"  🔍 Kategori tespiti: [{rol}] — {bilesen}")

    # Sayfaya göre ek dosya özelleştirme (web / harita odaklı)
    sayfa = talep.get("sayfa_url", "")
    metin = f"{talep.get('baslik','')} {talep.get('aciklama','')}".lower()
    if sayfa == "/" or "harita" in metin:
        dosyalar = list(dosyalar) + [
            "workspace/src/frontend/components/StationMap.vue",
            "workspace/src/frontend/pages/index.vue",
        ]
    elif "/r/" in sayfa or "rota" in metin:
        dosyalar = list(dosyalar) + [
            "workspace/src/frontend/pages/r/[payload].vue",
            "workspace/src/backend/src/modules/route-bridge/route-bridge.routes.ts",
        ]
    elif "istasyon" in sayfa or "detay" in metin:
        dosyalar = list(dosyalar) + [
            "workspace/src/frontend/components/StationDetailModal.vue"
        ]

    dosyalar = list(dict.fromkeys(dosyalar))  # tekrarları kaldır

    # AI danışma — kök neden analizi
    print(f"  🤖 AI danışma katmanı devreye alınıyor (AGY → Claude)...")
    ai_analiz = ai_danisma(talep, rol)
    if not ai_analiz:
        print(f"  ℹ️  AI mevcut değil veya yanıt vermedi. Statik analiz şablonu kullanılacak.")
        ai_analiz = (
            f"**Statik Analiz:**\n\n"
            f"Bu talep `{bilesen}` katmanını etkiliyor. "
            f"İlgili dosyalar ve modüller incelenerek kök neden tespit edilecek, "
            f"ardından aşağıdaki aksiyon planı uygulanacaktır."
        )

    # Kabul kriterleri listesi
    kabul_md = "\n".join(
        f"- [ ] {k}" for k in kat.get("kabul_kriterleri", [
            "Müşterinin bildirdiği hata veya eksiklik tamamen ortadan kalktı.",
            f"İlgili ekranda (`{sayfa or '/'}`) görsel veya işlevsel bir kırılma yaşanmadı.",
            "Mevcut çalışan diğer rotalar ve özellikler bozulmadan korundu.",
            f"Değişiklik tamamlandıktan sonra talep durumu `COZULDU` olarak güncellendi.",
        ])
    )
    # Son iki genel kriter her zaman ekle
    kabul_md += "\n- [ ] Değişiklik tamamlandıktan sonra talep durumu `COZULDU` olarak güncellendi."

    # Dosya listesi markdown
    dosya_md = "\n".join(f"   - `{d}`" for d in dosyalar)

    plan_md = f"""# Studio Yetkilisi Çözüm Planı: {talep_id}

> **Talep:** [{talep_id}] {talep.get('baslik')}  
> **Müşteri / Bildiren:** Proje Sahibi  
> **Bildirim Tarihi:** {talep.get('tarih')}  
> **Öncelik:** {talep.get('oncelik')} | **Tür:** {talep.get('tur')}  
> **Koordinatör:** Studio Yetkilisi & Teknik Liderlik  
> **Görevlendirilen Rol:** `{rol}` ({unvan})  
> **Kategori Tespiti:** Otomatik (keyword analizi + AI destekli)  

---

## 1. Müşteri Talebi ve Problem Tanımı

Müşteri (proje sahibi) denetimi sırasında aşağıdaki durumu tespit etti:

> **Açıklama:**  
> {talep.get('aciklama')}

- **Etkilenen Ekran / URL:** `{talep.get('sayfa_url')}`
- **Hedef Bileşen Grubu:** {bilesen}

---

## 2. Kök Neden & Mimari Analiz

{ai_analiz}

**İlgili Dosyalar & Modüller:**
{dosya_md}

---

## 3. Ekip İçin Adım Adım Aksiyon Planı

{kat['plan_asamalari']}

---

## 4. Kabul Kriterleri (Definition of Done)

{kabul_md}
"""

    plan_abs_path.write_text(plan_md, encoding="utf-8")

    # Müşteri talepleri veritabanını güncelle
    studio_notu = (
        f"Talep Studio Yetkilisi v2.0 tarafından analiz edildi. "
        f"Kategori: [{rol}] {unvan}. "
        f"AI danışma: {'Evet' if 'AGY' in ai_analiz or 'Claude' in ai_analiz else 'Hayır (statik)'} "
        f"Çözüm planı oluşturuldu: '{plan_rel_path}'."
    )
    MT.guncelle(talep_id, durum="PLANLANDI", gorevli_rol=rol,
                studio_notu=studio_notu, cozum_plani=plan_rel_path)

    # GitHub Issue varsa çözüm planını yorum olarak ilet
    if GH and talep.get("github_issue_number"):
        comment_body = (
            f"### 📋 Studio Yetkilisi Çözüm Planı Hazırlandı\n\n"
            f"- **Görevli Rol:** `{rol}` ({unvan})\n"
            f"- **Hedef Bileşen:** {bilesen}\n"
            f"- **Kategori Tespiti:** Otomatik (keyword + AI)\n\n"
            f"---\n\n{plan_md}"
        )
        GH.github_issue_yorum_ekle(talep["github_issue_number"], comment_body)
        print(f"  🐙 GitHub Issue #{talep['github_issue_number']} çözüm planı yorumu eklendi.")

    return plan_rel_path


# ==============================================================================
# TOPLU PLANLAMA
# ==============================================================================

def tum_bekleyenleri_planla():
    """Tüm 'BEKLEMEDE' durumundaki talepleri otomatik olarak planlar."""
    data = MT.load_data()
    bekleyenler = [t for t in data.get("talepler", []) if t.get("durum") == "BEKLEMEDE"]
    if not bekleyenler:
        print("[i] Bekleyen talep bulunmuyor. Tüm talepler zaten planlanmış veya çözülmüş.")
        return []

    uretilenler = []
    print(f"\n── Studio Yetkilisi v2.0: {len(bekleyenler)} Talep Analiz Ediliyor ────────────")
    for t in bekleyenler:
        tid = t["id"]
        path = cozum_plani_olustur(tid)
        uretilenler.append((tid, path))
        print(f" ✓ [{tid}] Analiz tamamlandı -> {path}")
    print()
    return uretilenler


# ==============================================================================
# SPRINT PANOSU SENKRONIZASYONU
# ==============================================================================

def otomatik_musteri_talepleri_senkronize_et() -> int:
    """Bekleyen tüm müşteri taleplerini algılar:
    1. Planı çıkmamış olanlara plan çıkarır ve GitHub issue altına postalar.
    2. Panoya (studio.db) henüz eklenmemiş olanlar için yeni bir sprint fazı açıp
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

    # Yalnızca aktif faza ait onaylanmış talepler ve acil HATA bildirimleri sprinte alınır
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
        kat = tespit_et_kategori(t)
        rol = kat["id"]
        ham_dosyalar = kat["dosyalar"]
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
            "talep_id": tid,
        }
        tasks.append(dev_task)

        # 2. UAT & Canlı Doğrulama Görevi
        uat_task_id = f"{sid}-T{task_counter}"
        task_counter += 1
        uat_task = {
            "id": uat_task_id,
            "title": f"[{tid}] Müşteri Kabulü & UAT Doğrulama Denetimi",
            "description": (
                f"{tid} için yapılan düzeltmenin sistemde çalıştığını ve "
                f"kabul kriterlerini karşıladığını doğrula."
            ),
            "role": "uat_auditor",
            "phase": "test",
            "outputs": ["workspace/docs/uat_kabul_raporu.md"],
            "depends_on": [dev_task_id],
            "talep_id": tid,
        }
        tasks.append(uat_task)

        # Durumu GELISTIRILIYOR yap
        MT.guncelle(
            tid,
            durum="GELISTIRILIYOR",
            studio_notu=(
                f"Sprint {sid} panosuna eklendi ({dev_task_id} ve {uat_task_id}). "
                f"Görevli rol: {rol}. Geliştirme başladı."
            ),
        )

        # GitHub Issue varsa yorum ekle
        if GH and t.get("github_issue_number"):
            GH.github_issue_yorum_ekle(
                t["github_issue_number"],
                (
                    f"🚀 **Sprint Panosuna Eklendi!**\n"
                    f"- Sprint: `{sid}`\n"
                    f"- Geliştirme Görevi: `{dev_task_id}` (`{rol}`)\n"
                    f"- Doğrulama Görevi: `{uat_task_id}` (`uat_auditor`)"
                ),
            )

    new_sprint = {
        "id": sid,
        "name": f"Müşteri Denetimi & Saha Onarımları ({', '.join(t['id'] for t in isleme_alinacaklar)})",
        "goal": (
            f"Site sahibinin ilettiği {len(isleme_alinacaklar)} adet müşteri talebinin "
            f"çözülmesi ve UAT ile kabul edilmesi."
        ),
        "planned_days": max(1, len(tasks) // 2),
        "tasks": tasks,
    }

    B.append_sprint(board, new_sprint)
    B.save(board)
    print(f"  ✓ {len(isleme_alinacaklar)} talep Sprint {sid} olarak panoya başarıyla eklendi!\n")
    return len(isleme_alinacaklar)


# ==============================================================================
# MAIN
# ==============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Studio Yetkilisi Çözüm Motoru v2.0")
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
        if MT.guncelle(
            args.cozum_onayla,
            durum="COZULDU",
            studio_notu=(
                f"{datetime.now().strftime('%Y-%m-%d %H:%M')} itibarıyla ekip tarafından "
                f"çözüldü ve müşteri onayına sunuldu."
            ),
        ):
            print(f"✓ [{args.cozum_onayla}] ÇÖZÜLDÜ olarak işaretlendi.")
        else:
            sys.exit(f"Hata: {args.cozum_onayla} bulunamadı.")


if __name__ == "__main__":
    main()
