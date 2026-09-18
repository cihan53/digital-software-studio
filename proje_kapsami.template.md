# Proje Kapsamı ve İster Dokümanı (Project Brief)

> **Not:** Bu dosya Dijital Yazılım Stüdyosu'nun ana giriş noktasıdır.  
> Geliştirmek istediğiniz uygulamanın amacını, hedeflerini ve teknik sınırlarını aşağıdaki başlıklarda tarif ediniz.  
> Stüdyo motoru (`./basla.sh`), buradaki tanımları okuyarak CTO, Ürün Sahibi, UX/UI, Geliştiriciler ve Test Ajanlarını otomatik olarak görevlendirecektir.

---

## 1. Proje Özeti ve Amacı
- **Proje Adı:** Benim Harika Uygulamam (Örnek)
- **Ana Hedef:** Kullanıcıların ihtiyaç duyduğu temel problemi çözen modern, ölçeklenebilir ve güvenli bir dijital ürün geliştirmek.
- **Hedef Kitle:** Son kullanıcılar, mobil ve masaüstü web ziyaretçileri.

---

## 2. Platformlar ve Teknoloji Tercihleri
- **Web Platformu:** Nuxt 3 / Vue 3 / Tailwind CSS (veya tercih ettiğiniz stack)
- **Backend Servisi:** Node.js (Fastify / Express) veya Python (FastAPI)
- **Veritabanı:** PostgreSQL / SQLite
- **Mobil (Opsiyonel):** Flutter (iOS & Android)

---

## 3. Temel Özellikler ve Kullanıcı Akışları
1. **Karşılama ve Arayüz:** Modern, hızlı, mobil uyumlu ve erişilebilir (WCAG 2.1 AA) ana sayfa.
2. **Kullanıcı İşlevleri:** Arama, filtreleme, listeleme ve detay görünümleri.
3. **API & Veri Yönetimi:** RESTful uç noktalar, girdi doğrulama (validation) ve hata yönetimi (RFC 7807).
4. **Kalite Güvencesi:** Sıfır konsol hatası (0 Console Errors), otomatik birim ve uçtan uca kabul (UAT) testleri.

---

## 4. Kapsam Dışı / Sınırlar
- İlk fazda karmaşık üçüncü parti lisanslı ödeme ağ geçitleri kapsam dışıdır (Faz 2'ye bırakılabilir).
- Canlı sunucuya dağıtım öncesi tüm fonksiyonlar yerel test ortamında doğrulanmalıdır.
