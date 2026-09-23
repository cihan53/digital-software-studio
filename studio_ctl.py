#!/usr/bin/env python3
"""
Kontrol ekranı — çalışan boru hattını izler ve yönetir.

    python studio_ctl.py

Tuşlar:  p duraklat/sürdür · s durdur · k mevcut görevi atla
         r başarısız görevi tekrar sıraya al · o çıktıyı aç · q çık

Not: çalışmakta olan bir model çağrısı yarıda kesilmez (parası zaten harcanmış
olur). Komutlar iki çağrı ARASINDA uygulanır — koşucu her görev öncesi
workspace/.control/ altını okur.
"""

import json
import os
import select
import shutil
import subprocess
import sys
import termios
import time
import tty
from pathlib import Path

import studio_board as B

ROOT = Path(__file__).resolve().parent
TRACE = ROOT / "workspace" / ".trace"

DIM, BOLD, RED, GREEN, YELLOW, CYAN, RESET = (
    "\033[2m", "\033[1m", "\033[31m", "\033[32m", "\033[33m", "\033[36m", "\033[0m"
)
MARK = {
    B.DONE: f"{GREEN}✓{RESET}", B.RUNNING: f"{YELLOW}▸{RESET}",
    B.READY: f"{CYAN}○{RESET}", B.BLOCKED: f"{RED}■{RESET}",
    B.FAILED: f"{RED}✗{RESET}", B.SKIPPED: f"{DIM}–{RESET}", B.TODO: f"{DIM}·{RESET}",
}


def human(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m}d{s:02d}s" if m else f"{s}s"


def read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def runner_alive() -> bool:
    """Bu dizine ait koşucu yaşıyor mu?

    pgrep kullanılamaz: aynı makinede başka bir stüdyonun koşusunu bizimki
    sanardı. Kilit dosyası workspace altında, yani dizine özgü.
    """
    lock = ROOT / "workspace" / ".lock"
    try:
        os.kill(int(lock.read_text(encoding="utf-8").strip()), 0)
        return True
    except (OSError, ValueError):
        return False


def render_design(cur: dict, cols: int) -> str:
    """Pano henüz yokken tasarım aşamasının ilerlemesini gösterir."""
    org = read_json(ROOT / "org_chart.json", {"hierarchy": []})
    state = {"completed_steps": [], "completed_outputs": []}
    # Önce studio.db'den oku
    try:
        conn = B.db_conn()
        try:
            cur_db = conn.cursor()
            cur_db.execute("SELECT anahtar, deger FROM studio_state WHERE anahtar IN ('completed_steps', 'completed_outputs')")
            rows = dict(cur_db.fetchall())
            if "completed_steps" in rows:
                state["completed_steps"] = json.loads(rows["completed_steps"])
            if "completed_outputs" in rows:
                state["completed_outputs"] = json.loads(rows["completed_outputs"])
        finally:
            conn.close()
    except Exception:
        state = read_json(ROOT / "workspace" / ".state.json",
                          {"completed_steps": [], "completed_outputs": []})
    done = set(state.get("completed_steps", []))
    design = [a for a in org["hierarchy"] if a.get("stage", "design") == "design"]
    active = cur.get("role")

    durum = f"{GREEN}ÇALIŞIYOR{RESET}" if runner_alive() else f"{DIM}BOŞTA{RESET}"
    L = [f"{BOLD}Aşama 1/2 — Tasarım{RESET}   {durum}   "
         f"{len(done & {a['id'] for a in design})}/{len(design)} rol   "
         f"{DIM}{time.strftime('%H:%M:%S')}{RESET}",
         "─" * min(cols, 96)]

    for a in design:
        eng = f"{a.get('backend', 'cli')}/{a.get('model', '-')}"
        if a["id"] in done:
            L.append(f" {GREEN}✓{RESET} {a['id']:<24}{DIM}{eng}{RESET}")
        elif a["id"] == active:
            L.append(f" {YELLOW}▸{RESET} {BOLD}{a['id']:<24}{RESET}{CYAN}{eng}{RESET}")
        else:
            L.append(f" {DIM}·  {a['id']:<24}{eng}{RESET}")

    L += ["", f"{DIM}Sprint panosu bu aşamanın sonunda 'sprint_planner' tarafından "
              f"üretilecek.{RESET}"]

    if cur.get("role"):
        el = time.time() - cur.get("started_at", time.time())
        L += ["", f"{YELLOW}▸ ŞU AN{RESET} {cur['role']} → {cur['target']}",
              f"  {DIM}{cur['backend']}/{cur['model']} · giden "
              f"{cur.get('prompt_chars', 0):,} krk · geçen {human(el)}{RESET}"]
        live = TRACE / "current.out"
        if live.exists():
            txt = live.read_text(encoding="utf-8", errors="replace")
            L.append(f"  {DIM}gelen {len(txt):,} krk{RESET}")
            for line in txt[-900:].splitlines()[-8:]:
                L.append(f"  {DIM}{line[:cols-4]}{RESET}")

    L += ["─" * min(cols, 96),
          f"{BOLD}p{RESET} duraklat/sürdür  {BOLD}s{RESET} durdur  {BOLD}q{RESET} çık"]
    return "\n".join(L)


def render(msg: str = "") -> str:
    cols = shutil.get_terminal_size((100, 40)).columns
    ctrl = B.control_state()
    cur = read_json(TRACE / "current.json", {})
    try:
        board = B.load()
    except ValueError as e:
        return (f"{RED}Pano bozuk:{RESET} {e}\n\n"
                f"{DIM}Tasarım görünümüne dönülüyor...{RESET}\n\n"
                + render_design(cur, cols))
    except FileNotFoundError:
        # Pano tasarım aşamasının SONUNDA üretilir; o ana kadar rol ilerlemesini göster.
        return render_design(cur, cols)

    p = B.progress(board)
    L = []

    if ctrl["stopping"]:
        durum = f"{RED}DURDURULUYOR{RESET}"
    elif ctrl["paused"]:
        durum = f"{YELLOW}DURAKLATILDI{RESET}"
    elif runner_alive():
        durum = f"{GREEN}ÇALIŞIYOR{RESET}"
    else:
        durum = f"{DIM}BOŞTA{RESET}"

    slip = B.slip_days(board)
    slip_s = f"  kayma {RED}+{slip}g{RESET}" if slip > 0 else ""
    L.append(f"{BOLD}Sprint Panosu{RESET}   {durum}   "
             f"{p['sprints_done']}/{p['sprints_total']} sprint · "
             f"{p['done']}/{p['total']} görev{slip_s}   {DIM}{time.strftime('%H:%M:%S')}{RESET}")
    L.append("─" * min(cols, 96))

    for s in sorted(board["sprints"], key=lambda x: x["order"]):
        head = (f" {BOLD}{s['id']}{RESET} {s['name'][:34]:<36}"
                f"{DIM}{s.get('planned_start','?')} → {s.get('planned_end','?')}"
                f"  [{s['status']}]{RESET}")
        L.append(head)
        for t in s["tasks"]:
            m = MARK.get(t["status"], "?")
            dur = f"{DIM}{human(t['duration_s'])}{RESET}" if t.get("duration_s") else ""
            # Not her durumda görünsün: READY'ye dönmüş ama önceki denemesi
            # başarısız olmuş görevin sebebi gizli kalmasın.
            note = f"  {RED}{t['note'][:52]}{RESET}" if t.get("note") else ""
            L.append(f"   {m} {t['id']:<8} {DIM}{t['phase'][:7]:<8}{RESET}"
                     f"{t['title'][:38]:<40}{dur}{note}")
        L.append("")

    if cur.get("role"):
        el = time.time() - cur.get("started_at", time.time())
        L.append(f"{YELLOW}▸ ŞU AN{RESET} {cur.get('task', '')} · {cur['role']} → {cur['target']}")
        L.append(f"  {DIM}{cur['backend']}/{cur['model']} · giden "
                 f"{cur.get('prompt_chars', 0):,} krk · geçen {human(el)}{RESET}")
        live = TRACE / "current.out"
        if live.exists():
            txt = live.read_text(encoding="utf-8", errors="replace")
            L.append(f"  {DIM}gelen {len(txt):,} krk{RESET}")
            for line in txt[-700:].splitlines()[-6:]:
                L.append(f"  {DIM}{line[:cols-4]}{RESET}")

    L.append("─" * min(cols, 96))
    if not runner_alive() and not ctrl["paused"]:
        try:
            _, nxt = B.next_ready(board)
        except Exception:
            nxt = None
        if nxt:
            L.append(f"{YELLOW}! Koşucu çalışmıyor — '{nxt['id']}' hazır ama kimse "
                     f"yürütmüyor.{RESET}")
            L.append(f"  {DIM}Başlatmak için ayrı bir terminalde: ./basla.sh{RESET}")
            L.append("─" * min(cols, 96))
    L.append(f"{BOLD}p{RESET} duraklat/sürdür  {BOLD}s{RESET} durdur  "
             f"{BOLD}k{RESET} atla  {BOLD}r{RESET} tekrar dene  "
             f"{BOLD}o{RESET} çıktı klasörü  {BOLD}q{RESET} çık")
    if msg:
        L.append(f"{CYAN}{msg}{RESET}")
    return "\n".join(L)


def getkey(timeout: float) -> str:
    if select.select([sys.stdin], [], [], timeout)[0]:
        return sys.stdin.read(1)
    return ""


def handle(key: str) -> str:
    if key == "p":
        if B.is_set("pause"):
            B.clear("pause")
            return "Sürdürüldü — koşucu bir sonraki görevi alacak."
        B.request("pause")
        return "Duraklatıldı — çalışan çağrı bitince yeni görev alınmayacak."
    if key == "s":
        B.request("stop")
        return "Durdurma istendi — mevcut çağrı bitince koşucu çıkacak."
    if key == "k":
        cur = read_json(TRACE / "current.json", {})
        tid = cur.get("task")
        if not tid:
            try:
                _, t = B.next_ready(B.load())
                tid = t["id"] if t else None
            except Exception:
                tid = None
        if not tid:
            return "Atlanacak görev bulunamadı."
        B.request("skip", tid)
        return f"{tid} atlanacak."
    if key == "r":
        board = B.load()
        stuck = [t for _, t in B.all_tasks(board) if t["status"] in (B.FAILED, B.BLOCKED)]
        if not stuck:
            return "Başarısız/bloke görev yok."
        for t in stuck:
            t["status"] = B.TODO
            t["note"] = ""
        B.refresh(board)
        B.save(board)
        return f"{len(stuck)} görev tekrar sıraya alındı."
    if key == "o":
        subprocess.run(["open", str(ROOT / "workspace")], check=False)
        return "workspace/ açıldı."
    return ""


def main():
    if not sys.stdin.isatty():
        print(render())
        return
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    msg, msg_at = "", 0.0
    try:
        tty.setcbreak(fd)
        while True:
            if msg and time.time() - msg_at > 6:
                msg = ""
            os.system("clear")
            print(render(msg))
            k = getkey(2.0)
            if k == "q":
                break
            if k:
                out = handle(k)
                if out:
                    msg, msg_at = out, time.time()
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        print()


if __name__ == "__main__":
    main()
