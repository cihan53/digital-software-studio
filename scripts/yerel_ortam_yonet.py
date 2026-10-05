#!/usr/bin/env python3
"""Panelden yerel ortam yönetimi (issue #191): workspace/yerel_ortam.sh'i başlat / durdur / yeniden başlat, port durumu, log.

Yalnız projenin KENDİ betiği (workspace/yerel_ortam.sh ya da kökteki yerel_ortam.sh) çalıştırılır; kullanıcı girdisi komuta karışmaz.
Süreç yeni oturumda başlar, çıktısı workspace/logs/yerel_ortam.log'a gider; kapatma yalnız bu projeye ait süreçlere dokunur.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import servis_kapat as SK  # noqa: E402

LOG_MAX = 60_000


def betik(kok: Path = ROOT) -> Path | None:
    for p in (kok / "workspace" / "yerel_ortam.sh", kok / "yerel_ortam.sh"):
        if p.is_file():
            return p
    return None


def _pidf(kok: Path) -> Path:
    return kok / "workspace" / ".control" / "yerel_ortam.pid"


def _logf(kok: Path) -> Path:
    return kok / "workspace" / "logs" / "yerel_ortam.log"


def _pid(kok: Path) -> int | None:
    try:
        p = int(_pidf(kok).read_text().strip())
    except (OSError, ValueError):
        return None
    return p if SK._canli(p) else None


def portlar(kok: Path = ROOT) -> list[int]:
    try:
        import studio_board as B
        return list(B.live_ports())
    except Exception:
        return [3000, 3001]


def durum(kok: Path = ROOT, portlar_: list[int] | None = None) -> dict:
    b = betik(kok)
    pl = portlar_ if portlar_ is not None else portlar(kok)
    acik = {p: bool([x for x in SK.dinleyenler(p) if SK.projede_mi(x, kok)]) for p in pl}
    pid = _pid(kok)
    if any(acik.values()):
        d = "calisiyor" if all(acik.values()) else "kismen"
    elif pid:
        d = "baslatiliyor"
    else:
        d = "durdu"
    return {"betik": str(b.relative_to(kok)) if b else None, "betik_var": bool(b), "durum": d, "pid": pid,
            "portlar": [{"port": p, "acik": a, "url": f"http://127.0.0.1:{p}"} for p, a in acik.items()],
            "log_yolu": str(_logf(kok).relative_to(kok))}


def log_oku(kok: Path = ROOT, satir: int = 300) -> str:
    f = _logf(kok)
    try:
        with open(f, "rb") as h:
            h.seek(0, os.SEEK_END)
            n = h.tell()
            h.seek(max(0, n - LOG_MAX))
            veri = h.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(veri.splitlines()[-satir:])


def baslat(kok: Path = ROOT, portlar_: list[int] | None = None) -> dict:
    b = betik(kok)
    if not b:
        return {"ok": False, "mesaj": "workspace/yerel_ortam.sh henüz yok (S1-T1 görevi üretir)."}
    d = durum(kok, portlar_)
    if d["durum"] != "durdu":
        return {"ok": False, "mesaj": "Yerel ortam zaten çalışıyor/başlatılıyor."}
    _logf(kok).parent.mkdir(parents=True, exist_ok=True)
    _pidf(kok).parent.mkdir(parents=True, exist_ok=True)
    log = open(_logf(kok), "ab")
    log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} başlatılıyor: {b.relative_to(kok)} ===\n".encode())
    log.flush()
    p = subprocess.Popen(["bash", str(b)], cwd=kok, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    _pidf(kok).write_text(str(p.pid))
    return {"ok": True, "mesaj": "Başlatıldı.", "pid": p.pid}


def durdur(kok: Path = ROOT, portlar_: list[int] | None = None) -> dict:
    kapatilan = []
    pid = _pid(kok)
    if pid:
        kapatilan += SK.agac_kapat(pid)
    for port in (portlar_ if portlar_ is not None else portlar(kok)):
        for x in SK.dinleyenler(port):
            if SK.projede_mi(x, kok):
                kapatilan += SK.agac_kapat(x)
    try:
        _pidf(kok).unlink()
    except OSError:
        pass
    _logf(kok).parent.mkdir(parents=True, exist_ok=True)
    with open(_logf(kok), "ab") as h:
        h.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} durduruldu ===\n".encode())
    return {"ok": True, "mesaj": "Durduruldu." if kapatilan else "Çalışan süreç yoktu.", "kapatilan": sorted(set(kapatilan))}


def yeniden(kok: Path = ROOT, portlar_: list[int] | None = None) -> dict:
    durdur(kok, portlar_)
    time.sleep(1)
    return baslat(kok, portlar_)


if __name__ == "__main__":
    import json
    print(json.dumps(durum(), ensure_ascii=False, indent=2))
