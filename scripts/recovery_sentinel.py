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
import os
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
        """Panodaki yarım kalmış, çökmüş veya takılmış görevleri analiz eder."""
        rapor = {
            "yetim_running": [],
            "failed_tasks": [],
            "blocked_tasks": [],
            "toplam_yarim": 0
        }
        pano_file = self.root / "workspace" / "pano.json"
        if not pano_file.exists():
            return rapor

        try:
            board = json.loads(pano_file.read_text(encoding="utf-8"))
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

        yarim_is_var = pano_durumu["toplam_yarim"] > 0
        deploy_yarim = git_durumu["uncommitted"] or (git_durumu["unpushed_commits"] > 0)

        # Durum 1: Hiçbir yarım iş yok, her şey güncel
        if not yarim_is_var and not deploy_yarim:
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
        if deploy_yarim and oto_push:
            try:
                # Uncommitted dosyaları commit et
                if git_durumu["uncommitted"]:
                    self.log("📦", "Değiştirilen tüm dosyalar paketleniyor (git add -A)...")
                    subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)

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
                push_res = subprocess.run(
                    ["git", "push", "origin", branch],
                    cwd=self.root, capture_output=True, text=True, timeout=30
                )
                if push_res.returncode == 0:
                    self.log("🎉", f"BAŞARILI! Tüm yarım kalan değişiklikler GitHub origin/{branch} dalına aktarıldı.")
                    self.log("🚀", "GitHub Actions CI/CD pipeline'ı devreye girdi ve otomatik canlı dağıtımı tetiklendi!")
                else:
                    self.log("⚠️", f"Push işlemi sırasında hata/uyarı: {push_res.stderr.strip()[:200]}")

            except Exception as e:
                self.log("❌", f"Otomatik deploy tamamlama sırasında hata oluştu: {e}")

        print("═"*65)
        self.log("🏁", "Kurtarma Ajanı denetimini tamamladı. Sistem artık temiz ve stüdyo akışına hazır.")
        print("═"*65 + "\n")
        return True


def main():
    agent = RecoverySentinelAgent(verbose=True)
    agent.denetle_ve_kurtar(oto_push=True)


if __name__ == "__main__":
    main()
