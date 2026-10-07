# Studio v2 — tasarım: organizasyon, ortam sözleşmesi, araçlı ajan modu, müşteri ortamı ve faz çıkış kapısı

Sürüm adı: **v2** · Durum: **taslak (onay bekliyor)** · Kapsam: yalnız tasarım; kod sonraki issue'larda (bkz. §13).

## 0. Sürümleme: v2

Bu belgedeki geliştirmelerin tamamı **v2** olarak anılır. Her dilim (§13) `v2:` önekli issue/PR başlığı ve `v2` etiketiyle açılır. Dilimler `main`'e normal akışla (patch) girer; v1.x hattı çalışmaya devam eder. v2'nin tamamlandığını gösteren son birleştirme `major:` önekiyle yapılır; release iş akışı `2.0.0` etiketini atar. Mevcut pilotlar (claude, devin, gemini) v1.x ile sürer; geçiş dilim dilim, `sync_studio.sh` ile.

## 1. Amaç

Çerçeve (digital-software-studio) farklı türde projeleri (web, mobil, gömülü, backend) aynı akışla yürütmelidir:

1. Basit bir kapsam yazılır; sistem inceler, eksikleri ve önerileri brief ekranıyla tamamlar.
2. Kapsam netleşince **organizasyon (rol kadrosu)** proje türüne göre kurulur ve onaylanır.
3. Kapsam sürecin her yerinde değişebilir; değişiklik boyutuna göre mevcut faz ilerler ya da yeni faz oluşur.
4. Kapsam kesinleşince teknik gereksinimler planlanır, faz ve sprintlere bölünür.
5. Geliştirme ortamı ve müşteri test ortamı hazırlanır.
6. Ajanlar geliştirme ortamında kodu geliştirir, test eder, hataları kendileri çözer.
7. Ajanlar gerçek ekran gezisiyle (UAT) doğrular; bulgular sprinte eklenir. Ortamı kıran hata anında çözülür.
8. Tüm kapılardan geçenler müşteri test ortamında müşteri onayına sunulur; onaylananlar kaynak yönetimine alınır.

## 2. Pilotlardan çıkan sorunlar (kanıt)

| Gözlem | Kök neden |
|---|---|
| devin `yerel_ortam.sh` dosyasının içeriği ajanın sohbet özeti oldu (iki kez) | Motor ajanın son cevabını çıktı dosyasına yazıyor; araçlı ajanlar (devin, agy, claude+araç) dosyayı kendileri düzenleyip özet yazıyor |
| claude `costLedger.test.ts` sonuna sohbet metni sızdı, test kırmızı kaldı | Aynı sınıf |
| Telafi üç kez "kapı zaten geçiyordu" dedi, UAT yine reddetti | Kapı ile gerçek hakem (UAT) farklı ölçüte bakıyordu; UAT ajanı komut çalıştıramadığı için eski kanıtla reddetti |
| claude "kota" beklerken aslında OAuth oturumu düşmüştü | Kimlik hatası kota hatasından ayrılmıyor |
| Her hata için kapı/kural ekleniyor | Ajan ile motor aynı doğrulama araçlarını kullanmıyor |
| Yerel ortam betiğini ajan yazıyor, çerçeve yönetmiyor | Ortam tanımı yapısal veri değil, serbest betik |
| Faz kapatma tamamen elle | Faz çıkış kriteri yok |

## 3. İlkeler

1. **Çerçeve proje türünü ve araçları bilmez.** Süreç yaşam döngüsünü, kanıt toplamayı, kapıları ve onayları yönetir; "nasıl derlenir/çalışır/doğrulanır" proje sözleşmesindedir.
2. **Hata kural ile değil, kanıtla çözülür.** Ajan hatayı gerçek çıktısıyla görür, kendi aracıyla düzeltir, motor aynı ölçütle doğrular.
3. **Ajan ve motor aynı doğrulama araçlarına bakar.** Biri başarılı diğeri başarısız diyemez.
4. **Ajanın cevabı dosya değildir.** Araçlı modda cevap yalnız özettir; çıktı dosyaları ajan tarafından yazılır, motor yalnız "var mı, değişti mi, doğrulama geçti mi" bakar.
5. **İnsan kararı yalnız karar gerektiren yerde:** ortam sözleşmesi onayı (v2 ilk sürüm), müşteri kabulü, kota aşımı, devre kesici sonrası devir. Kadro, faz planı, faz geçişi ve kapsam yerleşimi kararlarını sistem verir; insan bilgilendirme kaydını görür ve geri alabilir (§10.5).
6. **Gizli bilgi ajana görünmez** (§12).

## 4. Akış ve mevcut durum

| # | Adım | Bugün | Bu tasarımla |
|---|---|---|---|
| 1-2 | Kapsam + brief görüşmesi | Var | Aynı |
| 2b | Organizasyon kurulumu | Sabit rol kadrosu + planlayıcının dinamik rol sentezi; onay yok | §4a sistem kadro önerir ve karar verir; insana bilgilendirme ve geri alma |
| 3 | Kapsam değişikliği | Müşteri talebi var; etki analizi yok | §10.3 etki analizi ve faz önerisi |
| 4-5 | Gereksinim, faz, sprint planı | Plan ve faz planlama (#249) var; gereksinim izlenebilirliği yok | §10.2 + gereksinim → test izi |
| 6 | Geliştirme ortamı | Ajan yazdığı betik | §5 ortam sözleşmesi |
| 7 | Müşteri test ortamı | Yok | §9 |
| 8 | Ajan geliştirir/test eder/çözer | Yalnız onarımda | §8 araçlı ajan modu |
| 9 | Gerçek ekran gezisi (UAT) | Web için var; canlıyı kullanıcı açıyor | §6 adaptörler; sözleşmeyle çerçeve açar |
| 10 | Bulgular sprinte; ortamı kıran hata anında | Bulgu→talep→telafi var; acil hat yok | §11.2 acil hat |
| 11 | Müşteri onayı | Durum var; test edilecek ortam yok | §9 |
| 12 | Onaylananı kaynak yönetimine al | Görev bazlı otomatik commit; onaya bağlı yayın yok | §9.3 |

## 4a. Organizasyon kurulumu

Bugün: `org_chart.json` sabit bir kadro taşır (rol: sistem istemi, girdi/çıktı, aşama, araçlar, motor/model); planlayıcı bilinmeyen rol isterse motor dinamik rol sentezler. Kadro proje türüne göre ayrı kurulmaz, onay kapısı yoktur ve rol listesi web ağırlıklıdır.

### 4a.1 Model: ortak çekirdek + tür uzmanları
- **Ortak çekirdek (her projede):** CTO, ürün sahibi, sprint planlayıcı, devops, UAT denetçisi, güvenlik/gizlilik, kurtarma nöbetçisi, müşteri temsilcisi.
- **Tür uzmanları (profilden gelir, §7):** web (web mühendisi, ekran gezgin testçi), mobil (platform mühendisi, cihaz testçisi), gömülü (firmware mühendisi, simülatör/donanım testçisi, imza sorumlusu), backend (backend mühendisi, veri mühendisi, yük/güvenlik testçisi).
- Kadro **proje başına** `workspace/organizasyon.json` olarak tutulur; çerçevenin `org_chart.json`'ı varsayılan şablondur.

### 4a.2 Rol şeması
Her rol: `id`, görev ve sorumluluk, **yazma kapsamı** (hangi dosya/dizinler), **araç izinleri**, aşama, motor ve model, **bütçe payı**, sahip olduğu çıktılar (örn. ortam sözleşmesinin sahibi devops). Rol çıktıları dışında yazamaz (§8.3 kapsam denetimi bunu uygular).

### 4a.3 Akış
1. Kapsam ve brief bittikten sonra CTO ve ürün sahibi, tür profilinden başlayarak kadroyu önerir: hangi roller, kaç tane, hangi araç, hangi motor ve model.
2. **Kadro kararını sistem verir** (CTO + ürün sahibi rolleri): müşteri teknik kadro kararını veremeyebilir. Karar gerekçesiyle birlikte panel Onaylar sekmesinde **bilgilendirme kaydı** olarak görünür; insan isterse düzenler ya da geri alır (itiraz penceresi, kadro kilitlenmeden önce). Motor ve model ilk değeri de burada sistem tarafından seçilir; sonradan kontrol panelinden değişir (§11.3).
3. İtiraz penceresi kapanınca (ya da insan "tamam" deyince) kadro kilitlenir. Kilitten sonra rol ekleme/çıkarma (faz sırasında da) **gerekçeyle ve sistem kararıyla** yapılır; her değişiklik bilgilendirme kaydı düşer, insan geri alabilir.

### 4a.4 Dinamik rol sentezi (kontrol altında)
Planlayıcı kadroda olmayan rol isterse rol **önerilen** durumda oluşur, kapsamı dar ve geçicidir. CTO + ürün sahibi gerekçeyle kalıcı kadroya alır ya da reddeder (§4a.3 kilit sonrası kuralı); karar bilgilendirme kaydına düşer, insan geri alabilir. Karar gelene kadar görev bekler ya da mevcut en yakın role atanır.

### 4a.5 Roller üzerinde kontroller
Rol devre dışı bırakma (bugünkü `devre_disi`), rol bazında bütçe ve motor/model, rol bazında araç izni; hepsi kadro belgesinde ve panelde görünür.

## 5. Ortam sözleşmesi

Dosya: `workspace/ortam.json` (proje başına, sürüm kontrolünde). Yapısal veridir; ajan çıktısıyla bozulamaz, doğrulanamıyorsa kabul edilmez.

### 5.1 Alanlar

```
tur        : web | mobil | gomulu | backend (birden fazla olabilir; bölümler ayrı)
kur        : bağımlılıkları hazırlayan komut(lar)
derle      : kaynaktan çalıştırılabilir çıktı
calistir   : { baslat, durdur, yeniden_baslat, log }  -- geliştirme ortamı
saglik     : { dogrulayici, beklenen, zaman_asimi_sn }  -- "ayakta ve doğru mu?"
dogrula    : [ { ad, dogrulayici, komut/parametre, beklenen } ]  -- iç döngü (hızlı)
gez        : [ { ad, dogrulayici, senaryo } ]  -- UAT'nin motoru (gerçek kullanım)
paketle    : { komut, cikti }  -- müşteri ortamına çıkacak sürüm
musteri    : { hedef, transfer, baslat, durdur, saglik }  -- hedef: yerel | uzak; transfer: yöntem (§9.2)
yayin      : { sistem, dal, etiket_bicimi, geri_alma }  -- varsayılan: git, main, vX.Y.Z (§9.3)
tohum      : veri/durum başlatma (mock tohumu, test veritabanı)
gizli      : [ gizli bilgi adları ]  -- değerleri sözleşmede yok (§12)
```

### 5.2 Yaşam döngüsü

1. Teknoloji kararından sonra devops rolü, tür profilinden (§7) başlayarak sözleşmeyi yazar.
2. Çerçeve sözleşmeyi **doğrular**: komutlar var mı; `calistir` ile `saglik` birlikte geçiyor mu; `dogrula` hatasız koşuyor mu. Geçmezse ajan kanıtla yeniden dener (§8 onarım döngüsü).
3. İnsan onayı (onay kapısı). Onaydan sonra sözleşme kilitlenir; değiştirmek için sahip rol, sebep ve yeniden doğrulama gerekir.
4. Çerçeve ortamı yönetir: başlat/durdur/yeniden başlat, PID, log, sağlık yoklaması, zaman aşımı. Ajan "yeniden başlat"ı sözleşmedeki komutla ister.

### 5.3 Örnekler (kısaltılmış)

```json
{ "tur": ["web"],
  "kur": ["pnpm install"], "derle": ["pnpm build"],
  "calistir": {"baslat": "pnpm dev --port ${PORT}", "log": "workspace/logs/dev.log"},
  "saglik": {"dogrulayici": "http", "hedef": "http://localhost:${PORT}/", "beklenen": 200, "zaman_asimi_sn": 90},
  "dogrula": [{"ad":"tip","dogrulayici":"komut","komut":"pnpm typecheck"},
              {"ad":"birim","dogrulayici":"komut","komut":"pnpm test"}],
  "gez": [{"ad":"ekranlar","dogrulayici":"tarayici","senaryo":"workspace/uat_checklist.json"}] }
```

Gömülü: `derle` çapraz derleme, `calistir` QEMU/Renode, `saglik` seri logda "boot ok" (`seri-log`), `dogrula` host'ta birim test + statik analiz, `gez` simülatörde senaryo. Mobil: `calistir` emülatör/simülatör, `saglik` ilk ekran göründü, `gez` `cihaz-ekran` adaptörü. Backend: `calistir` servis + test veritabanı, `saglik` `/health`, `gez` `senaryo` adaptörü (API çağrı dizisi).

### 5.4 Müşteriden istenen girdiler (ortam gereksinimleri)

Müşteri teknik kurulumu bilmeyebilir. Sistem, proje türü ve sözleşmeye göre **tüm gereksinimleri çıkarır ve tarif eder**; müşteri tarifi izleyip sağlar:
- **Araçlar ve hesaplar:** gerekli yazılım/SDK, geliştirici hesapları, lisanslar.
- **Bağlantılar ve ayarlar:** ağ/port, VPN, dış servis adresleri, ortam değişkenleri; adım adım yönerge.
- **Anahtarlar:** mağaza API anahtarı, imzalama sertifikası/profili, SSH/transfer anahtarı, API anahtarları. Değerler §12 kurallarıyla saklanır; ajan görmez.
- **Donanım (gömülü):** cihaz/programlayıcı/seri bağlantı ve bağlantı şeması (`donanim` adaptörü bunu kullanır).
Panelde bir **müşteri girdileri** kontrol listesi bulunur; her madde "bekliyor / sağlandı / doğrulandı" durumundadır. Çerçeve sağlanan girdiyi (ör. bağlantı denemesi, anahtar geçerliliği) doğrular. Eksik girdi bir görevi bloke ederse müşteri panelde bilgilendirilir (§11.2 "bilinen sorun" mekanizması).
**Mobil dağıtım:** müşteriden alınan anahtarlarla **fastlane** (`paketle`/`transfer` adımı) kullanılır; çerçeve yöntemi bilmez, sözleşmedeki komutu yönetir.

## 6. Doğrulayıcı adaptörler

Küçük katalog; proje sözleşmede seçer. Her adaptör aynı arayüzü uygular: `kos(parametre) -> {ok, kanit, sure}`.

| Adaptör | Ne yapar | Türler |
|---|---|---|
| `komut` | Komutu koşar; çıkış kodu ve çıktı kanıttır | hepsi |
| `http` | İstek, durum/gövde iddiası | web, backend |
| `tarayici` | Gerçek tarayıcıda gezi; konsol, ağ, çizim denetimi (bugünkü `render_kapisi.mjs` ve `uat_live_audit.mjs`) | web |
| `cihaz-ekran` | Emülatör/simülatörde dokunma, ekran görüntüsü, erişilebilirlik ağacı | mobil |
| `seri-log` | Log/seri akışında beklenen satırı bekler; zaman aşımı | gömülü |
| `senaryo` | HTTP/gRPC çağrı dizisi ve beklenen sonuçlar | backend |
| `donanim` (isteğe bağlı) | Gerçek cihaza yaz, uçtan uca ölç | gömülü, ileride |

## 7. Proje türü profilleri

Profil, sözleşmenin başlangıç şablonu ve tür kontrol listesidir; araç adı sabitlemez, "bu tür için tipik adımlar" verir. Karışık projelerde birden fazla profil birleşir.

- **web:** tarayıcı gezisi, çizim ve konsol hatası, erişilebilirlik, performans bütçesi, çevrim içi/dışı davranış.
- **mobil:** ekran boyutları ve yönelim, izin akışları, çevrimdışı davranış, mağaza gereklilikleri.
- **gömülü:** bellek/zamanlama bütçesi, kesme/yarış, başlatma ve güç, imza, güvenli güncelleme; donanımsız test edilebilirlik tasarım kararı.
- **backend:** API sözleşmesi, veri geçişleri, yük/performans, güvenlik, gözlemlenebilirlik.

## 8. Araçlı ajan modu

Bugün yalnız talepli develop görevleri `scripts/onarim.py` döngüsüyle çalışır. Hedef: **tüm kod üreten görevler** (develop, devops; sonra test) bu modda.

### 8.1 Akış

1. Motor sözleşmeden ortamı hazırlar (`calistir` + `saglik`).
2. Ajan çağrılır: workspace'te dosyaları kendisi okur/düzenler, sözleşmedeki `dogrula` komutlarını ve gerekirse `gez` adımlarını koşar.
3. Tur sonunda motor **aynı** `dogrula`/`saglik` ölçütünü koşar. Geçerse görev kapanır; geçmezse kanıtla yeni tur (sınır: tur sayısı).
4. Sınır aşılırsa insana devir (devre kesici).

### 8.2 Çıktı yazım kuralı

- Araçlı modda ajan cevabı çıktı dosyasına **yazılmaz**.
- Motor çıktı için yalnız "dosya var mı, bu görevde değişti mi, doğrulama geçti mi" denetler.
- Araçsız (salt metin üreten) roller (doküman, plan) eskisi gibi çalışır; shebang/anlatım temizliği yalnız bu yolda kalır.

### 8.3 Güvenlik

- Yazma kapsamı `workspace/**`; çerçeve dosyaları değiştirilirse tur sonunda geri alınır, bütünlük denetimi (bugünkü onarım mekanizması).
- Komut yasakları (`sudo`, `git push/reset/...`, `pkill`) claude'da zorunlu; devin/agy kendi izin modunda: kapsam ve bütünlük denetimi onlar için de geçerli.
- Tur öncesi git kontrol noktası.

### 8.4 Maliyet

Araçlı mod daha yavaş ve pahalıdır. Kademeli geçiş (§13) ve görev/rol bazında motor-model seçimi (§11.3) ile yönetilir. Gömülüde derleme uzun olduğu için tur zaman aşımı sözleşmeden okunur.

## 9. Üç ortam ve yayın

### 9.1 Geliştirme ortamı
Sözleşmedeki `calistir`; sıcak yeniden yükleme varsa kullanır. Ajanlar ve UAT burada çalışır. Kıran hata acil hattı tetikler (§11.2).

### 9.2 Müşteri test ortamı
`paketle` çıktısından, **son onay adayı sürümden** kurulan sabit ortam; ayrı port/hedef ve ayrı tohum verisi. Geliştirme bozulsa etkilenmez. Müşteri onayı burada verilir (panel Onaylar sekmesinde bağlantı).
**Hedef ve transfer:** müşteri ortamı varsayılan olarak **aynı makinede** (`hedef: yerel`, ayrı port/süreç) çalışır; ayrı bir makine de olabilir (`hedef: uzak`). Uzak hedefte `paketle` çıktısı sözleşmedeki **transfer yöntemiyle** taşınır; çerçeve yöntemi bilmez, yalnız "paketi hedefe ulaştır, kur, sağlık denetimini geçir" adımlarını yönetir. Aynı adaptör modeli: `transfer` seçenekleri `yerel` (aynı makine, kopyalama gerekmez), `rsync/scp`, `konteyner kaydı`, `git çekme` ve `komut` (proje kendi betiğini verir). Uzak hedefte kimlik bilgileri §12 kurallarıyla yönetilir (anahtar adı sözleşmede, değeri çerçeve sürecinde). Geri alma, bir önceki sürümü aynı transferle yeniden kurmaktır.
Türe göre: web build + preview; mobil test dağıtımı/emülatör imajı; gömülü cihaza yazılabilir imaj ya da emülatör imajı; backend konteyner/ayrı örnek.

### 9.3 Yayın
Müşteri onayı sonrası: sürüm etiketi, kaynak yönetimine alma (**karar: `main`'e PR + etiket**; onaylı sürüm = `main`'deki etiket, geliştirme dalları onaylı sayılmaz). **Etiket = proje sürümü** (örn. `v1.2.0`; fazlar sürüm notunda görünür). **`main`'e PR yalnız müşteri onayından sonra** açılır (sprint sonunda ara PR yok), geri alma talimatı (önceki etiket). Hedef sistem (git/başka) ve onaylı sürüm dalı ortam sözleşmesindeki `yayin` bölümüyle tanımlanır (§5.1; varsayılan: `main` + etiket). Gömülüde ek olarak imza adımı.

## 10. Faz yönetimi

### 10.1 Bugün
`fazlar` (kimlik, ad, açıklama, durum PLANLANDI/AKTIF/TAMAMLANDI, hedef tarih, kilit, önkoşul faz). Talep triage: `ISTEK` değerlendirilir ve faza atanır, aktif olana kadar `FAZ_BEKLIYOR`; `HATA` fazı beklemez. `faz_ilerlet` yalnız durumu çevirir; faz için sprint planlama #249 ile geldi (planlayıcı + insan onayı).

### 10.2 Faz çıkış kapısı (yeni)
Fazı kapatmadan önce motor kontrol eder, eksiği söyler:
- Fazın tüm sprintleri DONE; açık talep/telafi yok.
- UAT geçti (bu faz için çalıştırılmış kanıt).
- Müşteri test ortamında onay alındı (§9.2).
- Gereksinim → test izi: fazın her kabul kriterinin bir doğrulaması var ve geçti.
- Hedef tarihe göre sapma raporu (bilgi; engelleme değil).
Kapı geçerse **sistem fazı kendisi ilerletir** (sonraki faz aktif olur, bildirim kaydı düşer); geçmezse neyin eksik olduğu panelde gösterilir. "Sonraki faza geç" düğmesi insan için zorla geçiş (kayıt altına alınır) ve geri alma (fazı yeniden açma) olarak kalır.

### 10.3 Kapsam değişikliği → etki analizi ve faz önerisi (yeni)
Brief ekranından gelen değişiklik: planlayıcı/CTO rolü etkiyi çıkarır (hangi tamamlanmış iş yeniden açılır, hangi sprintler kayar, tahmini maliyet). Boyut küçükse aktif faza; büyükse yeni faz açılır. Karar sistemdedir (§10.5): kapsam değişikliği etki analiziyle aktif faza ya da yeni faza yerleştirilir; insan bilgilendirme kaydını görür ve geri alabilir.

### 10.4 Tarih uyarısı (yeni, hafif)
Hedef tarihi aşan faz için uyarı; engelleme yok, görünürlük. **Faz başına bütçe v2 kapsamı dışıdır** (kota günlük kalır).

### 10.5 Karar yetkisi

Müşteri teknik karar veremeyebilir; faz kararlarını **sistem verir**, insan görür ve geri alabilir. Müşterinin kendi kararı (kabul) müşteride kalır.

| Karar | Kim verir | İnsan rolü |
|---|---|---|
| Organizasyon kadrosu (§4a) | Sistem (CTO + ürün sahibi) | Bilgilendirme kaydı; kilitlenmeden önce düzenle/geri al |
| Faz planı (sprintler) | Sistem (planlayıcı); plan doğrulama kapısından geçer | Bilgilendirme kaydı; geri alma (bugünkü #249 onay kapısı v2'de bilgilendirmeye döner) |
| Faz geçişi (çıkış kapısı) | Sistem, kriterler sağlanınca | Zorla geçiş / geri açma |
| Kapsam değişikliği: aktif faza mı, yeni faza mı | Sistem (etki analiziyle) | Bilgilendirme; geri alma |
| Ortam sözleşmesi (§5) | Sistem yazar, çerçeve doğrular; **insan onayı v2'nin ilk sürümünde korunur** | Onay (ortamı ve anahtarları etkilediği için) |
| Müşteri kabulü (adım 11) | **Müşteri** | Karar müşteride |

Her sistem kararı gerekçesiyle `audit_log`'a ve panelde bilgilendirme kaydına düşer.

### 10.6 Varsayım
Fazlar sıralıdır (paralel faz kapsam dışı).

## 11. Kontroller, kota, acil hat, motor

### 11.1 Mevcut kontroller (korunur)
Öncelik, atla, şuna geç, duraklat/durdur, kota onayı, görev bazında motor seçimi.

### 11.2 Acil hat (yeni)
Geliştirme veya müşteri ortamını kıran hata (`calistir`/`saglik` başarısız) **koşan görevi bölmez**: görev bitince sıradaki iş olarak araya girer ve iç döngüde çözülür. Hata ortamı kırdığı için koşan görev doğrulanamıyorsa görev bitiremeyeceğinden sınırı aşılınca normal devre kesici işler.
**Müşteri bilgilendirilir:** müşteri ortamını etkileyen (ya da etkileyebilecek) bir acil hat açıldığında müşteri panelinde/sohbetinde "bilinen sorun" notu görünür: ne etkileniyor, durum (bekliyor / çözülüyor / çözüldü) ve çözülünce kapanış bilgisi. İnsan da panelde acil hat uyarısı görür. Ekran/süreç hatası sprint olur ama hemen istenebilir (öncelik).

### 11.3 Motor ve model
Görev ve rol bazında seçim bugün var; eklenecek: proje türü varsayılanı (ör. gömülüde derleme uzun olduğundan daha güçlü model), "araçlı ajan gerektirir" bilgisi.

### 11.4 Kota
Günlük görev ve bütçe bugünkü gibi. Eklenecek: **kimlik hatası ≠ kota** ayrımı (`OAuth ... expired`, `credits balance too low` anlaşılır mesajla koşucuyu durdurur, yeniden denemeyi 5 saat beklemez).

### 11.5 Gözlem paneli: her şeyi görmek

İlke: **insan, sistemin ne yaptığını, ajanın ne yazdığını ve neyle uğraştığını panelden, ek bir araca gerek duymadan görür.** Bugün panelde Pano, Canlı Çıktı (koşan çağrının metin çıktısı), Audit Log ve İşlem Logları (çağrı başına istem/cevap) var; eksikler:

1. **"Şimdi" kartı** (panelin en üstünde, her sekmede görünür; **uygulandı**, bkz. §13 dilim 0): çalışan görev, rol, motor/model, aşama (sıra → kota → ajan → doğrulama), tur sayısı, geçen süre, bu görevin maliyeti; boştaysa **neden beklediği** (canlı kapalı, kota onayı, kimlik hatası, onay kapısı, bağımlılık) tek cümleyle ve ilgili düğmeyle.
2. **Etkinlik akışı** (zaman çizelgesi, filtrelenebilir): görev başladı/bitti, ajan turu, **ajanın araç çağrıları** (okudu: dosya, yazdı: dosya, çalıştırdı: komut ve çıkış), kapı sonuçları (render, UAT, test, betik), onarım turları, telafi/talep açılışı, onay/bilgilendirme kayıtları, kota ve kimlik olayları. Her satır ilgili görev ve çağrıya bağlanır.
3. **Değişiklik görünümü:** görev (ve tur) başına git farkı: değişen dosyalar, satır farkı (diff), eklenen/silinen test. "Ajan ne yazdı?" sorusunun cevabı çıktı özeti değil gerçek kod farkıdır.
4. **Ajan konuşması:** tam istem ve cevap (bugünkü İşlem Logları) + araç çağrıları aynı ekranda. Motor araç çağrılarını sunuyorsa (claude akış çıktısı) gerçek zamanlı; sunmuyorsa (devin/agy) görev sonunda git farkı ve komut geçmişi ile yetinilir.
5. **Ortam ve sağlık:** geliştirme/müşteri ortamı durumu, son sağlık sonucu, portlar, son loglar (sözleşmeden, §5).
6. **Kota ve maliyet:** bugün ve dönem harcaması, rol ve görev bazında kırılım.
7. **Bildirimler:** koşucu durduğunda (kimlik, kredi, kota, insan devri, ortam kırıldı) panelde belirgin uyarı; müşteriye gidenler ayrıca işaretlenir (§11.2).
8. **Müşteri girdileri ve onay kuyruğu** özeti (§5.4, Onaylar sekmesi).

**Durum:** 1 (neden kartı), 2 (Akış sekmesi: audit + claude araç çağrıları) ve 3 (görev git farkı) #260/#262 ile uygulandı; 4-8 kısmen ya da henüz yok. Canlı ortamı motor kendisi açar (#264, ara adım).

Veri kaynağı yeni bir sistem değil: mevcut `audit_log` ve `.trace` olay akışı genişletilir (olay türleri ve araç çağrısı kaydı), panel bunu okur. Kayıtlarda gizli değerler maskelenir (§12).

## 12. Güvenlik ve gizlilik

- Gizli değerler (imzalama anahtarı, API anahtarı, giriş bilgileri) sözleşmede ve ajan görünürlüğünde yok; yalnız adları (`gizli`) tutulur, değer ortam değişkeni olarak çerçeve süreçlerine verilir.
- Müşteri ortamı kaynak kodu ve anahtarlar içermeyen paket kullanır.
- Her ajan işlemi `audit_log`'a düşer; sözleşme değişikliği ve zorla geçiş ayrıca kaydedilir.

## 13. Geçiş planı (PR dilimleri)

0. **Gözlem paneli (§11.5)** — **büyük kısmı uygulandı (#260, #262, #264)**; kalan: ortam/sağlık, kota kırılımı, müşteri girdileri özeti. Sonraki dilimlerin izlenmesini kolaylaştırır; mevcut `audit_log`/`.trace` olay akışı, "Şimdi" kartı, etkinlik akışı, değişiklik görünümü.
0b. **Organizasyon kurulumu:** `organizasyon.json` şeması, kadro önerisi ve onayı, kontrollü dinamik rol sentezi, tür profillerinden varsayılan kadro.
1. **Ortam sözleşmesi çekirdeği:** şema, doğrulama, `komut`/`http`/`tarayici` adaptörleri, `calistir`/`saglik` yönetimi, web profili. Mevcut `yerel_ortam_yonet.py`, `build_checklist.json`, `smoke_checklist.json`, `uat_checklist.json` ve `studio.config.json` içindeki `kalite.*`/`live.ports` buna taşınır.
2. **Araçlı ajan modu:** önce devops ve web/backend develop, sonra tüm develop; çıktı yazım kuralı; test/doküman görevleri eskisi gibi.
3. **Kimlik/kota ayrımı** (küçük, bağımsız): `OAuth expired` / `credits balance too low` → koşucu anlaşılır mesajla durur, 5 saat beklemez (§11.4).
3b. **Bilgilendirme kaydı:** sistem kararlarının (kadro, faz planı, geçiş, kapsam yerleşimi) gerekçeli kaydı ve panelde geri alma düğmesi (§10.5). #250 faz planı onay kapısı bu dilimde bilgilendirmeye döner.
3c. **Müşteri girdileri paneli:** §5.4 kontrol listesi (bekliyor/sağlandı/doğrulandı) ve doğrulama.
3d. **Yazma kilidi ve ölçütler** (§16 sonucuna göre).
4. **Faz çıkış kapısı** (+ gereksinim → test izi).
5. **Müşteri test ortamı ve yayın akışı.**
6. **Acil hat ve müşteri bilgilendirmesi** (bilinen sorun notu).
7. **Kapsam değişikliği etki analizi ve faz önerisi; tarih uyarısı.**
8. **Mobil, gömülü, backend adaptörleri ve profilleri** (her biri ayrı küçük PR).

Her dilim: issue → branch → PR; testler ve README güncellemesi. Pilot (devin/claude) ortamlarında izlenir.

### 13.1 Geriye uyumluluk ve pilotların geçişi

Çalışan üç pilot (claude, gemini, devin) kesintisiz geçer; "büyük patlama" yok. Kurallar:

1. **Her dilim eski davranışı korur:** yeni dosya (`organizasyon.json`, `ortam.json`) yoksa çerçeve bugünkü yolla çalışır. Yeni alanlar `studio.config.json` ve veritabanında isteğe bağlıdır; şema eklemeleri `CREATE IF NOT EXISTS` / `normalize` ile kendiliğinden yapılır.
2. **İçe aktarma, yeniden kurulum değil:** pilotlar mevcut kadrodan ve dosyalardan **türetilen** belgelerle geçer:
   - `organizasyon.json` ← `org_chart.json` + sentezlenmiş dinamik roller (karar kaydı: "mevcut kadro içe aktarıldı").
   - `ortam.json` ← `workspace/yerel_ortam.sh`, `studio.config.json` (`live.ports`, `kalite.*`), `build_checklist.json`, `smoke_checklist.json`, `uat_checklist.json`. Çerçeve doğrular; insan sözleşmeyi onaylar; onaylanana kadar eski yol sürer.
   - Mevcut fazlar (FAZ-1 TAMAMLANDI, FAZ-2 AKTIF vb.) olduğu gibi kalır; çıkış kapısı yalnız yeni kapanışlara uygulanır.
3. **Araçlı ajan modu proje başına açılır** (`studio.config.json`); önce bir pilotta (öneri: devin, çünkü sorun orada çıktı), sonra diğerlerinde.
4. **Deney bütünlüğü:** üç kol aynı çerçeve sürümünde ve aynı anda güncellenir; her müdahale `deney_mudahaleler.md`'ye kaydedilir; kolların karşılaştırılabilirliğini bozan dilimler (ör. araçlı mod) tüm kollara birlikte açılır ya da farkı kayda geçirilir.
5. Her sync sonrası koşucu yeniden başlatılır (görev yarıda kalmasın diye motor kendiliğinden dokunmaz).

| Dilim | Pilotlarda etkisi | Ek iş |
|---|---|---|
| Gözlem paneli | Hemen: mevcut `audit_log` ve `.trace` okunur | Yalnız sync + yeniden başlatma |
| Organizasyon kurulumu | Mevcut kadro içe aktarılır, sistem kararı kaydedilir | İçe aktarma betiği |
| Ortam sözleşmesi | Mevcut dosyalardan türetilir, onay sonrası geçer | İçe aktarma + sözleşme onayı |
| Araçlı ajan modu | Proje başına bayrakla; devin'de önce | Bayrak açma |
| Faz çıkış kapısı | Yeni kapanışlarda | Yok |
| Müşteri ortamı ve yayın | Bir sonraki müşteri onayında | Hedef/transfer yapılandırması |
| Acil hat | Hemen | Yok |

## 14. Açık sorular

1. ~~Gömülüde gerçek donanım~~ **Karar:** her tür araç, hesap, bağlantı ve donanım müşteriden istenebilir; sistem gereksinim listesini ve kurulum/bağlantı tarifini üretir, müşteri kurar (§5.4). `donanim` adaptörü bu yüzden ilk sürümde desteklenir (müşteri sağladığı cihaz/bağlantı ile).
2. ~~Müşteri test ortamı aynı makinede mi, uzak mı?~~ **Karar:** varsayılan aynı makine; uzak hedef ve transfer yöntemi sözleşmeden seçilir (§9.2). Açık kalan: hangi transfer yöntemleri ilk sürümde desteklenecek (öneri: yerel, `komut`).
3. ~~Yayın hedefi, onaylı sürüm dalı, etiket adı, PR sıklığı~~ **Kararlar:** `main` + etiket; etiket proje sürümü; `main`'e PR yalnız müşteri onayından sonra (§9.3).
4. ~~Mobil dağıtım kanalı ve imza~~ **Karar:** dağıtım için gereken anahtarlar (mağaza API anahtarı, imzalama sertifikası/profili) müşteriden alınır ve **fastlane** ile dağıtılır (§5.4, §12).
5. ~~Acil hat koşan görevi böler mi?~~ **Karar:** bölmez, görev bitince araya girer; müşteri bilgilendirilir (§11.2). **Karar:** müşteri bildirim kanalı panel (müşteri sohbeti/durum ekranı); e-posta v2 kapsamı dışı.
6. ~~Faz başına kota~~ **Karar:** gerek yok (§10.4).
7. ~~Paralel faz~~ **Karar:** şimdilik sıralı (§10.6).
8. ~~Kadro onayı yeri~~ ve ~~sistem karar verir kapsamı~~ **Karar:** kadro ve faz kararları (plan, geçiş, kapsam değişikliği yerleşimi) sistemde; ortam sözleşmesi v2 ilk sürümde insan onaylı; müşteri kabulü müşteride (§10.5).

## 15. Kapsam dışı

- Belirli bir araç zincirine (Nuxt, Gradle, CMake…) gömülü kural.
- Üretim ortamına dağıtım otomasyonu (müşteri onayına kadar).
- Çok-AI karşılaştırma deneyinin yönetimi (ayrı çalışma).

## 16. Eksik alanlar (analizde ele alınmamış)

Pilot gözlemlerinden ve bu belgenin gözden geçirilmesinden çıkan alanlar. Her madde: **sorun → öneri**; "Karar" işaretliler kullanıcıdan bekler, diğerleri varsayılan öneriyle ilerler.

1. **Tasarım aşaması.** Bugün gereksinimden doğrudan kodlamaya geçiliyor; mimari/ekran/veri tasarımı onaysız. → Faz başına *tasarım → onay → kodlama*: tasarım çıktısı (`workspace/docs/`) ve sistem onayı (bilgilendirme kaydı) kodlama görevlerinin girdisi olur. **Karar:** v2'de ilk sınıf aşama mı, yoksa görev türü mü?
2. **Keşif ve mod seçimi (sıfırdan / taşıma).** Pilotlar taşıma; sıfırdan başlama analizi #59'da. → Brief sonunda `mod` alanı (`sifirdan` | `tasima`); taşımada kaynak envanteri ve parite listesi zorunlu.
3. **Eşzamanlı yazma kilidi.** Panel/CLI ile koşucu aynı `studio.db`'ye yazıyor; koşucu çalışırken pano düzenlemek kayıp yazma doğuruyor (şu an yalnız kural: düzenleme yapma). → Yazma tek yol üzerinden (koşucu sahibi; panel/CLI istek kuyruğuna yazar ya da sürücü kilidi `workspace/.control/yazma.kilit` alır). **Karar.**
4. **Dayanıklılık, yedek, geri alma.** Yarım kalan yazma, bozuk dosya (devin `yerel_ortam.sh` olayı) ve db bozulmasına karşı sistematik koruma yok. → Tur öncesi git kontrol noktası (§8.3) yanında `studio.db` anlık yedeği (günlük + kritik geçişlerde), sürümlü sözleşme dosyaları, tek komutla geri dönüş.
5. **Test stratejisi, regresyon belleği, gereksinim→test izi.** Bugün regresyon taraması ve smoke var; kabul kriteri ↔ test eşlemesi yok (§10.2 bunu varsayıyor). → Her gereksinimin test kimliği, düzeltilen her hata için kalıcı regresyon testi, iz tablosu.
6. **Proje hafızası.** Ajanlar her çağrıda bağlamı yeniden kuruyor; alınan kararlar ve öğrenilenler taşınmıyor. → `workspace/docs/hafiza.md` (karar, sebep, tarih); rol istemlerine ilgili kısım enjekte edilir; gizli değer içermez (§12).
7. **Başarı ölçütleri ve deney metrikleri.** Üç AI kolunun karşılaştırması için ortak ölçü yok. → Kol başına: tamamlanan görev/parite oranı, UAT ilk geçiş oranı, onarım turu/görev, insan müdahale sayısı (`deney_mudahaleler.md`), maliyet/görev, kapı yeniden açılma oranı. **Karar:** hangi ölçütler ve eşikler.
8. **Güvenlik tehdit modeli.** §12 yalnız gizli değerleri kapsıyor. → Tehditler: ajanın komut yürütmesi, bağımlılık zinciri, istem enjeksiyonu (müşteri girdisi/web içeriği), müşteri ortamına sızıntı; her biri için kontrol ve sahibi rol (güvenlik/gizlilik).
9. **Kalite boyutları.** Performans bütçesi, erişilebilirlik, i18n, tablo/liste sınırları §7'de yalnız tür kontrol listesi. → `dogrula`/`gez` adımı olarak sözleşmeye bağlanır, faz çıkış kapısında (§10.2) görünür.
10. **Paketleme, dokümantasyon, on-premise.** Teslim edilen paket, kurulum/işletim dokümanı, müşteri sunucusunda çalıştırma tanımsız. → `paketle` çıktısına teslim dokümanı eklenir; on-premise `musteri.hedef: uzak` ile aynı yolu kullanır.
11. **Müşteri/operatör yetki modeli.** Panelde herkes her şeyi yapabiliyor. → Roller: operatör (tam), müşteri (kabul, girdi sağlama, bilinen sorun görme), salt-okur; zorla geçiş ve kota onayı yalnız operatör.
12. **Dal stratejisi.** Pilotlarda tek `studio/calisma` dalı ve görev bazlı otomatik commit; yayın `main`+etiket (§9.3). → Çalışma dalı → müşteri onayında `main`'e PR; faz başına etiket; hotfix yolu (acil hat, §11.2) tanımlanır.
13. **Dilim DoD ve risk kaydı.** Dilimlerin "bitti" ölçütü ve riskleri belgesiz. → Her dilim: testler yeşil, README, claude kolunda doğrulama, geriye uyumluluk kontrolü (§13.1); riskler `workspace/docs/risk_kaydi.md`.

### Bekleyen kararlar
Madde **3** (yazma kilidi), **7** (ölçütler), **1** (tasarım aşaması) — kullanıcıdan alınacak; diğerleri varsayılan öneriyle ilerler.
