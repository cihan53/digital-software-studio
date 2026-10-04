#!/usr/bin/env python3
"""Studio servislerini listele / kapat (issue #145).

Servisler: panel (studio_web, varsayılan :8090), ortam (live.ports dinleyicileri: yerel Nuxt/mock vb.), koşucu.
GÜVENLİK: yalnız çalışma dizini bu projenin KÖKÜ altında olan süreçler kapatılır; başka proje veya sistem süreçlerine dokunulmaz.

  python3 scripts/servis_kapat.py liste
  python3 scripts/servis_kapat.py kapat --panel --ortam [--kosucu]   (hiçbiri verilmezse panel+ortam)
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _lsof(args: list[str]) -> str:
    try:
        return subprocess.run(["lsof", "-nP", *args], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def dinleyenler(port: int) -> list[int]:
    return sorted({int(x[1:]) for x in _lsof(["-iTCP:%d" % port, "-sTCP:LISTEN", "-Fp"]).splitlines() if x.startswith("p")})


def cwd_of(pid: int) -> Path | None:
    for ln in _lsof(["-a", "-p", str(pid), "-d", "cwd", "-Fn"]).splitlines():
        if ln.startswith("n"):
            return Path(ln[1:])
    return None


def projede_mi(pid: int, kok: Path) -> bool:
    c = cwd_of(pid)
    if c is None:
        return False
    try:
        c.resolve().relative_to(kok.resolve())
        return True
    except ValueError:
        return False


def cocuklar(pid: int) -> list[int]:
    out = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True).stdout.split()
    r: list[int] = []
    for c in out:
        r += [int(c)] + cocuklar(int(c))
    return r


def agac_kapat(pid: int, bekle: float = 4.0) -> list[int]:
    """pid ve tüm alt süreçleri SIGTERM, bekleyip kalanlara SIGKILL. Kapatılanların listesini döndürür."""
    hepsi = [pid] + cocuklar(pid)
    for p in reversed(hepsi):
        try:
            os.kill(p, signal.SIGTERM)
        except ProcessLookupError:
            pass
    bit = time.time() + bekle
    while time.time() < bit and any(_canli(p) for p in hepsi):
        time.sleep(0.2)
    for p in hepsi:
        if _canli(p):
            try:
                os.kill(p, signal.SIGKILL)
            except ProcessLookupError:
                pass
    return hepsi


def _canli(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def panel_portu() -> int:
    return int(os.environ.get("STUDIO_WEB_PORT", "8090"))


def ortam_portlari() -> list[int]:
    try:
        import studio_board as B
        return list(B.live_ports())
    except Exception:
        return [3000, 3001]


def servisler(kok: Path = ROOT, portlar_panel: int | None = None, portlar_ortam: list[int] | None = None) -> dict:
    """{'panel': [pid...], 'ortam': {port: [pid...]}} — yalnız bu projeye ait olanlar."""
    pp = portlar_panel if portlar_panel is not None else panel_portu()
    panel = [p for p in dinleyenler(pp) if projede_mi(p, kok)]
    pidf = kok / "workspace" / ".web.pid"
    if pidf.exists():
        try:
            p = int(pidf.read_text().strip())
            if _canli(p) and projede_mi(p, kok) and p not in panel:
                panel.append(p)
        except ValueError:
            pass
    ortam = {}
    for port in (portlar_ortam if portlar_ortam is not None else ortam_portlari()):
        ps = [p for p in dinleyenler(port) if projede_mi(p, kok)]
        if ps:
            ortam[port] = ps
    return {"panel": panel, "ortam": ortam}


def kosucu_pid(kok: Path = ROOT) -> int | None:
    try:
        p = int((kok / "workspace" / ".lock").read_text().strip())
        return p if _canli(p) else None
    except (OSError, ValueError):
        return None


def kapat(panel=True, ortam=True, kosucu=False, kok: Path = ROOT, **kw) -> list[str]:
    s = servisler(kok, **kw)
    log = []
    if kosucu:
        try:
            import studio_board as B
            if kosucu_pid(kok):
                B.request("stop", kaynak="servis_kapat")
                log.append("koşucuya durdurma istendi (çalışan çağrı bitince çıkar)")
        except Exception as e:
            log.append(f"koşucu durdurma istenemedi: {e}")
    if panel:
        for p in s["panel"]:
            log.append(f"panel kapatıldı: pid {p} (+{len(agac_kapat(p)) - 1} alt süreç)")
        (kok / "workspace" / ".web.pid").unlink(missing_ok=True)
    if ortam:
        for port, ps in s["ortam"].items():
            for p in ps:
                log.append(f"ortam :{port} kapatıldı: pid {p} (+{len(agac_kapat(p)) - 1} alt süreç)")
    return log


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["liste", "kapat"])
    ap.add_argument("--panel", action="store_true")
    ap.add_argument("--ortam", action="store_true")
    ap.add_argument("--kosucu", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "liste":
        s = servisler()
        print(f"panel   : {s['panel'] or 'kapalı'}")
        print(f"ortam   : {s['ortam'] or 'kapalı'}")
        print(f"koşucu  : {kosucu_pid() or 'kapalı'}")
        return 0
    tum = not (a.panel or a.ortam or a.kosucu)
    log = kapat(panel=a.panel or tum, ortam=a.ortam or tum, kosucu=a.kosucu)
    print("\n".join(log) if log else "kapatılacak servis yok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
