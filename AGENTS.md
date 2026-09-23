# Digital Software Studio — Geliştirme ve İş Akışı Kuralları

Bu dosya, projede yapılacak tüm görevler, hata düzeltmeleri ve özellik geliştirmeleri için zorunlu iş akışı kurallarını tanımlar.

---

## 📌 Zorunlu Görev / Hata Çözüm İş Akışı (Git Issue & Branch & PR Kuralı)

Kullanıcı **"bunu çöz"**, **"bu hatayı gider"**, **"bunu yap"** veya herhangi bir geliştirme/düzeltme istediğinde kesinlikle aşağıdaki adımlar sırasıyla uygulanmalıdır:

1. **GitHub Issue Aç:**
   * Görev veya hata için GitHub üzerinde açıklayıcı bir Issue oluşturulur:
     ```bash
     gh issue create --title "<Kısa ve net başlık>" --body "<Detaylı açıklama ve kabul kriterleri>"
     ```
   * Oluşturulan Issue numarası (örn. `#12`) alınır.

2. **Ana Daldan (main / master) Dal (Branch) Aç:**
   * Ana dal güncellenir ve doğrudan Issue numarası referans alınarak yeni dal açılır:
     ```bash
     git checkout main
     git pull origin main
     git checkout -b issue-<issue_number>-<kisa_aciklama>
     # Örnek: git checkout -b issue-12-sqlite-surec-gecisi
     ```

3. **Geliştirmeyi Dal İçerisinde Yap ve Doğrula:**
   * İlgili değişiklikler ve testler sadece bu dal üzerinde gerçekleştirilir.
   * Planlama modu gerekiyorsa plan hazırlanır ve onay alınır, ardından kodlama tamamlanır.
   * Testler ve doğrulamalar çalıştırılır.

4. **Değişiklikleri Commit ve Push Et:**
   ```bash
   git add .
   git commit -m "fix/feat: <açıklama> (closes #<issue_number>)"
   git push origin issue-<issue_number>-<kisa_aciklama>
   ```

5. **Merge Request / Pull Request (MR/PR) Aç:**
   * GitHub üzerinde `main` dalına doğru bir Pull Request açılır ve Issue ile bağlanır:
     ```bash
     gh pr create --title "<PR Başlığı>" --body "Closes #<issue_number>\n\n<Yapılan değişikliklerin özeti>" --base main
     ```
   * PR linki kullanıcıya sunulur.
