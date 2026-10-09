#!/usr/bin/env python3
"""Kontrol noktası (issue #275): önemli kararlardan sonra proje durumu commit + etiket olarak git'e gönderilir, geri dönmek kolay olur.

  brief-karari      brief görüşmesi bittikten sonra (brief + kararlar donar)
  envanter-*        envanter aşamasının her geçişinde (rotalar, envanter, tasarim, plan, tamam)
Etiket: kontrol/<ad>-<tarih>. Geri dönüş: `git checkout <etiket> -- workspace/docs` ya da dalı etikete sıfırla.
Ana dalda (main/master) commit/push yapılmaz (merge kullanıcı onayıdır). git/uzak yoksa sessiz no-op; hata üretimi durdurmaz.
Kapatma: STUDIO_KONTROL_NOKTASI=0.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _git(kok: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(kok), capture_output=True, text=True, timeout=120)


def var_mi(ad: str, kok: Path = ROOT) -> bool:
    try:
        return bool(_git(kok, "tag", "--list", f"kontrol/{ad}-*").stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return False


def olustur(ad: str, mesaj: str = "", kok: Path = ROOT, push: bool = True) -> str | None:
    """Commit (değişiklik varsa) + etiket + (uzak varsa) push. Etiket adını döndürür; yapılamazsa None."""
    if os.environ.get("STUDIO_KONTROL_NOKTASI") == "0" or not (kok / ".git").exists():
        return None
    if not (kok / "workspace" / "studio.config.json").exists():        # yalnız proje klasöründe (çerçeve deposunda asla)
        return None
    try:
        dal = _git(kok, "branch", "--show-current").stdout.strip()
        if not dal or dal in ("main", "master"):
            return None
        if _git(kok, "status", "--porcelain").stdout.strip():
            _git(kok, "add", "-A")
            if _git(kok, "commit", "-q", "-m", f"studio: kontrol noktası — {ad}" + (f" ({mesaj})" if mesaj else "")).returncode != 0:
                return None
        etiket = f"kontrol/{ad}-{datetime.now():%Y%m%d-%H%M%S}"
        if _git(kok, "tag", etiket).returncode != 0:
            return None
        if push and _git(kok, "remote", "get-url", "origin").returncode == 0:
            _git(kok, "push", "-q", "--no-verify", "origin", dal)
            _git(kok, "push", "-q", "--no-verify", "origin", etiket)
        try:
            sys.path.insert(0, str(kok))
            import studio_board as B
            B.audit("engine", "kontrol_noktasi", detay={"ad": ad, "etiket": etiket})
        except Exception:
            pass
        return etiket
    except (OSError, subprocess.TimeoutExpired):
        return None


def yoksa_olustur(ad: str, mesaj: str = "", kok: Path = ROOT) -> str | None:
    return None if var_mi(ad, kok) else olustur(ad, mesaj, kok)
