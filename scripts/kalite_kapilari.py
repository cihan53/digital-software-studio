#!/usr/bin/env python3
"""
scripts/kalite_kapilari.py
Digital Software Studio — Deterministik Kalite Kapıları (LLM kullanılmaz)

Görev sonrası makine-doğrulanabilir denetimler. Model çağırmaz, token harcamaz.

Alt komutlar:
    smoke            workspace/smoke_checklist.json kontrollerini koşturur
    regresyon        git diff'te kaldırılan fix/koruma referanslarını raporlar
    test-eslestirme  fix görevinde regresyon testi dosyası var mı denetler
    snapshot         git status --porcelain çıktısı üretir (görev öncesi anlık)
    degisenler FILE  snapshot dosyasına göre yeni değişen dosyaları listeler

Engine entegrasyonu (studio_engine.py):
    import kalite_kapilari as KK
    pre = KK.porcelain_snapshot()
    ... görev yürütülür ...
    notlar = KK.gorev_kapilari(task, pre)   # -> list[str]
"""

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT / "workspace"
CHECKLIST_FILE = WORKSPACE / "smoke_checklist.json"
UYARI_FILE = WORKSPACE / "docs" / "regresyon_uyarilari.md"

# ---------------------------------------------------------------------------
# Desenler
# ---------------------------------------------------------------------------

# Diff'te SİLİNEN satırlarda aranır: geçmiş hata düzeltmelerine / issue'lara
# yapılan referanslar ve "bunu koru" talimatları.
KORUMA_REF_RE = __import__("re").compile(
    r"(?i)("
    r"TALEP-\d+|ISSUE-\d+|BUG-\d+"
    r"|closes?\s+#\d+|fix(?:es|ed)?\s+#\d+|refs\s+#\d+"
    r"|regresyon|korunacak|asla\s+silme|silinmemeli"
    r"|do\s+not\s+(?:remove|delete)|do\s+not\s+touch|keep\s+this"
    r")"
)

# Bu dosyalar değiştiğinde dev/prod ortam eşliği riski doğar → smoke gate.
CONFIG_PATTERNS = (
    "nuxt.config", "vite.config", "next.config", ".htaccess",
    "docker-compose", "Dockerfile", "package.json", ".env",
    "nginx", "proxy", "Caddyfile", "wrangler.toml", "vercel.json",
)

# Fix + test eşleştirme: değişen dosyalarda bunlardan biri olmalı.
TEST_PATTERNS = (
    "/tests/", "/test/", "__tests__/",
    ".spec.", ".test.", "_test.", "test_",
)

# Görev başlığı/açıklamasında geçerse "fix görevi" sayılır.
FIX_KEYWORDS = (
    "fix", "düzelt", "hata", "bug", "onar", "sorun", "regresyon",
    "kırık", "bozuk", "çalışmıyor", "görünmüyor", "açılmıyor",
)


# ---------------------------------------------------------------------------
# Git yardımcıları
# ---------------------------------------------------------------------------

def _git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args, cwd=ROOT, capture_output=True, text=True, timeout=30
    )


def porcelain_snapshot() -> set[str]:
    """git status --porcelain satırlarının kümesi (görev öncesi anlık)."""
    res = _git(["status", "--porcelain"])
    if res.returncode != 0:
        return set()
    return {l for l in res.stdout.splitlines() if l.strip()}


def changed_files_since(before: set[str]) -> list[str]:
    """Snapshot'tan sonra durum değişen/yeni dosyalar."""
    after = porcelain_snapshot()
    files = []
    for line in sorted(after - before):
        path = line[3:].strip() if len(line) > 3 else line.strip()
        if " -> " in path:  # rename
            path = path.split(" -> ")[-1]
        path = path.strip('"')
        if path:
            files.append(path)
    return files


def _removed_lines(path: str) -> list[str]:
    """Çalışma ağacı + index'te, HEAD'e göre silinmiş satırlar."""
    removed = []
    for diff_args in (["diff", "HEAD", "--", path],):
        res = _git(diff_args)
        if res.returncode != 0:
            continue
        for line in res.stdout.splitlines():
            if line.startswith("-") and not line.startswith("---"):
                removed.append(line[1:].rstrip())
    return removed


# ---------------------------------------------------------------------------
# Kapı 1: Regresyon koruması — silinen fix/koruma referansları
# ---------------------------------------------------------------------------

def scan_removed_protection_refs(files: list[str]) -> list[str]:
    """Değişen dosyalarda silinmiş TALEP-XXX / issue / koruma referanslarını bulur."""
    findings = []
    for f in files:
        if not (ROOT / f).exists():
            continue  # silinen dosya — diff üretemeyiz
        for line in _removed_lines(f):
            m = KORUMA_REF_RE.search(line)
            if m:
                snippet = line.strip()[:110]
                findings.append(f"{f}: silinen koruma referansı [{m.group(1)}] → {snippet}")
    return findings


def has_test_file(files: list[str]) -> bool:
    low = [f.replace("\\", "/").lower() for f in files]
    return any(any(p in f for p in TEST_PATTERNS) for f in low)


def is_fix_task(task: dict) -> bool:
    if task.get("talep_id"):
        return True
    text = (task.get("title", "") + " " + task.get("description", "")).lower()
    return any(k in text for k in FIX_KEYWORDS)


def touches_config(files: list[str]) -> list[str]:
    low = {f.replace("\\", "/").lower(): f for f in files}
    hits = [orig for lf, orig in low.items()
            if any(p.lower() in lf for p in CONFIG_PATTERNS)]
    return hits


def uyarilari_dosyaya_yaz(task_id: str, basliklar: list[str]):
    """Regresyon/kalite bulgularını kalıcı denetim dosyasına ekler."""
    try:
        UYARI_FILE.parent.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        blok = [f"\n## [{task_id}] — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"]
        blok += [f"- {b}" for b in basliklar]
        with UYARI_FILE.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(blok) + "\n")
    except Exception as e:
        print(f"  [UYARI] regresyon_uyarilari.md yazılamadı: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Kapı 2: Smoke checklist (workspace/smoke_checklist.json)
# ---------------------------------------------------------------------------
# Şema:
# {
#   "checks": [
#     {"name": "...", "type": "http", "url": "http://...",
#      "status": 200, "contains": "...", "json_type": "list"},
#     {"name": "...", "type": "cmd", "command": "...", "expect_code": 0}
#   ]
# }

def _http_check(chk: dict) -> str | None:
    """None = geçti, str = hata mesajı."""
    url = chk["url"]
    req = urllib.request.Request(url, headers={"User-Agent": "studio-smoke/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=chk.get("timeout", 8)) as res:
            status = res.status
            body = res.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        status = e.code
        body = ""
    except Exception as e:
        return f"istek başarısız: {e}"

    expect = chk.get("status", 200)
    if status != expect:
        return f"HTTP {status} (beklenen {expect})"
    if "contains" in chk and chk["contains"] not in body:
        return f"gövde '{chk['contains']}' içermiyor"
    if "json_type" in chk:
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return "gövde geçerli JSON değil"
        want = {"list": list, "dict": dict}.get(chk["json_type"])
        if want and not isinstance(data, want):
            return f"JSON tipi {type(data).__name__} (beklenen {chk['json_type']})"
    return None


def _cmd_check(chk: dict) -> str | None:
    try:
        res = subprocess.run(
            chk["command"], shell=True, cwd=ROOT,
            capture_output=True, text=True,
            timeout=chk.get("timeout", 60), stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return f"komut {chk.get('timeout', 60)}s içinde bitmedi"
    expect = chk.get("expect_code", 0)
    if res.returncode != expect:
        tail = (res.stderr or res.stdout or "").strip().splitlines()
        detail = tail[-1][:120] if tail else ""
        return f"çıkış kodu {res.returncode} (beklenen {expect}) {detail}"
    if "contains" in chk and chk["contains"] not in (res.stdout or "") + (res.stderr or ""):
        return f"çıktı '{chk['contains']}' içermiyor"
    return None


def smoke_checklist() -> tuple[int, int, list[str]]:
    """(geçen, kalan, hata_mesajları). Checklist yoksa (0,0,[])."""
    if not CHECKLIST_FILE.exists():
        return (0, 0, [])
    try:
        checks = json.loads(CHECKLIST_FILE.read_text(encoding="utf-8")).get("checks", [])
    except Exception as e:
        return (0, 1, [f"smoke_checklist.json okunamadı: {e}"])

    passed, failed, failures = 0, 0, []
    for chk in checks:
        name = chk.get("name", chk.get("url") or chk.get("command") or "?")
        err = _http_check(chk) if chk.get("type") == "http" else _cmd_check(chk)
        if err:
            failed += 1
            failures.append(f"{name}: {err}")
        else:
            passed += 1
    return (passed, failed, failures)


# ---------------------------------------------------------------------------
# Birleşik görev kapısı — engine bunu çağırır
# ---------------------------------------------------------------------------

def gorev_kapilari(task: dict, pre_snapshot: set[str]) -> list[str]:
    """Görev sonrası deterministik kapılar. Dönen liste pano notuna eklenir."""
    notes = []
    files = changed_files_since(pre_snapshot)
    if not files:
        return notes

    # 1) Silinen koruma referansları
    findings = scan_removed_protection_refs(files)
    if findings:
        print(f"   ⚠️  [REGRESYON TARAMASI] {len(findings)} koruma referansı kaldırılmış:")
        for f_ in findings[:6]:
            print(f"         - {f_}")
        uyarilari_dosyaya_yaz(task.get("id", "?"), findings)
        notes.append(f"{len(findings)} koruma referansı kaldırıldı (regresyon_uyarilari.md)")

    # 2) Fix + regresyon testi eşleştirmesi
    if is_fix_task(task) and not has_test_file(files):
        msg = "fix görevi tamamlandı ama değişen dosyalarda test yok (regresyon testi eksik)"
        print(f"   ⚠️  [FIX+TEST KAPISI] {msg}")
        uyarilari_dosyaya_yaz(task.get("id", "?"), [msg + f" — dosyalar: {', '.join(files[:8])}"])
        notes.append("regresyon testi eksik")

    # 3) Config değişikliği veya test fazı → ortam eşliği smoke gate
    cfg = touches_config(files)
    is_test_phase = task.get("phase") == "test"
    if cfg:
        print(f"   🔧 [ORTAM EŞLİĞİ] Config dosyası değişti: {', '.join(cfg)}")
    if cfg or is_test_phase:
        passed, failed, failures = smoke_checklist()
        if passed + failed == 0:
            notes.append("smoke checklist tanımlı değil" if not cfg
                         else "config değişikliği — smoke checklist tanımlı değil")
        elif failed == 0:
            print(f"         ✅ Smoke checklist geçti ({passed}/{passed})")
            notes.append(f"smoke {passed}/{passed}")
        else:
            print(f"         ⚠️  Smoke checklist başarısız ({failed} hata):")
            for f_ in failures[:6]:
                print(f"             - {f_}")
            notes.append(f"smoke başarısız ({failed})")
    return notes


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli_smoke() -> int:
    passed, failed, failures = smoke_checklist()
    if passed + failed == 0:
        print("[i] workspace/smoke_checklist.json tanımlı değil — kapı atlandı.")
        return 0
    for f_ in failures:
        print(f"  ✗ {f_}")
    print(f"smoke: {passed} geçti, {failed} başarısız")
    return 1 if failed else 0


def _cli_regresyon(files: list[str]) -> int:
    if not files:
        files = changed_files_since(set())
    findings = scan_removed_protection_refs(files)
    for f_ in findings:
        print(f"  ⚠️  {f_}")
    print(f"regresyon taraması: {len(findings)} bulgu ({len(files)} dosya)")
    return 1 if findings else 0


def _cli_test_eslestirme(files: list[str]) -> int:
    if not files:
        files = changed_files_since(set())
    ok = has_test_file(files)
    print("test dosyası: " + ("VAR" if ok else "YOK") + f" ({len(files)} değişen dosya)")
    return 0 if ok else 1


def main():
    import argparse
    p = argparse.ArgumentParser(description="Deterministik kalite kapıları")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("smoke")
    r = sub.add_parser("regresyon"); r.add_argument("files", nargs="*")
    t = sub.add_parser("test-eslestirme"); t.add_argument("files", nargs="*")
    sub.add_parser("snapshot")
    d = sub.add_parser("degisenler"); d.add_argument("snapshot_file")

    args = p.parse_args()
    if args.cmd == "smoke":
        sys.exit(_cli_smoke())
    if args.cmd == "regresyon":
        sys.exit(_cli_regresyon(args.files))
    if args.cmd == "test-eslestirme":
        sys.exit(_cli_test_eslestirme(args.files))
    if args.cmd == "snapshot":
        print("\n".join(sorted(porcelain_snapshot())))
        return
    if args.cmd == "degisenler":
        before = set(Path(args.snapshot_file).read_text().splitlines())
        print("\n".join(changed_files_since(before)))
        return


if __name__ == "__main__":
    main()
