#!/usr/bin/env python3
"""
scripts/kalite_kapilari.py
Digital Software Studio — Deterministik Kalite Kapıları (LLM kullanılmaz)

Görev sonrası makine-doğrulanabilir denetimler. Model çağırmaz, token harcamaz.

Alt komutlar:
    smoke            workspace/smoke_checklist.json kontrollerini koşturur
    regresyon        git diff'te kaldırılan fix/koruma referanslarını raporlar
    test-eslestirme  fix görevinde regresyon testi dosyası var mı denetler
    hijyen           kırık symlink'leri temizler, sızan artefaktları raporlar
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
import re
import shutil
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
    res = _git(["status", "--porcelain", "-uall"])   # yeni dizin tek satıra çökmesin (#189)
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
# Kapı 4: Derleme/import doğrulaması — develop çıktısı gerçekten çalışıyor mu?
# ---------------------------------------------------------------------------
# 'Cannot find module ./geoSearch' sınıfı hatalar UAT'a kadar görünmez kalıyordu.
# Bu kapı görev kapanmadan önce deterministik olarak iki şeyi denetler:
#   a) Değişen kaynak dosyalardaki relative import/require yolları diskte
#      gerçekten bir dosyaya çözülüyor mu?
#   b) workspace/build_checklist.json tanımlıysa oradaki komutlar
#      (vue-tsc, tsc --noEmit, npm run build, flutter analyze ...) geçiyor mu?

BUILD_CHECKLIST_FILE = WORKSPACE / "build_checklist.json"

IMPORT_SPEC_RE = re.compile(
    r"""(?:from|import|require)\s*\(?\s*['"](\.[^'"]+)['"]""")

# Nuxt alias'ları (issue #241): '#shared/x', '~/x', '@/x', '~~/x', '@@/x' — yalnız uygulama dizininde nuxt.config.* varsa denetlenir
ALIAS_SPEC_RE = re.compile(
    r"""(?:from|import|require)\s*\(?\s*['"]((?:#shared|~~|~|@@|@)/[^'"]+)['"]""")

RESOLVE_EXTS = ("", ".ts", ".tsx", ".js", ".jsx", ".vue", ".mjs",
                ".json", ".css", ".scss", ".sass", ".less")
INDEX_FILES = tuple(f"index{e}" for e in
                    (".ts", ".tsx", ".js", ".jsx", ".vue"))

SRC_FILE_EXTS = (".ts", ".tsx", ".js", ".jsx", ".vue", ".mjs")


def _import_cozulur_mu(dosya_dir: Path, spec: str) -> bool:
    """'./geoSearch' gibi relative import'u dosya sisteminde çözmeyi dener."""
    base = dosya_dir / spec
    for ext in RESOLVE_EXTS:
        if Path(str(base) + ext).is_file():
            return True
    if base.is_dir() and any((base / idx).is_file() for idx in INDEX_FILES):
        return True
    return False


def _rel_veya_tam(p: Path) -> str:
    try:
        return str(Path(os.path.normpath(p)).relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(p)


def _uygulama_koku() -> Path | None:
    """Nuxt uygulama dizini (planlama.dizinler.uygulama, varsayılan workspace/src/web); nuxt.config.* yoksa None (alias denetimi yapılmaz)."""
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import studio_config as SC
        import uygulama_dizini as UD
        d = UD.dizin(SC.load_config(ROOT / "workspace" / "studio.config.json"))
    except Exception:
        d = "workspace/src/web"
    kok = ROOT / d
    return kok if kok.is_dir() and any(kok.glob("nuxt.config.*")) else None


def _alias_adaylari(kok: Path, spec: str) -> list[Path]:
    onek, _, geri = spec.partition("/")
    if onek == "#shared":
        return [kok / "shared" / geri]
    if onek in ("~~", "@@"):
        return [kok / geri]
    return [kok / "app" / geri, kok / geri]           # '~' ve '@': Nuxt 4 srcDir (app/), Nuxt 3 köküne geri düşer


def _alias_cozulur_mu(kok: Path, spec: str) -> bool:
    for base in _alias_adaylari(kok, spec):
        for ext in RESOLVE_EXTS:
            if Path(str(base) + ext).is_file():
                return True
        if base.is_dir() and any((base / idx).is_file() for idx in INDEX_FILES):
            return True
    return False


def betik_sozdizimi_hatalari(files: list[str]) -> list[str]:
    """Değişen .sh dosyaları `bash -n`, .mjs/.cjs dosyaları `node --check` ile denetlenir (#255)."""
    import shutil
    hatalar = []
    for f in files:
        p = ROOT / f
        if not p.is_file():
            continue
        if p.suffix in (".sh", ".bash") and shutil.which("bash"):
            cmd = ["bash", "-n", str(p)]
        elif p.suffix in (".mjs", ".cjs") and shutil.which("node"):
            cmd = ["node", "--check", str(p)]
        else:
            continue
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except (subprocess.TimeoutExpired, OSError):
            continue
        if r.returncode != 0:
            hatalar.append(f"{f}: sözdizimi hatası — {(r.stderr or r.stdout).strip().splitlines()[0][:200] if (r.stderr or r.stdout).strip() else ''}")
    return hatalar


def import_cozumleme_hatalari(files: list[str]) -> list[str]:
    """Değişen src dosyalarındaki çözülemeyen relative ve (Nuxt uygulamasında) alias import'larını döner."""
    hatalar = []
    kok = _uygulama_koku()
    for f in files:
        rel = f.replace("\\", "/")
        if not rel.endswith(SRC_FILE_EXTS):
            continue
        p = ROOT / rel
        if not p.is_file():
            continue
        try:
            metin = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for spec in set(IMPORT_SPEC_RE.findall(metin)):
            if not _import_cozulur_mu(p.parent, spec):
                hatalar.append(f"{rel}: '{spec}' çözülemedi (aranan: {_rel_veya_tam(p.parent / spec)}[.ts|.js|.vue|/index...])")
        if kok is not None:
            for spec in set(ALIAS_SPEC_RE.findall(metin)):
                if not _alias_cozulur_mu(kok, spec):
                    aranan = ", ".join(_rel_veya_tam(b) for b in _alias_adaylari(kok, spec))
                    hatalar.append(f"{rel}: '{spec}' çözülemedi (alias; aranan: {aranan}[.ts|.js|.vue|/index...])")
    return hatalar


def build_checklist() -> tuple[int, int, list[str]]:
    """workspace/build_checklist.json'daki derleme/doğrulama komutlarını koşturur.

    Şema:
    {"checks": [{"name": "frontend typecheck",
                 "command": "npx vue-tsc --noEmit",
                 "cwd": "workspace/src/frontend", "timeout_s": 180}]}
    """
    if not BUILD_CHECKLIST_FILE.exists():
        return (0, 0, [])
    try:
        checks = json.loads(BUILD_CHECKLIST_FILE.read_text(
            encoding="utf-8")).get("checks", [])
    except Exception as e:
        return (0, 1, [f"build_checklist.json okunamadı: {e}"])

    passed, failed, failures = 0, 0, []
    for chk in checks:
        name = chk.get("name", chk.get("command") or "?")
        cwd = ROOT / chk.get("cwd", ".")
        try:
            res = subprocess.run(chk.get("command", "true"), shell=True,
                                 cwd=cwd, capture_output=True, text=True,
                                 timeout=int(chk.get("timeout_s", 180)))
        except Exception as e:
            failed += 1
            failures.append(f"{name}: çalıştırılamadı ({e})")
            continue
        if res.returncode == 0:
            passed += 1
        else:
            failed += 1
            tail = (res.stdout + "\n" + res.stderr).strip().splitlines()
            failures.append(f"{name}: exit {res.returncode} — "
                            + " | ".join(tail[-4:])[:200])
    return (passed, failed, failures)


# ---------------------------------------------------------------------------
# Kapı 5: Çalışma alanı hijyeni + "çözüm kaynağa uygulandı mı" doğrulaması
# ---------------------------------------------------------------------------
# Saha gözlemleri:
#  a) Araçlı ajanlar workspace/ kökünde kırık symlink (göreli yol hatasıyla
#     'workspace/workspace/...' çift-yolu) ve sızıntı artefaktlar bırakıyor;
#     'git add -A' ile repoya sızıp ortamı bozuyorlar.
#  b) Geliştirici ajan düzeltmeyi raporunda anlatıp kaynak dosyaya hiç
#     yazmayabiliyor (TALEP-041 vakası): _CIKTI.md üretilir, kod değişmez.

# workspace/ kökünde bulunması şüpheli isimler — gerçek proje dosyaları
# workspace/src/ altında yaşar; kök yalnızca çalışma alanıdır.
SIZINTI_ISIM_RE = re.compile(
    r"(?i)^(package\.json|package-lock\.json|yarn\.lock|pnpm-lock\.yaml|"
    r"node_modules|composer\.(json|lock)|requirements\.txt|pyproject\.toml|"
    r"Gemfile(\.lock)?|go\.(mod|sum)|Cargo\.(toml|lock)|_CIKTI.*\.md|"
    r"test-results|playwright-report)$")

# workspace/src/ altında kaynak dosya sayılmayan üretim artefaktları
TEST_CIKTI_DIZINLERI = {"playwright-report", "test-results"}
SRC_ARTEFAKT_RE = re.compile(
    r"(?i)(^|/)_CIKTI[^/]*\.md$|(^|/)(test-results|playwright-report)(/|$)")

# Hijyen taramasında içine girilmeyen ağır/üretim dizinleri
_HIJYEN_SKIP = {"node_modules", ".git", ".nuxt", ".output", "dist", "build",
                ".history", ".stale", ".trace", "__pycache__", ".dart_tool"}


def _rel(p: Path) -> str:
    return str(p.relative_to(ROOT)).replace("\\", "/")


def _calisma_alani_tara() -> tuple[list[str], list[str]]:
    """workspace/ altında sığ tarama → (kırık symlink'ler, sızan artefaktlar).

    Git'ten bağımsız dosya sistemi taraması: gitignore'a takılan artefaktlar
    da yakalanır. Kök + 3 seviye iner (workspace/src/<alt>/<dosya> kapsanır),
    ağır üretim dizinlerine girilmez.
    """
    symlinks, artefakt = [], []
    if not WORKSPACE.is_dir():
        return symlinks, artefakt
    duzey = [WORKSPACE]
    for _ in range(4):
        yeni = []
        for d in duzey:
            try:
                cocuklar = list(d.iterdir())
            except OSError:
                continue
            for p in cocuklar:
                rel = _rel(p)
                if p.is_symlink():
                    if not p.exists():
                        symlinks.append(rel)
                    continue
                kalan = rel[len("workspace/"):]
                if "/" not in kalan and SIZINTI_ISIM_RE.match(p.name):
                    artefakt.append(rel)
                    continue
                if rel.startswith("workspace/src/") and SRC_ARTEFAKT_RE.search(rel):
                    artefakt.append(rel)
                    continue
                if p.is_dir() and p.name not in _HIJYEN_SKIP:
                    yeni.append(p)
        duzey = yeni
    return symlinks, artefakt


def calisma_alani_hijyeni(files: list[str] | None = None) -> tuple[list[str], list[str]]:
    """Çalışma alanı hijyen denetimi → (otomatik temizlenenler, bulgular).

    - Hedefsiz (kırık) symlink'ler hiçbir yere işaret etmediği için güvenle
      silinir ve 'temizlenen' olarak raporlanır.
    - workspace/ köküne veya workspace/src/ içine sızan artefaktlar
      (_CIKTI.md, test-results/, yabancı package.json/node_modules vb.)
      silinmez; yalnızca bulgu olarak raporlanır — kanıt veya kasıtlı
      dosya olabilirler.
    """
    temizlenen, bulgular = [], []

    kirli, artefakt = _calisma_alani_tara()
    for rel in kirli:
        try:
            (ROOT / rel).unlink()
            temizlenen.append(rel)
        except OSError as e:
            bulgular.append(f"{rel}: kırık symlink silinemedi ({e})")

    # Sızıntı adayları: dosya sistemi taraması + görev diff'inden gelenler.
    adaylar = set(artefakt)
    for f in files or []:
        rel = f.replace("\\", "/").rstrip("/")
        if not rel.startswith("workspace/"):
            continue
        kalan = rel[len("workspace/"):]
        if "/" not in kalan and SIZINTI_ISIM_RE.match(kalan):
            adaylar.add(rel)
        if SRC_ARTEFAKT_RE.search(rel):
            adaylar.add(rel)

    for rel in sorted(adaylar):
        p = ROOT / rel
        if rel in temizlenen or not (p.exists() or p.is_symlink()):
            continue
        # Yeniden üretilebilir test çıktı dizinleri (playwright-report, test-results) kaynak ağacında alarm değil temizlik konusudur (#239)
        if rel.startswith("workspace/src/") and p.is_dir() and not p.is_symlink() and p.name in TEST_CIKTI_DIZINLERI:
            try:
                shutil.rmtree(p)
                temizlenen.append(rel)
                continue
            except OSError as e:
                bulgular.append(f"{rel}: test çıktı dizini silinemedi ({e})")
                continue
        bulgular.append(f"{rel}: çalışma alanına sızan artefakt")
    return temizlenen, bulgular


def kaynak_degisti_mi(task: dict, files: list[str]) -> bool | None:
    """Develop görevi workspace/src hedefliyorsa gerçek kaynak değişikliği şart.

    True/False = kapı kararı; None = kapı bu göreve uygulanamaz.
    '_CIKTI.md' gibi çıktı artefaktları ve test raporu dizinleri kaynak
    değişikliği sayılmaz.
    """
    if task.get("phase") != "develop":
        return None
    outputs = [o.replace("\\", "/") for o in task.get("outputs", [])]
    if not any(o.startswith("workspace/src") for o in outputs):
        return None
    for f in files:
        rel = f.replace("\\", "/").rstrip("/")
        if rel.startswith("workspace/src/") and not SRC_ARTEFAKT_RE.search(rel):
            return True
    return False


# ---------------------------------------------------------------------------
# Birleşik görev kapısı — engine bunu çağırır
# ---------------------------------------------------------------------------

def gorev_kapilari(task: dict, pre_snapshot: set[str]) -> list[str]:
    """Görev sonrası deterministik kapılar. Dönen liste pano notuna eklenir."""
    notes = []
    files = changed_files_since(pre_snapshot)

    # 0a) Kaynak uygulandı mı — develop çıktısı yalnızca rapor/artefakt ise
    #     dosya listesi boş olsa bile yakala.
    if not task.get("onarim_muaf") and kaynak_degisti_mi(task, files) is False:
        msg = ("develop görevi workspace/src hedefliyor ama gerçek kaynak "
               "dosya değişmedi — çözüm yalnızca rapora/çıktı dokümanına "
               "yazılmış olabilir")
        print(f"   ⚠️  [KAYNAK KAPISI] {msg}")
        uyarilari_dosyaya_yaz(
            task.get("id", "?"),
            [msg + f" — dosyalar: {', '.join(files[:8]) or 'yok'}"])
        notes.append("kaynak uygulanmadı")

    # 0b) Çalışma alanı hijyeni — kırık symlink'ler temizlenir, sızan
    #     artefaktlar raporlanır (diff listesinden bağımsız çalışır).
    temizlenen, bulgular = calisma_alani_hijyeni(files)
    if temizlenen:
        print(f"   🧹 [HİJYEN] {len(temizlenen)} kırık symlink otomatik temizlendi:")
        for s in temizlenen[:6]:
            print(f"         - {s}")
        notes.append(f"hijyen: {len(temizlenen)} kırık symlink temizlendi")
    if bulgular:
        print(f"   ⚠️  [HİJYEN KAPISI] {len(bulgular)} sızan artefakt tespit edildi:")
        for b in bulgular[:6]:
            print(f"         - {b}")
        uyarilari_dosyaya_yaz(task.get("id", "?"), bulgular)
        notes.append(f"hijyen ihlali ({len(bulgular)})")

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

    # 3b) Betik sözdizimi (workspace/ altındaki .sh/.mjs/.cjs): bozuk betik görevi tamamlandı sayılmaz (#255)
    betikler = [f for f in files if f.replace("\\", "/").startswith("workspace/") and f.endswith((".sh", ".bash", ".mjs", ".cjs"))]
    if betikler:
        bsz = betik_sozdizimi_hatalari(betikler)
        if bsz:
            print(f"   ⚠️  [BETİK KAPISI] {len(bsz)} betikte sözdizimi hatası:")
            for f_ in bsz[:6]:
                print(f"         - {f_}")
            uyarilari_dosyaya_yaz(task.get("id", "?"), bsz)
            notes.append(f"derleme başarısız (betik {len(bsz)})")

    # 4) Develop çıktısı doğrulaması — kaynak dosya değiştiyse kod çalışmalı
    src_files = [f for f in files
                 if f.replace("\\", "/").startswith("workspace/src/")]
    if src_files:
        imp = import_cozumleme_hatalari(src_files)
        if imp:
            print(f"   ⚠️  [İMPORT KAPISI] {len(imp)} çözülemeyen import:")
            for f_ in imp[:6]:
                print(f"         - {f_}")
            uyarilari_dosyaya_yaz(task.get("id", "?"), imp)
            notes.append(f"derleme başarısız (import {len(imp)})")

        bp, bf, bfail = build_checklist()
        if bp + bf > 0:
            if bf == 0:
                print(f"         ✅ Build checklist geçti ({bp}/{bp})")
                notes.append(f"derleme {bp}/{bp}")
            else:
                print(f"         ⚠️  Build checklist başarısız ({bf} hata):")
                for f_ in bfail[:6]:
                    print(f"             - {f_}")
                uyarilari_dosyaya_yaz(task.get("id", "?"), bfail)
                notes.append(f"derleme başarısız ({bf})")
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


def _cli_hijyen() -> int:
    temiz, bulgu = calisma_alani_hijyeni(changed_files_since(set()))
    for s in temiz:
        print(f"  🧹 temizlendi: {s}")
    for b in bulgu:
        print(f"  ⚠️  {b}")
    print(f"hijyen: {len(temiz)} kırık symlink temizlendi, {len(bulgu)} bulgu")
    return 1 if bulgu else 0


def main():
    import argparse
    p = argparse.ArgumentParser(description="Deterministik kalite kapıları")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("smoke")
    r = sub.add_parser("regresyon"); r.add_argument("files", nargs="*")
    t = sub.add_parser("test-eslestirme"); t.add_argument("files", nargs="*")
    sub.add_parser("snapshot")
    sub.add_parser("hijyen")
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
    if args.cmd == "hijyen":
        sys.exit(_cli_hijyen())
    if args.cmd == "degisenler":
        before = set(Path(args.snapshot_file).read_text().splitlines())
        print("\n".join(changed_files_since(before)))
        return


if __name__ == "__main__":
    main()
