#!/usr/bin/env python3
"""Panelden yerel ortam yönetimi (issue #191, #217): workspace/yerel_ortam.sh'i (profil "yerel_ortam") ya da üretim derlemesi önizlemesini (profil "onizleme": build + preview) başlat / durdur / yeniden başlat, port durumu, log.

Yalnız projenin KENDİ betiği (workspace/yerel_ortam.sh ya da kökteki yerel_ortam.sh) çalıştırılır; kullanıcı girdisi komuta karışmaz.
Süreç yeni oturumda başlar, çıktısı workspace/logs/yerel_ortam.log'a gider; kapatma yalnız bu projeye ait süreçlere dokunur.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import servis_kapat as SK  # noqa: E402

LOG_MAX = 60_000


PROFILLER = ("yerel_ortam", "onizleme")


def _cfg(kok: Path) -> dict:
    try:
        return json.loads((kok / "workspace" / "studio.config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def onizleme_port(kok: Path = ROOT) -> int:
    """Önizleme portu: onizleme.port ya da canlı (dev) portun bir fazlası."""
    c = _cfg(kok)
    p = (c.get("onizleme") or {}).get("port")
    if isinstance(p, int) and 0 < p < 65536:
        return p
    ports = (c.get("live") or {}).get("ports") or [3000]
    return int(ports[0]) + 1


def onizleme_komutu(kok: Path = ROOT) -> str | None:
    """Üretim önizlemesi: `workspace/onizleme.sh` varsa o; yoksa uygulama dizininde package.json build + preview betiklerinden üretilir."""
    sh = kok / "workspace" / "onizleme.sh"
    if sh.is_file():
        return f"bash {shlex.quote(str(sh))}"
    try:
        import uygulama_dizini as UD
        app = kok / UD.dizin(_cfg(kok))
        betikler = json.loads((app / "package.json").read_text(encoding="utf-8")).get("scripts") or {}
    except (OSError, ValueError, ImportError):
        return None
    if "build" not in betikler or "preview" not in betikler:
        return None
    pm = "pnpm" if (app / "pnpm-lock.yaml").exists() else ("yarn" if (app / "yarn.lock").exists() else "npm")
    port = onizleme_port(kok)
    arg = f"--port {port}" if pm == "pnpm" else f"-- --port {port}"
    return f"cd {shlex.quote(str(app))} && {pm} run build && {pm} run preview {arg}"


def betik(kok: Path = ROOT, profil: str = "yerel_ortam") -> Path | None:
    if profil == "onizleme":
        return kok / "workspace" / "onizleme.sh" if (kok / "workspace" / "onizleme.sh").is_file() else None
    for p in (kok / "workspace" / "yerel_ortam.sh", kok / "yerel_ortam.sh"):
        if p.is_file():
            return p
    return None


def _pidf(kok: Path, profil: str = "yerel_ortam") -> Path:
    return kok / "workspace" / ".control" / f"{profil}.pid"


def _logf(kok: Path, profil: str = "yerel_ortam") -> Path:
    return kok / "workspace" / "logs" / f"{profil}.log"


def _pid(kok: Path, profil: str = "yerel_ortam") -> int | None:
    try:
        p = int(_pidf(kok, profil).read_text().strip())
    except (OSError, ValueError):
        return None
    return p if SK._canli(p) else None


def portlar(kok: Path = ROOT, profil: str = "yerel_ortam") -> list[int]:
    if profil == "onizleme":
        return [onizleme_port(kok)]
    try:
        import studio_board as B
        return list(B.live_ports())
    except Exception:
        return [3000, 3001]


def _komut(kok: Path, profil: str) -> tuple[str | None, str | None]:
    """(çalıştırılacak kabuk komutu, gösterilecek ad)"""
    if profil == "onizleme":
        k = onizleme_komutu(kok)
        return k, ("workspace/onizleme.sh" if (kok / "workspace" / "onizleme.sh").is_file() else "build + preview")
    b = betik(kok)
    return (f"bash {shlex.quote(str(b))}" if b else None), (str(b.relative_to(kok)) if b else None)


def durum(kok: Path = ROOT, portlar_: list[int] | None = None, profil: str = "yerel_ortam") -> dict:
    komut, ad = _komut(kok, profil)
    pl = portlar_ if portlar_ is not None else portlar(kok, profil)
    acik = {p: bool([x for x in SK.dinleyenler(p) if SK.projede_mi(x, kok)]) for p in pl}
    pid = _pid(kok, profil)
    if any(acik.values()):
        d = "calisiyor" if all(acik.values()) else "kismen"
    elif pid:
        d = "baslatiliyor"
    else:
        d = "durdu"
    return {"profil": profil, "betik": ad, "betik_var": bool(komut), "durum": d, "pid": pid,
            "portlar": [{"port": p, "acik": a, "url": f"http://localhost:{p}"} for p, a in acik.items()],
            "log_yolu": str(_logf(kok, profil).relative_to(kok))}


def log_oku(kok: Path = ROOT, satir: int = 300, profil: str = "yerel_ortam") -> str:
    f = _logf(kok, profil)
    try:
        with open(f, "rb") as h:
            h.seek(0, os.SEEK_END)
            n = h.tell()
            h.seek(max(0, n - LOG_MAX))
            veri = h.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(veri.splitlines()[-satir:])


def baslat(kok: Path = ROOT, portlar_: list[int] | None = None, profil: str = "yerel_ortam") -> dict:
    komut, ad = _komut(kok, profil)
    if not komut:
        return {"ok": False, "mesaj": ("workspace/yerel_ortam.sh henüz yok (S1-T1 görevi üretir)." if profil == "yerel_ortam"
                                       else "Önizleme için uygulama dizininde package.json içinde build ve preview betikleri (ya da workspace/onizleme.sh) gerekli.")}
    d = durum(kok, portlar_, profil)
    if d["durum"] != "durdu":
        return {"ok": False, "mesaj": "Zaten çalışıyor/başlatılıyor."}
    _logf(kok, profil).parent.mkdir(parents=True, exist_ok=True)
    _pidf(kok, profil).parent.mkdir(parents=True, exist_ok=True)
    log = open(_logf(kok, profil), "ab")
    log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} başlatılıyor: {ad} ===\n".encode())
    log.flush()
    p = subprocess.Popen(["bash", "-c", komut], cwd=kok, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    _pidf(kok, profil).write_text(str(p.pid))
    return {"ok": True, "mesaj": "Başlatıldı.", "pid": p.pid}


def durdur(kok: Path = ROOT, portlar_: list[int] | None = None, profil: str = "yerel_ortam") -> dict:
    kapatilan = []
    pid = _pid(kok, profil)
    if pid:
        kapatilan += SK.agac_kapat(pid)
    for port in (portlar_ if portlar_ is not None else portlar(kok, profil)):
        for x in SK.dinleyenler(port):
            if SK.projede_mi(x, kok):
                kapatilan += SK.agac_kapat(x)
    try:
        _pidf(kok, profil).unlink()
    except OSError:
        pass
    _logf(kok, profil).parent.mkdir(parents=True, exist_ok=True)
    with open(_logf(kok, profil), "ab") as h:
        h.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} durduruldu ===\n".encode())
    return {"ok": True, "mesaj": "Durduruldu." if kapatilan else "Çalışan süreç yoktu.", "kapatilan": sorted(set(kapatilan))}


def yeniden(kok: Path = ROOT, portlar_: list[int] | None = None, profil: str = "yerel_ortam") -> dict:
    durdur(kok, portlar_, profil)
    time.sleep(1)
    return baslat(kok, portlar_, profil)


if __name__ == "__main__":
    import json
    print(json.dumps(durum(), ensure_ascii=False, indent=2))
