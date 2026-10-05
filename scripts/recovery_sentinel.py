#!/usr/bin/env python3
"""
scripts/recovery_sentinel.py
Digital Software Studio — Süreç, Kurtarma ve Dağıtım Nöbetçisi Ajanı (Recovery & Sentinel Agent)

Bu ajan, stüdyo açılırken veya çalışma sırasında:
1. "İşler yarım kaldı mı?" denetimi yapar: Çöken/yarım kalan görevleri (RUNNING, FAILED, BLOCKED) tespit edip kurtarır.
2. "Deploy yarım kaldı mı?" denetimi yapar: Yerelde yapılmış ancak commit edilmemiş veya origin/master'a
   pushlanmamış değişiklikleri tespit eder.
3. Bekleyen deploy varsa otonom olarak paketler, commit eder ve origin/master'a pushlayarak
   GitHub Actions CI/CD dağıtımını tetikler.
4. "Yarım kalan işler ve deploy tamamlandı" raporunu verip stüdyonun olağan akışına devam etmesini sağlar.
"""

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

try:
    import studio_board as B
except ImportError:
    B = None

try:
    import musteri_talepleri as MT
except ImportError:
    MT = None

try:
    import github_issue_bridge as GH
except ImportError:
    GH = None

try:
    import kalite_kapilari as KK
except ImportError:
    KK = None


class RecoverySentinelAgent:
    """Süreç ve Dağıtım Kurtarma Ajanı"""

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.root = ROOT

    def log(self, icon: str, msg: str):
        if self.verbose:
            print(f"  {icon} [🛡️ KURTARMA AJANI] {msg}")

    def git_durumu_incele(self) -> dict:
        """Git çalışma alanı ve uzak dal senkronizasyonunu analiz eder."""
        durum = {
            "uncommitted": False,
            "degisen_dosya_sayisi": 0,
            "unpushed_commits": 0,
            "degisenler_ozet": [],
            "aktif_dal": "master"
        }

        try:
            # 1. Değişen/eklenen yerel dosyalar
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.root, capture_output=True, text=True, timeout=10
            )
            satirlar = [l.strip() for l in status.stdout.splitlines() if l.strip()]
            if satirlar:
                durum["uncommitted"] = True
                durum["degisen_dosya_sayisi"] = len(satirlar)
                durum["degisenler_ozet"] = satirlar[:10]

            # 2. Uzak repo ile commit farkı (ahead)
            try:
                subprocess.run(
                    ["git", "fetch", "origin", "master", "--quiet"],
                    cwd=self.root, capture_output=True, text=True, timeout=8
                )
            except Exception:
                pass

            ahead_res = subprocess.run(
                ["git", "rev-list", "--count", "origin/master..HEAD"],
                cwd=self.root, capture_output=True, text=True, timeout=8
            )
            count_str = ahead_res.stdout.strip()
            if count_str.isdigit():
                durum["unpushed_commits"] = int(count_str)

        except Exception as e:
            durum["hata"] = str(e)

        return durum

    def pano_yarim_isleri_incele(self) -> dict:
        """Panodaki (studio.db) yarım kalmış, çökmüş veya takılmış görevleri analiz eder."""
        rapor = {
            "yetim_running": [],
            "failed_tasks": [],
            "blocked_tasks": [],
            "toplam_yarim": 0
        }
        if not B:
            return rapor

        try:
            board = B.load()
            for s in board.get("sprints", []):
                for t in s.get("tasks", []):
                    st = t.get("status")
                    if st == "RUNNING":
                        rapor["yetim_running"].append(t["id"])
                    elif st == "FAILED":
                        rapor["failed_tasks"].append(t["id"])
                    elif st == "BLOCKED":
                        rapor["blocked_tasks"].append(t["id"])
            rapor["toplam_yarim"] = len(rapor["yetim_running"]) + len(rapor["failed_tasks"]) + len(rapor["blocked_tasks"])
        except Exception:
            pass

        return rapor

    def _talep_ac_deploy(self, branch: str, hata: str):
        """Push/deploy başarısızlığını müşteri talebi olarak havuza düşürür.

        Mükerrer koruması: açık bir [DEPLOY] talebi varken yenisi açılmaz.
        """
        if not MT:
            return
        try:
            data = MT.load_data()
            for t in data.get("talepler", []):
                if (t.get("baslik") or "").startswith("[DEPLOY]") \
                        and t.get("durum") not in ("COZULDU", "IPTAL"):
                    return
            yeni = MT.yeni_talep(
                "HATA",
                f"[DEPLOY] origin/{branch} push başarısız — deploy yarım kaldı",
                "Kurtarma ajanı yerel değişiklikleri uzak depoya gönderemedi.\n\n"
                f"```\n{hata[:700]}\n```\n\n"
                "Olası nedenler: uzak dalda yeni commitler (rebase denemesi de "
                "başarısız olduysa elle çakışma çözümü gerekir), yetki sorunu "
                "veya ağ hatası.",
                oncelik="YUKSEK", sayfa_url="/")
            self.log("📥", f"Deploy hatası {yeni['id']} talebi olarak havuza düşürüldü.")
        except Exception:
            pass

    def denetle_ci_cd_deploy(self) -> dict:
        """GitHub Actions üzerindeki son deploy durumunu sorgular.
        Deploy hatası varsa otomatik olarak [DEPLOY-CI/CD] talebi açar.
        """
        sonuc = {"durum": "BILINMIYOR", "run_id": None, "hata": None}
        try:
            cmd = ["gh", "run", "list", "--limit", "5", "--json",
                   "databaseId,status,conclusion,workflowName,headSha,url,createdAt"]
            res = subprocess.run(cmd, cwd=self.root, capture_output=True, text=True, timeout=20)
            if res.returncode != 0:
                return sonuc
            runs = json.loads(res.stdout)
            deploy_runs = [r for r in runs if "deploy" in (r.get("workflowName") or "").lower()]
            if not deploy_runs:
                return sonuc
            son_run = deploy_runs[0]
            run_id = son_run.get("databaseId")
            status = son_run.get("status")
            conclusion = son_run.get("conclusion")
            sonuc["run_id"] = run_id
            sonuc["status"] = status
            sonuc["conclusion"] = conclusion

            if status in ("in_progress", "queued"):
                sonuc["durum"] = "CALISIYOR"
                self.log("⏳", f"Canlı dağıtım (CI/CD) GitHub Actions üzerinde devam ediyor (Run ID: {run_id}).")
            elif conclusion == "success":
                sonuc["durum"] = "BASARILI"
                self.log("✅", f"Canlı dağıtım (CI/CD) BAŞARILI! Sürüm canlı ortamda aktif (Run ID: {run_id}).")
                self._coz_deploy_talepleri()
            elif conclusion in ("failure", "timed_out", "cancelled"):
                sonuc["durum"] = "BASARISIZ"
                log_cmd = ["gh", "run", "view", str(run_id), "--log-failed"]
                log_res = subprocess.run(log_cmd, cwd=self.root, capture_output=True, text=True, timeout=30)
                hata_log = log_res.stdout or log_res.stderr or "Hata detayı alınamadı"
                sonuc["hata"] = hata_log[:1500]
                self.log("❌", f"Canlı dağıtım (CI/CD) BAŞARISIZ! (Run ID: {run_id})")
                self._talep_ac_deploy_ci_cd(run_id, son_run.get("workflowName", "Deploy"), hata_log)
        except Exception as e:
            self.log("ℹ️", f"CI/CD deploy durumu kontrol edilemedi: {e}")
        return sonuc

    def _coz_deploy_talepleri(self):
        """Açık kalan [DEPLOY] taleplerini COZULDU olarak günceller."""
        if not MT:
            return
        try:
            data = MT.load_data()
            for t in data.get("talepler", []):
                if (t.get("baslik") or "").startswith(("[DEPLOY]", "[DEPLOY-CI/CD]")) and t.get("durum") not in ("COZULDU", "IPTAL"):
                    MT.guncelle(t["id"], durum="COZULDU",
                                studio_notu="CI/CD dağıtımı başarıyla tamamlandı, canlı sistem devrede.")
                    self.log("✓", f"Eski deploy hatası {t['id']} başarıyla kapatıldı.")
        except Exception:
            pass

    def _talep_ac_deploy_ci_cd(self, run_id: int, workflow: str, hata: str):
        """CI/CD deploy başarısızlığını acil müşteri talebi olarak havuza düşürür."""
        if not MT:
            return
        try:
            data = MT.load_data()
            for t in data.get("talepler", []):
                if f"Run #{run_id}" in (t.get("aciklama") or "") and t.get("durum") not in ("COZULDU", "IPTAL"):
                    return
                if (t.get("baslik") or "").startswith("[DEPLOY-CI/CD]") and t.get("durum") not in ("COZULDU", "IPTAL"):
                    return
            yeni = MT.yeni_talep(
                "HATA",
                f"[DEPLOY-CI/CD] GitHub Actions canlı dağıtımı başarısız oldu (Run #{run_id})",
                f"GitHub Actions '{workflow}' iş akışı canlıya dağıtım yaparken çöktü.\n\n"
                f"**Run ID:** {run_id}\n\n"
                f"**Başarısız Olan Adım Logları:**\n```\n{hata[:1200]}\n```\n\n"
                "Ajanların bu hatayı inceleyip workflow veya kaynak kodundaki derleme/dağıtım sorununu çözmesi gerekmektedir.",
                oncelik="ACIL", sayfa_url="/"
            )
            self.log("🚨", f"CI/CD Deploy arızası {yeni['id']} talebi olarak havuza düşürüldü!")
        except Exception as e:
            self.log("⚠️", f"Deploy talebi oluşturulurken hata: {e}")

    def bekleyen_talepleri_incele(self) -> list:
        """Çözülmüş ancak henüz yayına girmemiş müşteri taleplerini tespit eder."""
        bekleyenler = []
        if not MT:
            return bekleyenler

        try:
            data = MT.load_data()
            cozulenler = [t for t in data.get("talepler", []) if t.get("durum") == "COZULDU"]

            # Git log'da son commitlere bak
            son_log = subprocess.run(
                ["git", "log", "-n", "10", "--oneline"],
                cwd=self.root, capture_output=True, text=True
            ).stdout.lower()

            for t in cozulenler:
                tid = t["id"].lower()
                if tid not in son_log:
                    bekleyenler.append(t)
        except Exception:
            pass

        return bekleyenler

    def denetle_ve_kurtar(self, oto_push: bool = True) -> bool:
        """
        Ana denetim ve kurtarma akışı.
        Yarım kalan işleri ve deployları tespit eder, eksikleri tamamlar.
        """
        print("\n" + "═"*65)
        print(" 🛡️  [SÜREÇ & DAĞITIM NÖBETÇİSİ AJANI] Sistem Sağlık ve Kurtarma Taraması")
        print("═"*65)

        git_durumu = self.git_durumu_incele()
        pano_durumu = self.pano_yarim_isleri_incele()
        bekleyen_talepler = self.bekleyen_talepleri_incele()
        ci_cd_bilgi = self.denetle_ci_cd_deploy()

        yarim_is_var = pano_durumu["toplam_yarim"] > 0
        deploy_yarim = git_durumu["uncommitted"] or (git_durumu["unpushed_commits"] > 0)
        ci_cd_hatali = ci_cd_bilgi.get("durum") == "BASARISIZ"

        # Durum 1: Hiçbir yarım iş yok, her şey güncel
        if not yarim_is_var and not deploy_yarim and not ci_cd_hatali:
            self.log("✅", "Harika! Sistemde yarım kalmış iş veya bekleyen deploy bulunmuyor.")
            self.log("ℹ️", "Tüm görevler tutarlı, yerel kod tabanı origin/master ile tam senkronize.")
            print("═"*65 + "\n")
            return True

        # Durum 2: Yarım işler veya deploy tespit edildi
        print()
        if yarim_is_var:
            self.log("⚠️", f"DİKKAT: Önceki oturumdan kalan {pano_durumu['toplam_yarim']} adet yarım/çökmüş görev tespit edildi!")
            if pano_durumu["yetim_running"]:
                print(f"      • Yarım kalan (RUNNING): {', '.join(pano_durumu['yetim_running'])}")
            if pano_durumu["failed_tasks"]:
                print(f"      • Hata veren (FAILED) : {', '.join(pano_durumu['failed_tasks'])}")
            if pano_durumu["blocked_tasks"]:
                print(f"      • Takılan (BLOCKED)   : {', '.join(pano_durumu['blocked_tasks'])}")

        if deploy_yarim:
            self.log("🚨", "DİKKAT: Deploy yarım kalmış! Yapılan son değişiklikler canlıya henüz aktarılmamış!")
            if git_durumu["uncommitted"]:
                print(f"      • {git_durumu['degisen_dosya_sayisi']} adet dosya commit bekliyor (yerelde yapıldı, depoya işlenmedi).")
            if git_durumu["unpushed_commits"] > 0:
                print(f"      • {git_durumu['unpushed_commits']} adet yerel commit henüz GitHub origin/master'a pushlanmadı.")
            if bekleyen_talepler:
                talep_ozet = ", ".join([f"{t['id']} ({t.get('baslik', '')[:30]}...)" for t in bekleyen_talepler])
                print(f"      • Yayına girmeyi bekleyen çözülmüş talepler: {talep_ozet}")

        # OTOMATİK KURTARMA VE TAMAMLAMA ADIMLARI
        print()
        self.log("🔧", "Kurtarma ve tamamlama operasyonu başlatılıyor...")

        # 1. Pano görevlerini kurtar
        if yarim_is_var and B:
            try:
                board = B.load()
                kurtarilan = 0
                if B.recover_orphans(board):
                    kurtarilan += len(pano_durumu["yetim_running"])
                for s in board.get("sprints", []):
                    for t in s.get("tasks", []):
                        if t.get("status") in ("FAILED", "BLOCKED"):
                            t["status"] = "TODO"
                            t["attempts"] = 0
                            t["note"] = "[Kurtarma Ajanı] Otomatik olarak sıraya alındı"
                            kurtarilan += 1
                B.normalize(board)
                B.refresh(board)
                B.save(board)
                self.log("✓", f"Yarım kalan {kurtarilan} adet görev temizlendi ve yeniden TODO sırasına alındı.")
            except Exception as e:
                self.log("⚠️", f"Pano kurtarma sırasında uyarı: {e}")

        # 2. Deploy'u tamamla ve canlıya gönder
        hepsi_temiz = True
        if deploy_yarim and oto_push:
            try:
                # Çalışma alanına sızan artefaktlar deploy'a karışmasın:
                # kırık symlink'ler silinir, kalan bulgular stage dışı tutulur.
                sizinti_yollar = []
                if KK:
                    try:
                        temiz, sizinti_yollar = KK.calisma_alani_hijyeni()
                        if temiz:
                            self.log("🧹", f"{len(temiz)} kırık symlink otomatik temizlendi: "
                                          f"{', '.join(temiz[:4])}")
                        for yol in sizinti_yollar:
                            self.log("⚠️", f"Sızan artefakt commit dışında tutulacak: {yol}")
                    except Exception:
                        sizinti_yollar = []

                # Uncommitted dosyaları commit et
                if git_durumu["uncommitted"]:
                    self.log("📦", "Değiştirilen tüm dosyalar paketleniyor (git add -A)...")
                    subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)
                    for yol in sizinti_yollar:
                        subprocess.run(
                            ["git", "reset", "-q", "--", yol],
                            cwd=self.root, capture_output=True)

                    # Anlamlı commit mesajı oluştur
                    if bekleyen_talepler:
                        tids = [t["id"] for t in bekleyen_talepler]
                        closes_refs = [f"closes #{t['github_issue_number']}" for t in bekleyen_talepler if t.get("github_issue_number")]
                        closes_str = f" ({', '.join(closes_refs)})" if closes_refs else ""
                        commit_msg = f"fix(failover-deploy): yarım kalan talepler ve sistem güncellemeleri yayına alındı [{', '.join(tids)}]{closes_str}"
                    else:
                        commit_msg = f"fix(failover-deploy): yarım kalan son değişiklikler otomatik yayına alındı ({datetime.now().strftime('%Y-%m-%d %H:%M')})"

                    commit_res = subprocess.run(
                        ["git", "commit", "-m", commit_msg],
                        cwd=self.root, capture_output=True, text=True
                    )
                    if commit_res.returncode == 0:
                        self.log("✓", f"Değişiklikler commit edildi: '{commit_msg}'")
                    else:
                        self.log("ℹ️", f"Commit detayı: {commit_res.stdout.strip() or commit_res.stderr.strip()}")

                # Aktif branch'e pushla
                branch_cmd = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=self.root, capture_output=True, text=True
                )
                branch = branch_cmd.stdout.strip() if branch_cmd.returncode == 0 else "main"
                if not branch or branch == "HEAD":
                    branch = "main"

                self.log("🚀", f"origin/{branch} dalına pushlanıyor (CI/CD tetikleniyor)...")
                push_ok, son_hata = False, ""
                for deneme in (1, 2):
                    push_res = subprocess.run(
                        ["git", "push", "origin", branch],
                        cwd=self.root, capture_output=True, text=True, timeout=60
                    )
                    if push_res.returncode == 0:
                        push_ok = True
                        break
                    son_hata = (push_res.stderr or push_res.stdout or "").strip()
                    nff = any(k in son_hata for k in
                              ("non-fast-forward", "fetch first", "rejected"))
                    if deneme == 1 and nff:
                        self.log("🔄", "Push reddedildi (non-fast-forward) — uzak "
                                      "değişiklikler rebase ile alınıp yeniden denenecek...")
                        pull = subprocess.run(
                            ["git", "pull", "--rebase", "origin", branch],
                            cwd=self.root, capture_output=True, text=True, timeout=90)
                        if pull.returncode != 0:
                            subprocess.run(["git", "rebase", "--abort"],
                                           cwd=self.root, capture_output=True)
                            self.log("⚠️", f"Rebase başarısız (çakışma geri alındı): "
                                          f"{(pull.stderr or pull.stdout or '').strip()[:160]}")
                            break
                        continue
                    break
                if push_ok:
                    self.log("🎉", f"BAŞARILI! Tüm yarım kalan değişiklikler GitHub origin/{branch} dalına aktarıldı.")
                    self.log("🚀", "GitHub Actions CI/CD pipeline'ı devreye girdi ve otomatik canlı dağıtımı tetiklendi!")
                    try:
                        time.sleep(3)
                        self.denetle_ci_cd_deploy()
                    except Exception:
                        pass
                else:
                    hepsi_temiz = False
                    self.log("❌", f"PUSH BAŞARISIZ — değişiklikler origin/{branch} dalına ulaşmadı:")
                    print(f"      {son_hata[:240]}")
                    self._talep_ac_deploy(branch, son_hata)

            except Exception as e:
                hepsi_temiz = False
                self.log("❌", f"Otomatik deploy tamamlama sırasında hata oluştu: {e}")

        print("═"*65)
        if hepsi_temiz:
            self.log("🏁", "Kurtarma Ajanı denetimini tamamladı. Sistem artık temiz ve stüdyo akışına hazır.")
        else:
            self.log("⚠️", "Kurtarma TAMAMLANAMADI — deploy hâlâ yarım. "
                          "Yukarıdaki hatalar giderilmeden sistem temiz sayılmaz.")
        print("═"*65 + "\n")
        return hepsi_temiz


def main():
    agent = RecoverySentinelAgent(verbose=True)
    temiz = agent.denetle_ve_kurtar(oto_push=True)
    sys.exit(0 if temiz else 1)


if __name__ == "__main__":
    main()
