# Digital Software Studio — Geliştirme ve İş Akışı Kuralları

Bu dosya, projede yapılacak tüm görevler, hata düzeltmeleri ve özellik geliştirmeleri için zorunlu iş akışı kurallarını tanımlar.

---

## 📌 Zorunlu Görev / Hata Çözüm İş Akışı (Git Issue & Branch & PR Kuralı)

> Bu akış `~/.gemini/config/rules/git_development_workflow.md` global kuralıyla
> aynı konvansiyonu kullanır: `master` taban dalı, `bug/<N>` / `feature/<N>` dalları.

Kullanıcı **"bunu çöz"**, **"bu hatayı gider"**, **"bunu yap"** veya herhangi bir geliştirme/düzeltme istediğinde kesinlikle aşağıdaki adımlar sırasıyla uygulanmalıdır:

1. **GitHub Issue Aç:**
   * Görev veya hata için GitHub üzerinde açıklayıcı bir Issue oluşturulur:
     ```bash
     gh issue create --title "<Kısa ve net başlık>" --body "<Detaylı açıklama ve kabul kriterleri>"
     ```
   * Oluşturulan Issue numarası (örn. `#12`) alınır.

2. **Master'dan Dal (Branch) Aç:**
   * Ana dal güncellenir ve Issue numarası referans alınarak yeni dal açılır.
     Hatalar `bug/<N>`, özellikler/iyileştirmeler `feature/<N>` adını alır:
     ```bash
     git checkout master
     git pull origin master
     git checkout -b bug/<issue_number>        # hata için
     git checkout -b feature/<issue_number>    # özellik için
     ```
   * Not: deponun ana dalı `master` yerine `main` ise `main` kullanılır
     (`git remote show origin | grep 'HEAD branch'` ile görülebilir).

3. **Geliştirmeyi Dal İçerisinde Yap ve Doğrula:**
   * İlgili değişiklikler ve testler sadece bu dal üzerinde gerçekleştirilir.
   * Planlama modu gerekiyorsa plan hazırlanır ve onay alınır, ardından kodlama tamamlanır.
   * Testler ve doğrulamalar çalıştırılır.

4. **Değişiklikleri Commit ve Push Et:**
   ```bash
   git add .
   git commit -m "fix/feat: <açıklama> (#<issue_number>)"
   git push -u origin bug/<issue_number>
   ```

5. **Merge Request / Pull Request (MR/PR) Aç:**
   * GitHub üzerinde `master` dalına doğru bir Pull Request açılır ve Issue ile bağlanır:
     ```bash
     gh pr create --title "<PR Başlığı>" --body "Closes #<issue_number>\n\n<Yapılan değişikliklerin özeti>" --base master
     ```
   * PR linki kullanıcıya sunulur.

---

## 📁 Çalışma Alanı (workspace/) Kuralı

Studio ile bir proje geliştirilirken **projeye ait tüm üretilen dosyalar,
geçici durum ve runtime artefaktları `workspace/` altında yaşar.** Repo
kökü yalnızca framework dosyalarını ve kullanıcı dokümanlarını (AGENTS.md,
README, proje_kapsami.md, org_chart.json vb.) barındırır.

| Konum | İçerik |
|---|---|
| `workspace/studio.db` | Tek doğruluk kaynağı (pano, talepler, kota, audit) |
| `workspace/logs/` | pipeline.log ve diğer süreç logları |
| `workspace/.trace/` | Çağrı izleri (current.json, index.jsonl, NNNN.json) |
| `workspace/.control/` | Kontrol bayrakları (pause/stop/skip/...) |
| `workspace/docs/` | Üretilen dokümanlar, çözüm planları, talep raporları |
| `workspace/src/` | Üretilen proje kaynak kodu |

Kurallar:
- Yeni runtime/geçici dosya eklerken köke değil `workspace/` (veya uygun alt
  dizinine) yazın; `.gitignore` gerektirmemesi için kökte artefakt bırakmayın.
- Kökte `studio.db` bulunursa `studio_board.db_conn()` ilk bağlantıda
  otomatik olarak `workspace/` altına taşır (tek seferlik migrasyon).
- `.studio-version` tek istisnadır: hangi framework sürümünün kurulu
  olduğunu gösteren kökteki provensans dosyasıdır ve commit'lenir.

---

## 🏷️ Versiyonlama & Release

Ana dala (`main`/`master`) yapılan her merge'de GitHub Actions
(`.github/workflows/release.yml`) otomatik olarak `studio.version` sürümünü
yükseltir, changelog'a merge mesajını düşer ve `vX.Y.Z` tag'i atar:

- `feat:`/`feature:` önekli merge → **minor**, `BREAKING`/`!:` → **major**,
  diğerleri → **patch**
- Release commit'i `chore(release): vX.Y.Z [skip ci]` ile atılır ve yeniden
  tetiklenmez (döngü koruması)
- Projelerdeki `framework_update_info()` bu sürüm değişimini görüp kullanıcıya
  güncelleme bildirimi gösterir — tag/sürüm disiplini bildirim sisteminin
  tetikleyicisidir, elle `studio.version` düzenlenmesi gerekmez.
