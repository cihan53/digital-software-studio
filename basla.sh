#!/usr/bin/env bash
# ChyzTV Sanal Stüdyo — tek giriş noktası.
#
#   ./basla.sh              her şeyi sırayla çalıştırır ve kontrol ekranını açar
#   ./basla.sh --kontrol    hiçbir şey çalıştırmaz, sadece ön koşulları denetler
#   ./basla.sh --durdur     çalışan koşuyu nazikçe durdurur
#   ./basla.sh --izle       sadece kontrol ekranını açar
#   ./basla.sh --durum      tek satırlık durum özeti (ekran açmadan)
#
#   ./basla.sh --musteri    müşteri denetim masasını (istek/şikayet) açar
#   ./basla.sh --onayla     günlük kota dolduğunda bir tur daha izin ver
#   ./basla.sh --onayla 5   bugün için 5 görevlik ek kota tanı
#
#   Günlük varsayılan: 3 görev / 2 USD. Değiştirmek için:
#   STUDIO_GUNLUK_GOREV, STUDIO_GUNLUK_BUTCE
#   ./basla.sh --sifirla    ilerlemeyi sıfırlar (üretilmiş dosyalar arşive gider)
set -uo pipefail
cd "$(dirname "$0")" || exit 1

PY=".venv/bin/python"
LOG="pipeline.log"
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
      echo "── Antigravity Model Kotası ─────────────────────────"
      (agy -p="/usage" 2>/dev/null || ~/.local/bin/agy -p="/usage")
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
import json, pathlib, subprocess, time, os
root = pathlib.Path(".")
lock = root / "workspace/.lock"
alive = False
if lock.exists():
    try:
        pid = int(lock.read_text().strip())
        os.kill(pid, 0)
        alive = True
    except (ValueError, OSError):
        pass
print("Koşucu :", "ÇALIŞIYOR" if alive else "boşta")
try:
    st = json.loads((root/"workspace/.state.json").read_text())
    print("Roller :", ", ".join(st["completed_steps"]) or "(henüz yok)")
    print("Dosya  :", len(st["completed_outputs"]))
except FileNotFoundError:
    print("Roller : (henüz tamamlanan yok)")
cur = {}
try:
    cur = json.loads((root/"workspace/.trace/current.json").read_text())
except Exception:
    pass
if alive and cur.get("role"):
    el = int(time.time() - cur.get("started_at", time.time()))
    print(f"Şu an  : {cur['role']} -> {cur['target']}  ({el//60}dk {el%60}s)")
pano = root/"workspace/pano.json"
print("Pano   :", "var" if pano.exists() else "henüz üretilmedi (tasarım aşamasının sonunda çıkar)")
idx = root/"workspace/.trace/index.jsonl"
if idx.exists():
    rows = [json.loads(l) for l in idx.read_text().splitlines() if l.strip()]
    tot = sum(r.get("cost_usd") or 0 for r in rows)
    print(f"Harcama: ${tot:.2f} ({len(rows)} çağrı)")
import studio_board as B
d = B.ledger_read(); mg, mb = B.ledger_limits()
durum = "DOLDU — onay bekliyor" if (d["gorev"] >= mg or d["maliyet"] >= mb) else "açık"
print(f"Kota   : bugün {d['gorev']}/{mg} görev, ${d['maliyet']:.2f}/${mb:.2f}  [{durum}]")
PYEOF
      exit 0 ;;
  --durdur)
      if ! calisiyor_mu; then ylw "Çalışan koşu yok."; exit 0; fi
      $PY -c "import studio_board as B; B.request('stop')"
      grn "Durdurma istendi — çalışan çağrı bitince koşucu çıkacak."
      dim "Hemen kesmek için: pkill -f studio_engine.py  (devam eden çağrının parası gider)"
      exit 0 ;;
  --sifirla)
      if calisiyor_mu; then red "Önce koşuyu durdur: ./basla.sh --durdur"; exit 1; fi
      TS=$(date +%Y%m%d_%H%M%S)
      mkdir -p "_arsiv/$TS"
      for d in workspace/docs workspace/src workspace/tests; do
        [ -d "$d" ] && mv "$d" "_arsiv/$TS/" 2>/dev/null
      done
      [ -f workspace/pano.json ] && mv workspace/pano.json "_arsiv/$TS/"
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

# Antigravity CLI (agy) kontrolü
AGY_EXE="$(command -v agy 2>/dev/null || true)"
if [ -z "$AGY_EXE" ] && [ -x "$HOME/.local/bin/agy" ]; then
  AGY_EXE="$HOME/.local/bin/agy"
fi

if [ -n "$AGY_EXE" ]; then
  grn "✓ agy bulundu ($AGY_EXE)"
else
  red "✗ agy bulunamadı. Lütfen Antigravity CLI'nın kurulu olduğundan emin olun (~/.local/bin/agy)"; HATA=1
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

# Arka plan sürecine mutlak komut yollarını ve Antigravity ayarlarını geçir
export STUDIO_BACKEND="agy"
export STUDIO_AGY_BIN="${AGY_EXE:-$HOME/.local/bin/agy}"
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
