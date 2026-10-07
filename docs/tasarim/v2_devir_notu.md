# Studio v2 — devir notu (yeni sohbete taşıma)

Tarih: 2026-10-07 · Ana belge: `docs/tasarim/ortam_ve_akis.md` (tasarım, PR #258 ile `main`'de) · Takip: GitHub etiket `v2`.

## 1. Proje ve depolar

- **Çerçeve:** `/Users/cihan/PROJECT/digital-software-studio` (GitHub `cihan53/digital-software-studio`, ana dal `main`, release iş akışı her merge'de patch sürümü atar; v2 bitince `major:` önekli merge → 2.0.0).
- **Pilot projeler** (aynı brief, farklı AI; karşılaştırma deneyi): `/Users/cihan/PROJECT/oobeya-ui-vue-studio-{claude,gemini,devin}` (Oobeya Angular → Vue/Nuxt taşıma; panel 8090/8091/8092, Nuxt 3000/3100/3200). `/Users/cihan/PROJECT/oobeya-ui-vue-studio` oturumun çalışma dizini.
- Kol güncelleme: kolda `./sync_studio.sh --studio-guncelle`; koşucu/panel yeniden başlatma: `./workspace/yeniden_baslat.sh` (**yalnız kullanıcı başlatır**); kota onayı: `./basla.sh --onayla`; canlı: `./basla.sh --canli`.

## 2. Çalışma kuralları (kullanıcıdan)

1. Her iş: **issue → `feature/<N>` dalı → PR** (`v2` etiketi, başlık `v2:` önekli). Onay kalıbı: kullanıcı **"PR'ı merge et, sync yap"** der → merge + sync.
2. **Şimdilik yalnız claude kolu güncellenir ve orada test edilir** (kullanıcı kararı); gemini ve devin'e sync YOK (devin'in tek istisnası: bozuk dosyayı onarma, kullanıcı istedi).
3. Claude kolunda **elle düzeltme yapılmaz**; ajan/çerçeve çözer, müdahale `workspace/docs/deney_mudahaleler.md`'ye kaydedilir.
4. Koşucuyu kullanıcı başlatır. Koşucu çalışırken panoyu (studio.db) düzenleme (kayıp yazma).
5. Hata için kural eklemek yerine **jenerik çözüm** (kapalı döngü onarım, araçlı ajan, kanıt). Çerçevede projeye özel yol/araç yok (workspace/ altında).
6. Uydurma veri yok; kullanıcı onayı olmadan kota/harcama aşımı yok.
7. GitHub zaman zaman GraphQL/push 500 verir: kısa bekleyip yeniden dene (`git push --no-verify`, `gh api` yedeği).

## 3. Verilen kararlar (tasarım belgesi §14'te işlenmiş)

Müşteri ortamı varsayılan aynı makine (uzak hedef + transfer yöntemi sözleşmeden); yayın `main` + etiket, etiket proje sürümü, `main`'e PR yalnız müşteri onayından sonra; müşteri bildirimi panelden; her tür araç/donanım/anahtar müşteriden istenir (müşteri girdileri listesi), mobil dağıtım fastlane; faz başına bütçe yok; fazlar sıralı; kadro ve faz kararlarını sistem verir (ortam sözleşmesi v2 ilk sürümde insan onaylı, müşteri kabulü müşteride); acil hat koşan görevi bölmez, bitince araya girer ve müşteriyi bilgilendirir.

## 4. Yapılanlar (v1.10.86 civarı, hepsi `main`'de)

| PR | İçerik |
|---|---|
| #258 | v2 tasarım belgesi |
| #260, #262 | Gözlem paneli: neden kartı (`scripts/gozlem.py`), 🔭 Akış sekmesi (audit + claude araç çağrıları), görev git farkı (`/api/akis`, `/api/degisiklik`); notes dalı karışması ve özet biçimi düzeltildi |
| #264 | Canlı ortamı motor kendisi açar (`_canli_otomatik_baslat`, 5 dk arayla ≤3 deneme, `STUDIO_CANLI_OTOMATIK=0` kapatır) |
| önceki | Faz planlama onay kapılı (#250), onarım döngüsü KAYNAK/BUILD gerçek test + UAT bulgusu (#252), UAT ret sayacı/motor kanıtı (#254), betik sözdizimi kapısı (#256) |

## 5. Güncel durum (pilotlar)

- **claude:** v1.10.86 + #264 motoru senkron; panel/koşucu **eski kodla** çalışıyordu. Kota onayı bekliyordu ($11.47/$12.00); canlı (3000) kapalıydı. **Test planı:** kullanıcı `./basla.sh --onayla` + `./workspace/yeniden_baslat.sh` → koşucunun canlıyı kendisi açması, neden kartı, Akış sekmesinde araç çağrıları, görev farkı. TALEP-011 çözüldü (S9 açıldı).
- **devin:** v1.10.83 civarı. `yerel_ortam.sh` iki kez ajan özetiyle ezildi, son sağlam sürüme (0aff518) döndürüldü; **S16-T3'ün asıl değişikliği (B-23) kayıp, görevin yeniden açılması kullanıcı kararı**. Canlı (3200) açılmayı bekliyordu.
- **gemini:** v1.10.83 civarı; S1 bloke (telafi), S6-T2 canlı (3100) bekliyordu.

## 6. Açık işler

**A. Tasarım belgesi düzeltmeleri (çelişkiler):** §3 ilke 5 (faz planı onayı), §4a.3/4a.4 (kadro kilidi/onayı), §10.3 (karar insanda), §9.3 (`yayin` bölümü şemada yok, "projeye göre ayarlanır"), §11.5/§13 (gözlem durumu ve canlı ara adımı), §13'te kimlik/kota ayrımı, bilgilendirme kaydı, müşteri girdileri paneli dilimleri yok.

**B. Analizde ele alınmamış alanlar (belgeye "§16 Eksik alanlar" olarak eklenecek):** (1) tasarım aşaması (tasarım → onay → kodlama), (2) keşif ve sıfırdan/taşıma mod seçimi, (3) **eşzamanlı yazma kilidi** (panel/CLI ↔ koşucu), (4) dayanıklılık/yedek/rollback, (5) test stratejisi + regresyon belleği + gereksinim→test izi, (6) proje hafızası, (7) **başarı ölçütleri ve deney metrikleri**, (8) güvenlik tehdit modeli, (9) kalite boyutları (performans, erişilebilirlik, i18n, tablo sınırı), (10) paketleme/dokümantasyon/on-premise, (11) müşteri/operatör yetki modeli, (12) dal stratejisi, (13) dilim DoD ve risk kaydı. **Kullanıcıdan bekleyen kararlar:** yazma kilidi, ölçütler, tasarım aşaması v2'de ilk sınıf mı.

**C. Sonraki dilimler (§13):** organizasyon kurulumu (`organizasyon.json`, mevcut kadroyu içe aktar) → ortam sözleşmesi çekirdeği → araçlı ajan modu + çıktı yazım kuralı (ajan cevabı dosyayı ezmez) → kimlik/kota ayrımı → faz çıkış kapısı → müşteri test ortamı ve yayın → acil hat → kapsam değişikliği etki analizi → mobil/gömülü/backend adaptörleri. Önerilen öncelik: yazma kilidi ve ölçütler (B) ile devam.

## 7. Yeni sohbet için başlangıç istemi

> Studio v2 çalışmasına devam ediyoruz. Önce `/Users/cihan/PROJECT/digital-software-studio/docs/tasarim/v2_devir_notu.md` ve `docs/tasarim/ortam_ve_akis.md` dosyalarını oku. Kurallar: issue→branch→PR (v2 etiketi), yalnız claude kolunu güncelle/test et, claude'da elle düzeltme yok, koşucuyu ben başlatırım. Önce belgedeki çelişkileri düzelt ve §16 "Eksik alanlar" bölümünü ekle (devir notu §6A-B), sonra benden yazma kilidi, ölçütler ve tasarım aşaması kararlarını al; sonra sıradaki dilime geç. Claude kolundaki test durumunu da kontrol et.
