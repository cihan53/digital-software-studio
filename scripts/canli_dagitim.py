#!/usr/bin/env python3
"""
scripts/canli_dagitim.py
Digital Software Studio — Web Panelinden Canlıya Dağıtım (Deploy) ve GitHub Issue Yönetimi

Web panelinden veya CLI'dan tek tıkla:
1. Onaylanmış tüm işleri ana dala (master/main) birleştirip (merge) canlıya gönderme,
2. Yalnızca belirli bir tamamlanmış talebe ait commit'leri seçici (cherry-pick) canlıya aktarma,
3. Stüdyoda çözülmüş fakat GitHub'da açık kalmış Issue'ları senkronize edip kapatma.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def ana_dal_bul(cwd: Path | None = None) -> str:
    """Projenin ana dalını (master veya main) tespit eder."""
    work_dir = cwd or ROOT
    try:
        r_master = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", "refs/heads/master"],
            cwd=str(work_dir)
        )
        if r_master.returncode == 0:
            r_main = subprocess.run(
                ["git", "show-ref", "--verify", "--quiet", "refs/heads/main"],
                cwd=str(work_dir)
            )
            if r_main.returncode != 0:
                return "master"

        r_origin_master = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", "refs/remotes/origin/master"],
            cwd=str(work_dir)
        )
        if r_origin_master.returncode == 0:
            r_origin_main = subprocess.run(
                ["git", "show-ref", "--verify", "--quiet", "refs/remotes/origin/main"],
                cwd=str(work_dir)
            )
            if r_origin_main.returncode != 0:
                return "master"
    except Exception:
        pass
    return "main"


def mevcut_dal_bul(cwd: Path | None = None) -> str:
    """Aktif git dalını döndürür."""
    work_dir = cwd or ROOT
    try:
        res = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            cwd=str(work_dir)
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return os.getenv("STUDIO_GIT_BRANCH", "studio/calisma")


def _calisma_dizinini_guvenceye_al(work_dir: Path) -> bool:
    """İzlenen dosyalarda uncommitted değişiklik varsa stash yapar."""
    try:
        st = subprocess.run(
            ["git", "status", "--porcelain", "-uno"],
            capture_output=True,
            text=True,
            cwd=str(work_dir)
        )
        if st.returncode == 0 and st.stdout.strip():
            stash_res = subprocess.run(
                ["git", "stash", "push", "-m", "studio_canli_dagitim_auto_stash"],
                capture_output=True,
                text=True,
                cwd=str(work_dir)
            )
            return stash_res.returncode == 0 and "No local changes to save" not in stash_res.stdout
    except Exception:
        pass
    return False


def _calisma_dizinini_geri_yukle(work_dir: Path):
    """Varsa auto-stash kaydını geri yükler."""
    try:
        subprocess.run(
            ["git", "stash", "pop"],
            capture_output=True,
            text=True,
            cwd=str(work_dir)
        )
    except Exception:
        pass


def canliya_dagit_hepsi(cwd: Path | None = None) -> dict:
    """studio/calisma dalındaki tüm onaylı işleri ana dala merge edip push eder."""
    work_dir = cwd or ROOT
    ana_dal = ana_dal_bul(work_dir)
    calisma_dali = os.getenv("STUDIO_GIT_BRANCH", "studio/calisma")
    if calisma_dali == ana_dal:
        calisma_dali = "studio/calisma"

    stashed = _calisma_dizinini_guvenceye_al(work_dir)

    try:
        # 1. Ana dala geç
        c1 = subprocess.run(["git", "checkout", ana_dal], capture_output=True, text=True, cwd=str(work_dir))
        if c1.returncode != 0:
            return {"ok": False, "mesaj": f"'{ana_dal}' dalına geçilemedi: {c1.stderr.strip()}"}

        # 2. Remote'dan son hali çek
        subprocess.run(["git", "pull", "--ff-only", "origin", ana_dal], capture_output=True, text=True, cwd=str(work_dir))

        # 3. Çalışma dalını merge et
        merge_msg = f"merge: {calisma_dali} canlıya dağıtıldı (onaylandı)"
        c3 = subprocess.run(
            ["git", "merge", "--no-ff", "-X", "theirs", calisma_dali, "-m", merge_msg],
            capture_output=True,
            text=True,
            cwd=str(work_dir)
        )
        if c3.returncode != 0:
            subprocess.run(["git", "merge", "--abort"], capture_output=True, text=True, cwd=str(work_dir))
            return {"ok": False, "mesaj": f"Merge başarısız: {c3.stderr.strip()}"}

        # 4. Remote'a push et
        c4 = subprocess.run(["git", "push", "origin", ana_dal], capture_output=True, text=True, cwd=str(work_dir))
        if c4.returncode != 0:
            return {"ok": False, "mesaj": f"'{ana_dal}' remote'a push edilemedi: {c4.stderr.strip()}"}

        # 5. İlgili açık GitHub Issue'larını kapat/eşitle
        issue_sonuc = issuelari_kapat(work_dir)

        return {
            "ok": True,
            "mesaj": f"Tüm işler başarıyla '{ana_dal}' dalına birleştirildi ve canlı dağıtım başlatıldı.",
            "ana_dal": ana_dal,
            "kapatilan_issuelar": issue_sonuc.get("kapatilanlar", [])
        }
    finally:
        # Çalışma dalına geri dön
        subprocess.run(["git", "checkout", "-q", calisma_dali], capture_output=True, text=True, cwd=str(work_dir))
        if stashed:
            _calisma_dizinini_geri_yukle(work_dir)


def canliya_dagit_tekil(talep_id: str, cwd: Path | None = None) -> dict:
    """Yalnızca belirtilen talebe ait commit'leri ana dala cherry-pick ile aktarır."""
    if not talep_id:
        return {"ok": False, "mesaj": "Talep ID belirtilmedi."}

    work_dir = cwd or ROOT
    ana_dal = ana_dal_bul(work_dir)
    calisma_dali = os.getenv("STUDIO_GIT_BRANCH", "studio/calisma")
    if calisma_dali == ana_dal:
        calisma_dali = "studio/calisma"

    tid = talep_id.strip().upper()
    num_match = re.search(r"\d+", tid)
    num_str = num_match.group(0) if num_match else ""

    # Çalışma dalında olup ana dalda olmayan, bu talebe ait commit'leri bul
    # (Örnek başlıklar: TALEP-014, talep-014, #254)
    log_cmd = [
        "git", "log", f"{ana_dal}..{calisma_dali}",
        "--grep", tid,
        "-i",
        "--reverse",
        "--format=%H"
    ]
    res = subprocess.run(log_cmd, capture_output=True, text=True, cwd=str(work_dir))
    commits = [c.strip() for c in res.stdout.splitlines() if c.strip()]

    # Alternatif regex arama (örn. "fix(talep-14)" veya "closes #...")
    if not commits and num_str:
        log_cmd2 = [
            "git", "log", f"{ana_dal}..{calisma_dali}",
            "--grep", f"talep-{int(num_str)}",
            "-i",
            "--reverse",
            "--format=%H"
        ]
        res2 = subprocess.run(log_cmd2, capture_output=True, text=True, cwd=str(work_dir))
        commits = [c.strip() for c in res2.stdout.splitlines() if c.strip()]

    if not commits:
        return {
            "ok": False,
            "mesaj": f"{tid} için '{calisma_dali}' dalında ana dala aktarılacak yeni bir commit bulunamadı. "
                     f"(Zaten canlıda olabilir veya doğrudan commit mesajında yer almamış olabilir)."
        }

    stashed = _calisma_dizinini_guvenceye_al(work_dir)

    try:
        # 1. Ana dala geç
        c1 = subprocess.run(["git", "checkout", ana_dal], capture_output=True, text=True, cwd=str(work_dir))
        if c1.returncode != 0:
            return {"ok": False, "mesaj": f"'{ana_dal}' dalına geçilemedi: {c1.stderr.strip()}"}

        # 2. Remote güncelle
        subprocess.run(["git", "pull", "--ff-only", "origin", ana_dal], capture_output=True, text=True, cwd=str(work_dir))

        # 3. Cherry-pick adımları
        for c in commits:
            cp_res = subprocess.run(["git", "cherry-pick", c], capture_output=True, text=True, cwd=str(work_dir))
            if cp_res.returncode != 0:
                subprocess.run(["git", "cherry-pick", "--abort"], capture_output=True, text=True, cwd=str(work_dir))
                return {
                    "ok": False,
                    "mesaj": f"{tid} aktarılırken çakışma (conflict) oluştu (commit {c[:8]}). "
                             f"Bu talep önceki geliştirmelere bağımlı olabilir. Lütfen 'Tümünü Canlıya Dağıt' seçeneğini kullanın."
                }

        # 4. Remote'a push et
        c4 = subprocess.run(["git", "push", "origin", ana_dal], capture_output=True, text=True, cwd=str(work_dir))
        if c4.returncode != 0:
            return {"ok": False, "mesaj": f"'{ana_dal}' remote'a push edilemedi: {c4.stderr.strip()}"}

        # 5. Varsa talebin GitHub Issue'sunu kapat
        try:
            sys.path.insert(0, str(work_dir / "scripts"))
            import musteri_talepleri as MT
            import github_issue_bridge as GH
            t = MT.getir(tid, cwd=work_dir)
            if t and t.get("github_issue_number"):
                GH.github_issue_kapat(
                    t["github_issue_number"],
                    kapanis_notu=f"Tekil canlı dağıtım ile yayına alındı ({tid}).",
                    cwd=work_dir
                )
        except Exception:
            pass

        return {
            "ok": True,
            "mesaj": f"{tid} ({len(commits)} commit) başarıyla '{ana_dal}' dalına aktarıldı ve canlıya gönderildi.",
            "commits": [c[:8] for c in commits]
        }
    finally:
        subprocess.run(["git", "checkout", "-q", calisma_dali], capture_output=True, text=True, cwd=str(work_dir))
        if stashed:
            _calisma_dizinini_geri_yukle(work_dir)


def issuelari_kapat(cwd: Path | None = None) -> dict:
    """Stüdyoda çözülmüş (COZULDU) fakat GitHub'da açık kalmış Issue'ları senkronize eder."""
    work_dir = cwd or ROOT
    try:
        sys.path.insert(0, str(work_dir / "scripts"))
        import musteri_talepleri as MT
        import github_issue_bridge as GH
    except Exception as e:
        return {"ok": False, "mesaj": f"Modül yükleme hatası: {e}", "kapatilanlar": []}

    if not GH.gh_mevcut_mu():
        return {"ok": False, "mesaj": "GitHub CLI ('gh') oturumu bulunamadı.", "kapatilanlar": []}

    try:
        # GitHub'daki açık issue numaralarını listele
        res = subprocess.run(
            ["gh", "issue", "list", "--state", "open", "--json", "number"],
            capture_output=True,
            text=True,
            cwd=str(work_dir),
            timeout=10
        )
        if res.returncode != 0:
            return {"ok": False, "mesaj": f"GitHub issue listesi alınamadı: {res.stderr.strip()}", "kapatilanlar": []}

        acik_numaralar = {item["number"] for item in json.loads(res.stdout or "[]") if "number" in item}
    except Exception as e:
        return {"ok": False, "mesaj": f"GitHub API hatası: {e}", "kapatilanlar": []}

    # DB'den çözülmüş talepleri çek
    cozulen_talepler = [
        t for t in MT.db_tum_talepler()
        if t.get("durum") == "COZULDU" and t.get("github_issue_number")
    ]

    kapatilanlar = []
    for t in cozulen_talepler:
        iss_no = t.get("github_issue_number")
        if iss_no in acik_numaralar:
            ok = GH.github_issue_kapat(
                iss_no,
                kapanis_notu=f"Digital Software Studio: Müşteri onayı ile çözüldü ve kapatıldı ({t.get('id')}).",
                cwd=work_dir
            )
            if ok:
                kapatilanlar.append(iss_no)

    if kapatilanlar:
        return {
            "ok": True,
            "mesaj": f"{len(kapatilanlar)} adet açık GitHub Issue başarıyla senkronize edilip kapatıldı: " +
                     ", ".join(f"#{n}" for n in kapatilanlar),
            "kapatilanlar": kapatilanlar
        }
    return {
        "ok": True,
        "mesaj": "Tüm çözülmüş taleplerin GitHub Issue'ları zaten senkronize ve kapalı durumda.",
        "kapatilanlar": []
    }


def main():
    parser = argparse.ArgumentParser(description="Canlı Dağıtım ve GitHub Issue Yönetimi")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--hepsi", action="store_true", help="Tüm onaylı işleri ana dala birleştir ve canlıya gönder")
    group.add_argument("--tekil", metavar="TALEP_ID", help="Yalnızca belirtilen talebi ana dala cherry-pick ile canlıya gönder")
    group.add_argument("--issuelari-kapat", action="store_true", help="Çözülmüş taleplerin GitHub issue'larını kapat")

    args = parser.parse_args()

    if args.hepsi:
        res = canliya_dagit_hepsi()
        print(("✓ " if res["ok"] else "✗ ") + res["mesaj"])
        sys.exit(0 if res["ok"] else 1)
    elif args.tekil:
        res = canliya_dagit_tekil(args.tekil)
        print(("✓ " if res["ok"] else "✗ ") + res["mesaj"])
        sys.exit(0 if res["ok"] else 1)
    elif args.issuelari_kapat:
        res = issuelari_kapat()
        print(("✓ " if res["ok"] else "✗ ") + res["mesaj"])
        sys.exit(0 if res["ok"] else 1)


if __name__ == "__main__":
    main()
