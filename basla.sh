#!/usr/bin/env bash
# ChyzTV Sanal Stüdyo — tek giriş noktası.
#
#   ./basla.sh              her şeyi sırayla çalıştırır ve kontrol ekranını açar
#   ./basla.sh --kontrol    hiçbir şey çalıştırmaz, sadece ön koşulları denetler
#   ./basla.sh --durdur     çalışan koşuyu nazikçe durdurur
#   ./basla.sh --izle       sadece kontrol ekranını açar
#   ./basla.sh --durum      tek satırlık durum özeti (ekran açmadan)
#   ./basla.sh --web        web arayüzünü başlatır (panel + müşteri odası, :8080)
#
#   ./basla.sh --musteri    müşteri denetim masasını (istek/şikayet) açar
#   ./basla.sh --onayla     günlük kota dolduğunda bir tur daha izin ver
#   ./basla.sh --onayla 5   bugün için 5 görevlik ek kota tanı
#
#   Pano yönetimi (studio.db üzerinde çalışır, koşucu bayrakla haberdar edilir):
#   ./basla.sh --oncelik S1-T2 10      görev önceliği (büyük = önce koşar)
#   ./basla.sh --sira S1-T2 0          görevi sprint içinde sıraya taşı
#   ./basla.sh --sprint-sira S3 0      sprint'i yeniden sırala
#   ./basla.sh --gec S2-T1             mevcut çağrı bitince bu göreve geç
#   ./basla.sh --gec S2-T1 --force     çağrıyı anında kesip bu göreve geç
#   ./basla.sh --atla [S1-T2]          görevi atla (id yoksa koşan/sıradaki)
#   ./basla.sh --atla S1-T2 --force    çağrıyı anında kesip atla
#
#   Günlük varsayılan: 3 görev / 2 USD. Değiştirmek için:
#   STUDIO_GUNLUK_GOREV, STUDIO_GUNLUK_BUTCE
#   ./basla.sh --sifirla    ilerlemeyi sıfırlar (üretilmiş dosyalar arşive gider)
set -uo pipefail
cd "$(dirname "$0")" || exit 1

PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"
LOG="workspace/logs/pipeline.log"
red()  { printf "\033[31m%s\033[0m\n" "$*"; }
grn()  { printf "\033[32m%s\033[0m\n" "$*"; }
ylw()  { printf "\033[33m%s\033[0m\n" "$*"; }
dim()  { printf "\033[2m%s\033[0m\n" "$*"; }

# Bu dizine ait koşucu çalışıyor mu? pgrep dizinden bağımsız eşleştiği için
# başka bir stüdyonun koşusunu bizimki sanıyordu; kilit dosyası dizine özgü.
calisiyor_mu() {
    local kilit="workspace/.lock"
    [ -f "$kilit" ] || return 1
    local pid; pid=$(cat "$kilit" 2>/dev/null)
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}
kosucu_pid() { cat workspace/.lock 2>/dev/null; }

# ---------------------------------------------------------------- alt komutlar
case "${1:-}" in
  --usage|--kullanim)
      if [ "${STUDIO_BACKEND:-agy}" = "devin" ]; then
        echo "── Devin AI Backend ──────────────────────────────"
        (devin auth status 2>/dev/null || ~/.local/bin/devin auth status 2>/dev/null || echo "devin CLI oturum durumu alınamadı")
      else
        echo "── Antigravity Model Kotası ─────────────────────────"
        (agy -p="/usage" 2>/dev/null || ~/.local/bin/agy -p="/usage")
      fi
      echo
      $PY - <<'PYEOF'
import json, pathlib
root = pathlib.Path(".")
idx = root / "workspace/.trace/index.jsonl"
if idx.exists() and idx.read_text().strip():
    rows = [json.loads(l) for l in idx.read_text().splitlines() if l.strip()]
    tin = sum(r.get("tokens_in", 0) for r in rows)
    tout = sum(r.get("tokens_out", 0) for r in rows)
    tth = sum(r.get("tokens_thinking", 0) for r in rows)
    print("── Proje İçi Token Özeti ────────────────────────────")
    print(f"Toplam Çağrı  : {len(rows)}")
    print(f"Girdi Token   : {tin:,}")
    print(f"Çıktı Token   : {tout:,}")
    print(f"Düşünce Token : {tth:,}")
    print(f"Toplam Token  : {(tin + tout):,}")
PYEOF
      exit 0 ;;
  --kurtar|--deploy|--recovery)
      $PY scripts/recovery_sentinel.py
      exit 0 ;;
  --canli|--dev)
      exec ./canli.sh ;;
  --test-izle)
      node scripts/tarayici_test_izle.mjs
      exit 0 ;;
  --incele|--review)
      $PY studio_engine.py --review
      exit 0 ;;
  --musteri|--talep|--talepler)
      exec ./musteri.sh "${@:2}" ;;
  --izle)   exec $PY studio_ctl.py ;;
  --web|--panel|--arayuz)
      exec $PY studio_web.py "${@:2}" ;;
  --onayla)
      $PY - "$@" <<'PYEOF'
import sys, studio_board as B
gorev = int(sys.argv[2]) if len(sys.argv) > 2 else None
d = B.ledger_approve(gorev=gorev)
mg, mb = B.ledger_limits()
print(f"✓ Onay verildi. Bugünkü kota: {d['gorev']}/{mg} görev, "
      f"${d['maliyet']:.2f}/${mb:.2f}")
print("  Başlatmak için: ./basla.sh")
PYEOF
      exit 0 ;;
  --durum)
      $PY - <<'PYEOF'
import json, pathlib, subprocess, time, os, sys
root = pathlib.Path(".")
lock = root / "workspace/.lock"
BOLD="\033[1m"; GREEN="\033[32m"; YELLOW="\033[33m"; RED="\033[31m"
CYAN="\033[36m"; DIM="\033[2m"; NC="\033[0m"; BLUE="\033[34m"

def bar(done, total, width=24):
    if total == 0: return "[" + "─"*width + "]"
    filled = int(width * done / total)
    return "[" + "█"*filled + "░"*(width-filled) + f"]"

# ── Process Kontrolü ──────────────────────────────────────────────────────────
pid = None
alive = False
if lock.exists():
    try:
        pid = int(lock.read_text().strip())
        os.kill(pid, 0)
        alive = True
    except (ValueError, OSError):
        pass

print()
print(f"{BOLD}{'─'*62}{NC}")
if alive:
    try:
        ps = subprocess.run(
            ["ps", "-o", "pid,%cpu,%mem,etime", "-p", str(pid)],
            capture_output=True, text=True
        )
        ps_lines = ps.stdout.strip().splitlines()
        if len(ps_lines) > 1:
            parts = ps_lines[1].split()
            cpu, mem, etime = parts[1], parts[2], parts[3]
            print(f"  {GREEN}●{NC} {BOLD}ÇALIŞIYOR{NC}  PID:{pid}  CPU:{cpu}%  RAM:{mem}%  Çalışma:{etime}")
    except Exception:
        print(f"  {GREEN}●{NC} {BOLD}ÇALIŞIYOR{NC}  PID:{pid}")
else:
    if lock.exists():
        print(f"  {RED}●{NC} {BOLD}DURDU{NC} {DIM}(lock takılı kaldı — ./basla.sh --sifirla önerilir){NC}")
    else:
        print(f"  {DIM}●  Boşta{NC}")

# ── Aktif Görev Detayı ───────────────────────────────────────────────────────
cur = {}
try:
    cur = json.loads((root/"workspace/.trace/current.json").read_text())
except Exception:
    pass

# Koşucu ölmüşse bayat 'started_at' sayacı gösterme; kesilme sebebini bas.
if cur.get("role") and (cur.get("ended_at") or cur.get("error") or not alive):
    ended = cur.get("ended_at") or cur.get("started_at") or time.time()
    kesildi = max(0, int(ended - cur.get("started_at", ended)))
    print(f"\n  {RED}✗ Son çağrı kesildi{NC}: {cur.get('task','?')} · {cur.get('role','?')}  "
          f"{DIM}({kesildi//60}dk {kesildi%60:02d}s sürdü){NC}")
    if cur.get("error"):
        print(f"  {DIM}sebep: {str(cur['error'])[:100]}{NC}")
    cur = {}

if cur.get("role"):
    elapsed = int(time.time() - cur.get("started_at", time.time()))
    el_m, el_s = elapsed // 60, elapsed % 60

    # Aynı role ait geçmiş ortalama süre
    avg_s = None
    idx_f = root/"workspace/.trace/index.jsonl"
    if idx_f.exists():
        rows = [json.loads(l) for l in idx_f.read_text().splitlines() if l.strip()]
        durations = [r["duration_s"] for r in rows
                     if r.get("duration_s") and r.get("role") == cur["role"]]
        if durations:
            avg_s = sum(durations) / len(durations)

    print(f"\n{BOLD}  ▸ Aktif Görev{NC}")
    print(f"  {'─'*58}")
    print(f"  {CYAN}Rol    {NC}: {BOLD}{cur['role']}{NC}  {DIM}({cur.get('title','')}){NC}")
    print(f"  {CYAN}Hedef  {NC}: {cur.get('target','?')}")
    print(f"  {CYAN}Sprint {NC}: {cur.get('sprint','?')} › {cur.get('task','?')}")
    print(f"  {CYAN}Model  {NC}: {cur.get('model','?')}  {DIM}({cur.get('effort','?')} effort){NC}")

    süre_str = f"{el_m}dk {el_s}s"
    if avg_s and elapsed > avg_s * 1.5:
        print(f"  {CYAN}Süre   {NC}: {YELLOW}{süre_str}  ⚠ Normalden uzun (ort. {int(avg_s)}s){NC}")
    elif avg_s:
        kalan = max(0, int(avg_s) - elapsed)
        kalan_str = f"{kalan//60}dk {kalan%60}s" if kalan > 0 else "bitiyor..."
        print(f"  {CYAN}Süre   {NC}: {süre_str}  {DIM}≈ {kalan_str} kaldı (ort. {int(avg_s)}s){NC}")
    else:
        print(f"  {CYAN}Süre   {NC}: {süre_str}")

    print(f"  {CYAN}Token  {NC}: {cur.get('prompt_chars',0):,} karakter")

    # ── Pipeline log: 429 / hata durumu ──────────────────────────────────────
    log_f = root / "workspace/logs/pipeline.log"
    if not log_f.exists():
        log_f = root / "pipeline.log"  # eski sürümden kalan kök logu
    if log_f.exists():
        log_lines = log_f.read_text(errors="replace").splitlines()
        # Son 60 satırda quota/hata ara
        son60 = log_lines[-60:]
        quota_lines = [l for l in son60 if "RESOURCE_EXHAUSTED" in l or "429" in l or "Kota/limit" in l]
        err_lines   = [l for l in son60 if "hata koduyla" in l.lower() or "ERROR" in l or "error:" in l.lower()]
        bekleme_lines = [l for l in son60 if "beklenip tekrar" in l]

        if quota_lines:
            # Kaç dakikadır bekleniyor?
            bekleme_sure = "?"
            for bl in reversed(bekleme_lines):
                import re
                m = re.search(r"(\d+)dk", bl)
                if m:
                    bekleme_sure = m.group(1) + "dk"
                    break
            print(f"\n  {BOLD}{'─'*58}{NC}")
            print(f"  {RED}⏸  API KOTASI DOLDU — 429 RESOURCE_EXHAUSTED{NC}")
            print(f"  {YELLOW}   Sistem 20s'de bir tekrar deniyor ({bekleme_sure} bekleniyor, maks 5sa){NC}")
            print(f"  {DIM}   Quota açılınca otomatik devam eder.{NC}")
            print(f"  {DIM}   Durdurmak için: ./basla.sh --durdur{NC}")
            print(f"  {BOLD}{'─'*58}{NC}")
        elif err_lines:
            last_err = err_lines[-1].strip()[:100]
            print(f"\n  {RED}⚠  Son hata:{NC} {DIM}{last_err}{NC}")

    # Canlı çıktının son satırları
    out_f = root/"workspace/.trace/current.out"
    if out_f.exists():
        content = out_f.read_text(errors="replace").strip()
        if content:
            son = [l for l in content.splitlines() if l.strip()][-3:]
            print(f"\n  {BOLD}Son çıktı:{NC}")
            for sat in son:
                print(f"  {DIM}│ {sat[:80]}{NC}")

# ── Sprint İlerlemesi ────────────────────────────────────────────────────────
p = None
try:
    import studio_board as B
    p = B.load()
except Exception:
    pass

if p and p.get("sprints"):
    try:
        sprints = p.get("sprints", [])
        total_s = len(sprints)
        done_s = sum(1 for s in sprints if s.get("status") == "DONE")
        all_tasks = [t for s in sprints for t in s.get("tasks", [])]
        total_t = len(all_tasks)
        done_t = sum(1 for t in all_tasks if t.get("status") in ("done", "DONE"))
        fail_t = sum(1 for t in all_tasks if t.get("status") in ("error", "failed", "FAILED"))

        print(f"\n{BOLD}  Sprint İlerlemesi (studio.db){NC}")
        print(f"  {'─'*58}")
        print(f"  Sprint  {bar(done_s, total_s)} {done_s}/{total_s}")
        print(f"  Görev   {bar(done_t, total_t)} {done_t}/{total_t}")
        if fail_t:
            print(f"  {RED}  ⚠  {fail_t} görev hatalı!{NC}")

        # Aktif sprint detayı
        aktif = next((s for s in sprints if s.get("status") in ("READY","RUNNING")), None)
        if aktif:
            tasks = aktif.get("tasks", [])
            done_st = sum(1 for t in tasks if t.get("status") in ("done", "DONE"))
            print(f"\n  {BOLD}Aktif:{NC} {aktif['id']} — {aktif.get('name','')[:45]}")
            print(f"         {bar(done_st, len(tasks), 16)} {done_st}/{len(tasks)}")
            for t in tasks:
                st = t.get("status","?")
                icon = (f"{GREEN}✓{NC}" if st in ("done", "DONE")
                        else f"{YELLOW}▸{NC}" if st in ("RUNNING","running","in_progress")
                        else f"{RED}✗{NC}" if st in ("error","failed","FAILED")
                        else f"{DIM}·{NC}")
                note = f" {DIM}{t.get('note','')[:35]}{NC}" if t.get("note") else ""
                dur = f" {DIM}{t.get('duration_s',0):.0f}s{NC}" if t.get("duration_s") else ""
                print(f"    {icon} {t['id']:<10} {t.get('title','')[:40]}{dur}{note}")

        # Bir sonraki sprint
        sonraki = next((s for s in sprints if s.get("status") == "TODO"), None)
        if sonraki:
            tasks = sonraki.get("tasks", [])
            print(f"\n  {DIM}Sıradaki: {sonraki['id']} — {sonraki.get('name','')[:42]}  ({len(tasks)} görev){NC}")
    except Exception as e:
        print(f"  {DIM}Pano okunurken hata: {e}{NC}")
else:
    print(f"  {DIM}Pano: henüz üretilmedi{NC}")

# ── Son Çağrı İstatistikleri ─────────────────────────────────────────────────
idx_f = root/"workspace/.trace/index.jsonl"
if idx_f.exists():
    rows = [json.loads(l) for l in idx_f.read_text().splitlines() if l.strip()]
    if rows:
        tot_cost = sum(r.get("cost_usd") or 0 for r in rows)
        tot_tok  = sum(r.get("tokens_total") or 0 for r in rows)
        avg_dur  = sum(r.get("duration_s") or 0 for r in rows) / len(rows)
        errors   = [r for r in rows if r.get("error")]
        last5    = rows[-5:]

        print(f"\n{BOLD}  Çağrı Özeti{NC}  {DIM}(toplam {len(rows)} çağrı){NC}")
        print(f"  {'─'*58}")
        print(f"  Maliyet:{DIM} ${tot_cost:.4f}{NC}   Token:{DIM} {tot_tok:,}{NC}   Ort.süre:{DIM} {avg_dur:.0f}s{NC}")
        if errors:
            print(f"  {RED}⚠  {len(errors)} hatalı çağrı{NC}")

        print(f"\n  {DIM}Son 5 çağrı:{NC}")
        for r in last5:
            dur  = r.get("duration_s", 0)
            tok  = r.get("tokens_in", 0)
            cost = r.get("cost_usd") or 0
            icon = f"{RED}✗{NC}" if r.get("error") else f"{GREEN}✓{NC}"
            err_hint = f" {RED}{str(r.get('error',''))[:30]}{NC}" if r.get("error") else ""
            print(f"    {icon} #{r['seq']:<4} {r.get('role','?'):<22} {dur:>5.0f}s  {tok:>8,}t{err_hint}")

# ── Kota ─────────────────────────────────────────────────────────────────────
try:
    import studio_board as B
    d = B.ledger_read(); mg, mb = B.ledger_limits()
    doldu = d["gorev"] >= mg or d["maliyet"] >= mb
    dolmak_uzere = d["gorev"] >= mg * 0.8
    kr = RED if doldu else (YELLOW if dolmak_uzere else GREEN)
    ds = "DOLDU — onay bekliyor" if doldu else ("Dolmak üzere" if dolmak_uzere else "açık")
    print(f"\n  {BOLD}Kota:{NC} {kr}bugün {d['gorev']}/{mg} görev  ${d['maliyet']:.2f}/${mb:.2f}  [{ds}]{NC}")
except Exception:
    pass

# ── Framework Güncelleme Bildirimi ───────────────────────────────────────────
try:
    import studio_board as B
    g = B.framework_update_info()
    if g and g.get("update"):
        print(f"\n  {YELLOW}⚠  Studio v{g['remote']} güncellemesi mevcut{NC} "
              f"{DIM}(kurulu v{g['local']}){NC}")
        for c in (g.get("changes") or [])[:4]:
            print(f"     {DIM}• {c[:84]}{NC}")
        print(f"  {CYAN}   İncele: python3 scripts/studio_updater.py --kontrol{NC}")
except Exception:
    pass

print(f"{BOLD}{'─'*62}{NC}")
print()
PYEOF
      exit 0 ;;
  --durdur)
      if ! calisiyor_mu; then ylw "Çalışan koşu yok."; exit 0; fi
      $PY -c "import studio_board as B; B.request('stop', kaynak='cli')"
      grn "Durdurma istendi — çalışan çağrı bitince koşucu çıkacak."
      dim "Hemen kesmek için: pkill -f studio_engine.py  (devam eden çağrının parası gider)"
      exit 0 ;;
  --oncelik|--sira|--sprint-sira|--gec|--atla)
      $PY - "$@" <<'PYEOF'
import sys
import studio_board as B

cmd = sys.argv[1]
args = [a for a in sys.argv[2:] if not a.startswith("--")]
force = "--force" in sys.argv[2:]

if cmd == "--oncelik":
    if len(args) < 2:
        sys.exit("Kullanım: ./basla.sh --oncelik <görev_id> <değer>")
    tid, deger = args[0], int(args[1])
    if not B.set_priority(tid, deger):
        sys.exit(f"Görev bulunamadı: {tid}")
    B.request("reload", kaynak="cli")
    print(f"✓ {tid} önceliği {deger} olarak ayarlandı (büyük = önce koşar).")

elif cmd == "--sira":
    if len(args) < 2:
        sys.exit("Kullanım: ./basla.sh --sira <görev_id> <pozisyon>")
    tid, poz = args[0], int(args[1])
    if not B.reorder_task(tid, poz):
        sys.exit(f"Görev bulunamadı: {tid}")
    B.request("reload", kaynak="cli")
    print(f"✓ {tid} sprint içinde {poz}. sıraya taşındı.")

elif cmd == "--sprint-sira":
    if len(args) < 2:
        sys.exit("Kullanım: ./basla.sh --sprint-sira <sprint_id> <pozisyon>")
    sid, poz = args[0], int(args[1])
    if not B.reorder_sprint(sid, poz):
        sys.exit(f"Sprint bulunamadı: {sid}")
    B.request("reload", kaynak="cli")
    print(f"✓ {sid} {poz}. sıraya taşındı.")

elif cmd == "--gec":
    if len(args) < 1:
        sys.exit("Kullanım: ./basla.sh --gec <görev_id> [--force]")
    tid = args[0]
    try:
        board = B.load()
    except Exception:
        sys.exit("Pano yok — önce ./basla.sh ile koşu başlatın.")
    s, t = B.find_task(board, tid)
    if t is None:
        sys.exit(f"Görev bulunamadı: {tid}")
    if t["status"] in B.TERMINAL:
        sys.exit(f"{tid} zaten kapalı ({t['status']}).")
    B.request("goto", tid, kaynak="cli")
    if force:
        B.request("force", kaynak="cli")
        print(f"✓ {tid} hedeflendi — çalışan çağrı anında kesilip bu göreve geçilecek.")
    else:
        print(f"✓ {tid} hedeflendi — mevcut çağrı bitince bu göreve geçilecek.")

elif cmd == "--atla":
    tid = args[0] if args else None
    if not tid:
        try:
            board = B.load()
            _, run = B.find_running(board)
            if run:
                tid = run["id"]
            else:
                _, t = B.next_ready(board)
                tid = t["id"] if t else None
        except Exception:
            tid = None
    if not tid:
        sys.exit("Atlanacak görev bulunamadı.")
    B.request("skip", tid, kaynak="cli")
    if force:
        B.request("force", kaynak="cli")
        print(f"✓ {tid} atlanacak — çalışan çağrı anında kesiliyor.")
    else:
        print(f"✓ {tid} atlanacak — mevcut çağrı bitince uygulanır.")
PYEOF
      exit 0 ;;
  --sifirla)
      if calisiyor_mu; then red "Önce koşuyu durdur: ./basla.sh --durdur"; exit 1; fi
      TS=$(date +%Y%m%d_%H%M%S)
      mkdir -p "_arsiv/$TS"
      for d in workspace/docs workspace/src workspace/tests; do
        [ -d "$d" ] && mv "$d" "_arsiv/$TS/" 2>/dev/null
      done
      # Panoyu arşivle (yedek) ve studio.db'den temizle
      $PY - "_arsiv/$TS" <<'PYEOF'
import json, pathlib, sys
import studio_board as B
try:
    board = B.db_load_board()
    if board and board.get("sprints"):
        pathlib.Path(sys.argv[1], "sprint_panosu_yedek.json").write_text(
            json.dumps(board, indent=2, ensure_ascii=False), encoding="utf-8")
except Exception:
    pass
B.board_reset()
PYEOF
      rm -f workspace/pano.json
      rm -f workspace/.state.json
      rm -rf workspace/.trace workspace/.control workspace/.stale
      grn "Sıfırlandı. Önceki çıktılar: _arsiv/$TS/"
      exit 0 ;;
esac

SADECE_KONTROL=0
[ "${1:-}" = "--kontrol" ] && SADECE_KONTROL=1

# ---------------------------------------------------------------- ön koşullar
echo "── Ön koşullar ──────────────────────────────"
HATA=0

if [ ! -x "$PY" ]; then
  ylw "· venv yok, kuruluyor..."
  python3 -m venv .venv || { red "✗ venv kurulamadı"; exit 1; }
fi
grn "✓ Python ortamı hazır"

# PATH'e ~/.local/bin ekle
export PATH="$HOME/.local/bin:$PATH"

# Model arka ucu kontrolü (STUDIO_BACKEND: agy | devin)
STUDIO_BACKEND="${STUDIO_BACKEND:-agy}"

if [ "$STUDIO_BACKEND" = "devin" ]; then
  DEVIN_EXE="$(command -v devin 2>/dev/null || true)"
  if [ -z "$DEVIN_EXE" ] && [ -x "$HOME/.local/bin/devin" ]; then
    DEVIN_EXE="$HOME/.local/bin/devin"
  fi
  if [ -z "$DEVIN_EXE" ] && [ -x "/Applications/Devin.app/Contents/Resources/app/extensions/windsurf/devin/bin/devin" ]; then
    DEVIN_EXE="/Applications/Devin.app/Contents/Resources/app/extensions/windsurf/devin/bin/devin"
  fi

  if [ -n "$DEVIN_EXE" ]; then
    grn "✓ devin bulundu ($DEVIN_EXE)"
    [ "${STUDIO_DEVIN_CLOUD:-0}" = "1" ] && dim "  · Devin Cloud oturumları etkin (STUDIO_DEVIN_CLOUD=1)"
    # Oturum kontrolü: token süresizdir; koşu ortasında patlamamak için erken uyar.
    if "$DEVIN_EXE" auth status 2>&1 | grep -qi "not logged in"; then
      red "✗ devin oturumu yok. Bir kez 'devin auth login' çalıştırın (token süresizdir)."; HATA=1
    else
      grn "✓ devin oturumu açık"
    fi
  else
    red "✗ devin bulunamadı. Lütfen Devin CLI'nın kurulu olduğundan emin olun (~/.local/bin/devin)"; HATA=1
  fi
else
  AGY_EXE="$(command -v agy 2>/dev/null || true)"
  if [ -z "$AGY_EXE" ] && [ -x "$HOME/.local/bin/agy" ]; then
    AGY_EXE="$HOME/.local/bin/agy"
  fi

  if [ -n "$AGY_EXE" ]; then
    grn "✓ agy bulundu ($AGY_EXE)"
  else
    red "✗ agy bulunamadı. Lütfen Antigravity CLI'nın kurulu olduğundan emin olun (~/.local/bin/agy)"; HATA=1
  fi
fi

if [ ! -f proje_kapsami.md ]; then
  red "✗ proje_kapsami.md yok"; HATA=1
elif grep -q "BURAYI DOLDUR" proje_kapsami.md; then
  ylw "! proje_kapsami.md'de doldurulmamış bölümler var — roller varsayım üretecek"
else
  grn "✓ Kapsam dokümanı hazır ($(wc -l < proje_kapsami.md | tr -d ' ') satır)"
fi

if calisiyor_mu; then
  PIDS=$(kosucu_pid)
  if [ "$SADECE_KONTROL" = "1" ]; then
    # Denetim modunda çalışan koşu sorun değil, bilgi.
    grn "✓ Koşu hâlihazırda çalışıyor (pid: $PIDS)"
    echo
    $0 --durum
    echo
    dim "İzlemek için: ./basla.sh --izle    Durdurmak için: ./basla.sh --durdur"
    exit 0
  fi
  ylw "! Zaten çalışan bir koşu var (pid: $PIDS) — ikinci koşucu başlatılmayacak."
  dim "  Aynı dosyalara iki süreç yazmasın diye engelleniyor."
  echo
  dim "  Kontrol ekranı açılıyor..."
  sleep 1
  exec $PY studio_ctl.py
fi

[ "$HATA" = "1" ] && { echo; red "Ön koşullar sağlanmadı."; exit 1; }

if [ "$SADECE_KONTROL" = "1" ]; then
  echo; grn "Her şey hazır. Başlatmak için: ./basla.sh"
  exit 0
fi

# ---------------------------------------------------------------- 1. Kurtarma ve Dağıtım Nöbetçisi (Failover & Deploy Sentinel)
$PY scripts/recovery_sentinel.py

# ---------------------------------------------------------------- 2. Müşteri Talepleri Senkronizasyonu
$PY - <<'PYEOF'
import sys
sys.path.insert(0, "scripts")
try:
    import studio_yetkilisi as SY
    eklenen = SY.otomatik_musteri_talepleri_senkronize_et()
    if eklenen > 0:
        print(f"  [✓] {eklenen} adet müşteri talebi algılandı ve sprint panosuna eklendi.")
except Exception as e:
    pass
PYEOF

# ---------------------------------------------------------------- çalıştır
echo
echo "── Başlatılıyor ─────────────────────────────"
dim "Aşama 1/2  tasarım rolleri → mimari, backlog, güvenlik, paket raporu, sprint panosu"
dim "Aşama 2/2  yapım görevleri → pano sırasına göre kod ve testler"
echo
$PY studio_engine.py --dry-run 2>&1 | grep -E "^\[i\] (Motor|[0-9]+ rol)" | sed 's/^/  /'
echo
dim "Log: $LOG    Durdurmak için kontrol ekranında 's'"
echo

# Arka plan sürecine mutlak komut yollarını ve backend ayarlarını geçir
export STUDIO_BACKEND="${STUDIO_BACKEND:-agy}"
export STUDIO_AGY_BIN="${AGY_EXE:-$HOME/.local/bin/agy}"
[ -n "${DEVIN_EXE:-}" ] && export STUDIO_DEVIN_BIN="$DEVIN_EXE"
mkdir -p "$(dirname "$LOG")"
nohup $PY studio_engine.py --full --yes ${STUDIO_BUTCE:+--max-cost $STUDIO_BUTCE} > "$LOG" 2>&1 &
PID=$!
sleep 2
if ! kill -0 "$PID" 2>/dev/null; then
  red "✗ Koşucu hemen düştü. Son satırlar:"; tail -15 "$LOG"; exit 1
fi
grn "✓ Koşucu çalışıyor (pid $PID)"
echo
dim "Kontrol ekranı açılıyor — çıkmak için 'q' (koşu arka planda devam eder)"
sleep 2
exec $PY studio_ctl.py
