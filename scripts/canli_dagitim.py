#!/usr/bin/env python3
"""
scripts/canli_dagitim.py
Digital Software Studio — İzole Dal (bug/feature) Yaşam Döngüsü, Canlıya Dağıtım ve GitHub Issue Yönetimi

İş Akışı:
1. Görev veya talep başladığında güncel ana daldan (master/main) izole dal açılır (bug/<N> veya feature/<N>).
2. Geliştirme ve UAT doğrulaması izole dal üzerinde yapılır.
3. Onay alındığında dal ana dala birleştirilir (merge), push edilir ve dal temizlenir.
4. Granüler dağıtım ile Web & Backend ve Mobil bağımsız tetiklenebilir.
"""

import argparse
import json
import os
import re
import shutil
import sqlite3
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


def gorev_dali_adi(task_or_talep: dict | str, cwd: Path | None = None) -> str:
    """Görev veya talep için standart izole dal adı (bug/<N> veya feature/<N>) belirler.
    
    Örnekler:
      - GitHub Issue #261 (HATA) -> bug/261
      - GitHub Issue #262 (GELISTIRME) -> feature/262
      - TALEP-018 (HATA, issue yoksa) -> bug/18
      - S16-T2 (Sprint görevi) -> feature/s16-t2
    """
    work_dir = cwd or ROOT
    if isinstance(task_or_talep, str):
        tid = task_or_talep.strip()
        if tid.startswith(("bug/", "feature/", "task/")):
            return tid
        try:
            sys.path.insert(0, str(work_dir / "scripts"))
            import musteri_talepleri as MT
            t = MT.getir(tid, cwd=work_dir)
            if t:
                return gorev_dali_adi(t, cwd=work_dir)
        except Exception:
            pass

        # Pano görevi ID'si ise (örn. S52-T1) studio.db'den ilişkili talep_id'sini bul
        try:
            db_f = work_dir / "workspace" / "studio.db"
            if not db_f.exists():
                db_f = work_dir / "studio.db"
            if db_f.exists():
                conn = sqlite3.connect(str(db_f), timeout=5.0)
                cur = conn.cursor()
                row = cur.execute("SELECT talep_id, baslik FROM pano_gorevleri WHERE lower(id) = lower(?)", (tid,)).fetchone()
                conn.close()
                if row:
                    rel_talep_id = row[0]
                    if not rel_talep_id and row[1]:
                        m_t = re.search(r"\[(TALEP-\d+)\]", row[1], re.IGNORECASE)
                        if m_t:
                            rel_talep_id = m_t.group(1).upper()
                    if rel_talep_id:
                        import musteri_talepleri as MT
                        t_db = MT.getir(rel_talep_id, cwd=work_dir)
                        if t_db:
                            return gorev_dali_adi(t_db, cwd=work_dir)
        except Exception:
            pass

        num_m = re.search(r"\d+", tid)
        num = num_m.group(0) if num_m else tid.lower()
        return f"feature/{num}"

    t = task_or_talep
    # 1. Eğer task içinde talep_id varsa veya başlığında [TALEP-XXX] geçiyorsa ilişkili talebi çek
    talep_id = t.get("talep_id")
    if not talep_id:
        text = f"{t.get('baslik', '')} {t.get('title', '')} {t.get('description', '')}"
        m_t = re.search(r"\[(TALEP-\d+)\]", text, re.IGNORECASE)
        if m_t:
            talep_id = m_t.group(1).upper()

    if talep_id:
        try:
            sys.path.insert(0, str(work_dir / "scripts"))
            import musteri_talepleri as MT
            talep = MT.getir(talep_id, cwd=work_dir)
            if talep:
                return gorev_dali_adi(talep, cwd=work_dir)
        except Exception:
            pass

    # 2. GitHub issue numarası varsa
    issue_no = t.get("github_issue_number")
    if not issue_no:
        text = f"{t.get('baslik', '')} {t.get('title', '')} {t.get('description', '')}"
        m = re.search(r"#(\d+)", text)
        if m:
            issue_no = m.group(1)

    tur = str(t.get("tur", "")).upper()
    baslik = str(t.get("baslik") or t.get("title") or "").lower()
    is_bug = tur in ("HATA", "BUG") or any(k in baslik for k in ("hata", "bug", "fix", "düzelt", "onar"))
    prefix = "bug" if is_bug else "feature"

    if issue_no:
        return f"{prefix}/{issue_no}"

    tid_raw = str(t.get("id") or t.get("talep_id") or "")
    num_m = re.search(r"\d+", tid_raw)
    if num_m and tid_raw.upper().startswith("TALEP"):
        return f"{prefix}/{int(num_m.group(0))}"

    clean_id = re.sub(r"[^a-zA-Z0-9_-]", "-", str(t.get("id") or "task")).lower()
    return f"{prefix}/{clean_id}"


def talep_pr_olustur(task_or_talep: dict | str, cwd: Path | None = None) -> dict:
    """Talebin veya görevin izole dalı için GitHub PR açar veya mevcut PR linkini döner."""
    work_dir = cwd or ROOT
    ana_dal = ana_dal_bul(work_dir)
    dal_adi = gorev_dali_adi(task_or_talep, cwd=work_dir)

    if not shutil.which("gh"):
        return {"ok": False, "mesaj": "gh CLI kurulu değil."}

    # Dal yerelde veya remote'da var mı?
    dal_var = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{dal_adi}"],
        cwd=str(work_dir)
    ).returncode == 0
    if not dal_var:
        r_var = subprocess.run(
            ["git", "ls-remote", "--exit-code", "--heads", "origin", dal_adi],
            cwd=str(work_dir)
        ).returncode == 0
        if not r_var:
            return {"ok": False, "mesaj": f"'{dal_adi}' dalı bulunamadı."}

    # 1. Dalı origin'e pushla
    subprocess.run(["git", "push", "-u", "origin", dal_adi], capture_output=True, text=True, cwd=str(work_dir))

    # 2. Mevcut açık PR var mı kontrol et
    pr_chk = subprocess.run(
        ["gh", "pr", "list", "--head", dal_adi, "--json", "number,url,state"],
        capture_output=True, text=True, cwd=str(work_dir)
    )
    if pr_chk.returncode == 0 and pr_chk.stdout.strip():
        try:
            prs = json.loads(pr_chk.stdout.strip())
            for p in prs:
                if p.get("state") == "OPEN":
                    return {"ok": True, "pr_url": p.get("url"), "pr_number": p.get("number"), "mesaj": "PR zaten mevcut."}
        except Exception:
            pass

    # 3. PR başlığı ve açıklaması hazırla
    issue_no = None
    baslik = dal_adi
    aciklama = ""

    tid = ""
    if isinstance(task_or_talep, dict):
        tid = task_or_talep.get("talep_id") or task_or_talep.get("id") or ""
        baslik = task_or_talep.get("baslik") or task_or_talep.get("title") or dal_adi
    elif isinstance(task_or_talep, str):
        tid = task_or_talep

    try:
        sys.path.insert(0, str(work_dir / "scripts"))
        import musteri_talepleri as MT
        t = MT.getir(tid, cwd=work_dir)
        if t:
            issue_no = t.get("github_issue_number")
            baslik = t.get("baslik") or baslik
            aciklama = t.get("aciklama") or ""
    except Exception:
        pass

    if not issue_no:
        m = re.search(r"\d+", dal_adi)
        if m:
            issue_no = int(m.group(0))

    pr_title = baslik
    if issue_no and f"#{issue_no}" not in pr_title:
        pr_title = f"{pr_title} (#{issue_no})"

    prefix = "fix" if dal_adi.startswith("bug/") else "feat"
    if not pr_title.startswith(("fix", "feat", "chore", "refactor")):
        pr_title = f"{prefix}: {pr_title}"

    body = f"Closes #{issue_no}\n\n{aciklama}" if issue_no else aciklama or pr_title

    # 4. GitHub PR oluştur
    cmd = [
        "gh", "pr", "create",
        "--head", dal_adi,
        "--base", ana_dal,
        "--title", pr_title[:120],
        "--body", body
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(work_dir))
    if res.returncode == 0:
        url = res.stdout.strip()
        return {"ok": True, "pr_url": url, "mesaj": f"PR açıldı: {url}"}
    return {"ok": False, "mesaj": f"PR oluşturulamadı: {res.stderr.strip()}"}


def gorev_dali_hazirla(task_or_talep: dict | str, cwd: Path | None = None) -> dict:
    """Görev veya talep için master/main tabanlı izole dal açar veya mevcut dala geçer."""
    work_dir = cwd or ROOT
    ana_dal = ana_dal_bul(work_dir)
    dal_adi = gorev_dali_adi(task_or_talep, cwd=work_dir)

    stashed = _calisma_dizinini_guvenceye_al(work_dir)

    try:
        dal_var = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{dal_adi}"],
            cwd=str(work_dir)
        ).returncode == 0

        if dal_var:
            c = subprocess.run(["git", "checkout", dal_adi], capture_output=True, text=True, cwd=str(work_dir))
            if c.returncode != 0:
                return {"ok": False, "mesaj": f"'{dal_adi}' dalına geçilemedi: {c.stderr.strip()}", "dal": dal_adi}
        else:
            c_main = subprocess.run(["git", "checkout", ana_dal], capture_output=True, text=True, cwd=str(work_dir))
            if c_main.returncode == 0:
                subprocess.run(["git", "pull", "--ff-only", "origin", ana_dal], capture_output=True, text=True, cwd=str(work_dir))
            
            c_new = subprocess.run(["git", "checkout", "-b", dal_adi, ana_dal], capture_output=True, text=True, cwd=str(work_dir))
            if c_new.returncode != 0:
                return {"ok": False, "mesaj": f"'{dal_adi}' dalı oluşturulamadı: {c_new.stderr.strip()}", "dal": dal_adi}

        return {
            "ok": True,
            "mesaj": f"İzole dal '{dal_adi}' hazırlandı (taban: '{ana_dal}').",
            "dal": dal_adi,
            "ana_dal": ana_dal
        }
    finally:
        if stashed:
            _calisma_dizinini_geri_yukle(work_dir)


def gorev_dali_birlestir(dal_adi_veya_talep: str, issue_number: int | None = None, mesaj: str = "", cwd: Path | None = None) -> dict:
    """Tamamlanan izole dalı ana dala merge edip pushlar ve dalı yerel/uzaktan temizler."""
    work_dir = cwd or ROOT
    ana_dal = ana_dal_bul(work_dir)
    dal_adi = dal_adi_veya_talep if dal_adi_veya_talep.startswith(("bug/", "feature/", "task/")) else gorev_dali_adi(dal_adi_veya_talep, cwd=work_dir)

    stashed = _calisma_dizinini_guvenceye_al(work_dir)

    try:
        dal_var = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{dal_adi}"],
            cwd=str(work_dir)
        ).returncode == 0

        if not dal_var:
            return {"ok": False, "mesaj": f"'{dal_adi}' dalı yerelde bulunamadı."}

        # 1. Ana dala geç
        c1 = subprocess.run(["git", "checkout", ana_dal], capture_output=True, text=True, cwd=str(work_dir))
        if c1.returncode != 0:
            return {"ok": False, "mesaj": f"'{ana_dal}' dalına geçilemedi: {c1.stderr.strip()}"}

        # 2. Remote'dan en son halini al
        subprocess.run(["git", "pull", "--ff-only", "origin", ana_dal], capture_output=True, text=True, cwd=str(work_dir))

        # 3. Dalı merge et
        m_msg = mesaj.strip() or f"merge: {dal_adi} ana dala aktarıldı (onaylandı)"
        if issue_number and f"#{issue_number}" not in m_msg:
            m_msg += f" (closes #{issue_number})"

        c3 = subprocess.run(
            ["git", "merge", "--no-ff", "-X", "theirs", dal_adi, "-m", m_msg],
            capture_output=True,
            text=True,
            cwd=str(work_dir)
        )
        if c3.returncode != 0:
            subprocess.run(["git", "merge", "--abort"], capture_output=True, text=True, cwd=str(work_dir))
            return {"ok": False, "mesaj": f"Merge çakışması: {c3.stderr.strip()}"}

        # 4. Remote'a push et
        c4 = subprocess.run(["git", "push", "origin", ana_dal], capture_output=True, text=True, cwd=str(work_dir))
        if c4.returncode != 0:
            return {"ok": False, "mesaj": f"'{ana_dal}' remote'a push edilemedi: {c4.stderr.strip()}"}

        # 5. Dalı sil (yerel ve uzaktan)
        subprocess.run(["git", "branch", "-D", dal_adi], capture_output=True, text=True, cwd=str(work_dir))
        subprocess.run(["git", "push", "origin", "--delete", dal_adi], capture_output=True, text=True, cwd=str(work_dir))

        # 6. GitHub Issue'yu kapat
        if issue_number:
            try:
                sys.path.insert(0, str(work_dir / "scripts"))
                import github_issue_bridge as GH
                GH.github_issue_kapat(issue_number, kapanis_notu=f"İzole dal '{dal_adi}' ana dala birleştirilerek yayınlandı.", cwd=work_dir)
            except Exception:
                pass

        # 7. Talebi CANLIDA olarak işaretle ve kilitle
        try:
            sys.path.insert(0, str(work_dir / "scripts"))
            import musteri_talepleri as MT
            target_tid = None
            if dal_adi_veya_talep.upper().startswith("TALEP-"):
                target_tid = dal_adi_veya_talep.upper()
            elif issue_number:
                for item in (MT.db_tum_talepler() if hasattr(MT, 'db_tum_talepler') else []):
                    if item.get("github_issue_number") == issue_number:
                        target_tid = item.get("id")
                        break
            if target_tid:
                MT.guncelle(target_tid, durum="CANLIDA",
                            studio_notu=f"İzole dal '{dal_adi}' ana dala birleştirildi ve canlıya alındı (kilitlendi).",
                            zorla=True)
        except Exception:
            pass

        return {
            "ok": True,
            "mesaj": f"'{dal_adi}' başarıyla '{ana_dal}' dalına birleştirildi ve dal temizlendi.",
            "ana_dal": ana_dal,
            "dal": dal_adi
        }
    finally:
        if stashed:
            _calisma_dizinini_geri_yukle(work_dir)


def canliya_dagit_tekil(talep_id: str, cwd: Path | None = None) -> dict:
    """Belirtilen talebi izole dalı üzerinden (veya geriye dönük cherry-pick ile) ana dala aktarır."""
    if not talep_id:
        return {"ok": False, "mesaj": "Talep ID belirtilmedi."}

    work_dir = cwd or ROOT
    ana_dal = ana_dal_bul(work_dir)
    dal_adi = gorev_dali_adi(talep_id, cwd=work_dir)

    # 1. İzole dal var mı kontrol et
    dal_var = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{dal_adi}"],
        cwd=str(work_dir)
    ).returncode == 0

    if dal_var:
        # İzole dal mevcutsa doğrudan temiz merge yap
        issue_no = None
        try:
            sys.path.insert(0, str(work_dir / "scripts"))
            import musteri_talepleri as MT
            t = MT.getir(talep_id, cwd=work_dir)
            if t:
                issue_no = t.get("github_issue_number")
        except Exception:
            pass
        return gorev_dali_birlestir(dal_adi, issue_number=issue_no, cwd=work_dir)

    # 2. Geriye dönük uyumluluk: Çalışma dalından cherry-pick fallback
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
        c1 = subprocess.run(["git", "checkout", ana_dal], capture_output=True, text=True, cwd=str(work_dir))
        if c1.returncode != 0:
            return {"ok": False, "mesaj": f"'{ana_dal}' dalına geçilemedi: {c1.stderr.strip()}"}

        subprocess.run(["git", "pull", "--ff-only", "origin", ana_dal], capture_output=True, text=True, cwd=str(work_dir))

        for c in commits:
            cp_res = subprocess.run(["git", "cherry-pick", c], capture_output=True, text=True, cwd=str(work_dir))
            if cp_res.returncode != 0:
                subprocess.run(["git", "cherry-pick", "--abort"], capture_output=True, text=True, cwd=str(work_dir))
                return {
                    "ok": False,
                    "mesaj": f"{tid} aktarılırken çakışma (conflict) oluştu (commit {c[:8]}). "
                             f"Bu talep önceki geliştirmelere bağımlı olabilir. Lütfen 'Tümünü Canlıya Dağıt' seçeneğini kullanın."
                }

        c4 = subprocess.run(["git", "push", "origin", ana_dal], capture_output=True, text=True, cwd=str(work_dir))
        if c4.returncode != 0:
            return {"ok": False, "mesaj": f"'{ana_dal}' remote'a push edilemedi: {c4.stderr.strip()}"}

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


def canliya_dagit_hepsi(cwd: Path | None = None) -> dict:
    """Tüm açık bug/*, feature/* ve çalışma dalındaki onaylı işleri ana dala merge edip push eder."""
    work_dir = cwd or ROOT
    ana_dal = ana_dal_bul(work_dir)
    calisma_dali = os.getenv("STUDIO_GIT_BRANCH", "studio/calisma")
    if calisma_dali == ana_dal:
        calisma_dali = "studio/calisma"

    stashed = _calisma_dizinini_guvenceye_al(work_dir)

    try:
        # 1. Ana dala geç ve güncelle
        c1 = subprocess.run(["git", "checkout", ana_dal], capture_output=True, text=True, cwd=str(work_dir))
        if c1.returncode != 0:
            return {"ok": False, "mesaj": f"'{ana_dal}' dalına geçilemedi: {c1.stderr.strip()}"}

        subprocess.run(["git", "pull", "--ff-only", "origin", ana_dal], capture_output=True, text=True, cwd=str(work_dir))
        subprocess.run(["git", "clean", "-fd"], capture_output=True, text=True, cwd=str(work_dir))

        # 2. Varsa açık bug/* ve feature/* dallarını tespit et
        br_res = subprocess.run(["git", "branch", "--list", "bug/*", "feature/*"], capture_output=True, text=True, cwd=str(work_dir))
        izole_dallar = [b.strip().lstrip("* ") for b in br_res.stdout.splitlines() if b.strip()]

        birlestirilen_dallar = []
        for d in izole_dallar:
            m_res = subprocess.run(
                ["git", "merge", "--no-ff", "-X", "theirs", d, "-m", f"merge: {d} ana dala birleştirildi"],
                capture_output=True, text=True, cwd=str(work_dir)
            )
            if m_res.returncode == 0:
                birlestirilen_dallar.append(d)
                # Birleştirilen dalı sil
                subprocess.run(["git", "branch", "-D", d], capture_output=True, text=True, cwd=str(work_dir))
                subprocess.run(["git", "push", "origin", "--delete", d], capture_output=True, text=True, cwd=str(work_dir))
            else:
                subprocess.run(["git", "merge", "--abort"], capture_output=True, text=True, cwd=str(work_dir))

        # 3. Varsa legacy çalışma dalını merge et
        calisma_var = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{calisma_dali}"],
            cwd=str(work_dir)
        ).returncode == 0
        if calisma_var:
            merge_msg = f"merge: {calisma_dali} canlıya dağıtıldı (onaylandı)"
            subprocess.run(
                ["git", "merge", "--no-ff", "-X", "theirs", calisma_dali, "-m", merge_msg],
                capture_output=True, text=True, cwd=str(work_dir)
            )

        # 4. Remote'a push et
        c4 = subprocess.run(["git", "push", "origin", ana_dal], capture_output=True, text=True, cwd=str(work_dir))
        if c4.returncode != 0:
            return {"ok": False, "mesaj": f"'{ana_dal}' remote'a push edilemedi: {c4.stderr.strip()}"}

        # 5. İlgili açık GitHub Issue'larını kapat/eşitle
        issue_sonuc = issuelari_kapat(work_dir)

        mesaj = f"Tüm işler başarıyla '{ana_dal}' dalına birleştirildi ve canlı dağıtım başlatıldı."
        if birlestirilen_dallar:
            mesaj += f" (Birleştirilen izole dallar: {', '.join(birlestirilen_dallar)})"

        return {
            "ok": True,
            "mesaj": mesaj,
            "ana_dal": ana_dal,
            "birlestirilen_dallar": birlestirilen_dallar,
            "kapatilan_issuelar": issue_sonuc.get("kapatilanlar", [])
        }
    finally:
        subprocess.run(["git", "checkout", "-q", calisma_dali], capture_output=True, text=True, cwd=str(work_dir))
        if stashed:
            _calisma_dizinini_geri_yukle(work_dir)


def _workflow_bul(anahtar_kelimeler: list[str], work_dir: Path) -> str | None:
    """Projedeki .github/workflows altındaki yaml dosyalarını tarayıp eşleşen workflow adını bulur."""
    wf_dir = work_dir / ".github" / "workflows"
    if not wf_dir.is_dir():
        return None
    for yml in sorted(wf_dir.glob("*.yml")) + sorted(wf_dir.glob("*.yaml")):
        try:
            icerik = yml.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        ad_match = re.search(r"^name:\s*['\"]?([^'\"\n]+)['\"]?", icerik, re.MULTILINE)
        wf_adi = ad_match.group(1).strip() if ad_match else yml.stem
        for kw in anahtar_kelimeler:
            if kw.lower() in wf_adi.lower() or kw.lower() in yml.name.lower():
                return wf_adi
    return None


def canliya_dagit_tetikle(hedef: str = "hepsi", kanal: str = "production", cwd: Path | None = None) -> dict:
    """Belirli bir hedef ortam için CI/CD dağıtımını tetikler (web/backend, mobil veya hepsi)."""
    work_dir = cwd or ROOT
    ana_dal = ana_dal_bul(work_dir)
    hedef = hedef.lower().strip()
    tetiklenenler = []
    hatalar = []

    # 1. Web & Backend
    if hedef in ("web", "backend", "hepsi"):
        wf_web = _workflow_bul(["deploy", "web", "server", "api"], work_dir) or "Deploy"
        cmd_web = ["gh", "workflow", "run", wf_web, "--ref", ana_dal]
        r_w = subprocess.run(cmd_web, capture_output=True, text=True, cwd=str(work_dir), timeout=15)
        if r_w.returncode == 0:
            tetiklenenler.append("Web & Backend")
        else:
            hatalar.append(f"Web tetikleme hatası: {r_w.stderr.strip()}")

    # 2. Mobil
    if hedef in ("mobil", "android", "mobile", "hepsi"):
        wf_mob = _workflow_bul(["android", "mobile", "mobil", "play", "ios"], work_dir) or "Build & Deploy Android"
        cmd_mob = ["gh", "workflow", "run", wf_mob, "--ref", ana_dal]
        r_m = subprocess.run(cmd_mob, capture_output=True, text=True, cwd=str(work_dir), timeout=15)
        if r_m.returncode == 0:
            tetiklenenler.append(f"Mobil Uygulama ({kanal})")
        else:
            hatalar.append(f"Mobil tetikleme hatası: {r_m.stderr.strip()}")

    if tetiklenenler:
        msg = f"Dağıtım başarıyla başlatıldı: {', '.join(tetiklenenler)}."
        if hatalar:
            msg += f" (Uyarılar: {'; '.join(hatalar)})"
        return {"ok": True, "mesaj": msg, "tetiklenenler": tetiklenenler}
    else:
        return {"ok": False, "mesaj": f"Hiçbir dağıtım tetiklenemedi: {'; '.join(hatalar)}"}


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
    parser = argparse.ArgumentParser(description="İzole Dal Yönetimi, Canlı Dağıtım ve GitHub Issue Yönetimi")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--hepsi", action="store_true", help="Tüm onaylı işleri ana dala birleştir ve canlıya gönder")
    group.add_argument("--tekil", metavar="TALEP_ID", help="Yalnızca belirtilen talebi ana dala birleştir ve canlıya gönder")
    group.add_argument("--hazirla", metavar="TASK_VEYA_TALEP", help="Görev için master tabanlı izole dal aç")
    group.add_argument("--birlestir", metavar="DAL_ADI", help="İzole dalı ana dala birleştir ve dalı temizle")
    group.add_argument("--tetikle", choices=["web", "mobil", "hepsi"], help="Seçilen ortamın CI/CD dağıtımını tetikle")
    group.add_argument("--issuelari-kapat", action="store_true", help="Çözülmüş taleplerin GitHub issue'larını kapat")

    parser.add_argument("--kanal", default="production", help="Mobil dağıtım kanalı (internal, alpha, beta, production)")

    args = parser.parse_args()

    if args.hepsi:
        res = canliya_dagit_hepsi()
        print(("✓ " if res["ok"] else "✗ ") + res["mesaj"])
        sys.exit(0 if res["ok"] else 1)
    elif args.tekil:
        res = canliya_dagit_tekil(args.tekil)
        print(("✓ " if res["ok"] else "✗ ") + res["mesaj"])
        sys.exit(0 if res["ok"] else 1)
    elif args.hazirla:
        res = gorev_dali_hazirla(args.hazirla)
        print(("✓ " if res["ok"] else "✗ ") + res["mesaj"])
        sys.exit(0 if res["ok"] else 1)
    elif args.birlestir:
        res = gorev_dali_birlestir(args.birlestir)
        print(("✓ " if res["ok"] else "✗ ") + res["mesaj"])
        sys.exit(0 if res["ok"] else 1)
    elif args.tetikle:
        res = canliya_dagit_tetikle(hedef=args.tetikle, kanal=args.kanal)
        print(("✓ " if res["ok"] else "✗ ") + res["mesaj"])
        sys.exit(0 if res["ok"] else 1)
    elif args.issuelari_kapat:
        res = issuelari_kapat()
        print(("✓ " if res["ok"] else "✗ ") + res["mesaj"])
        sys.exit(0 if res["ok"] else 1)


if __name__ == "__main__":
    main()
