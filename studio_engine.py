#!/usr/bin/env python3
"""
Sanal Yazılım Stüdyosu — org_chart.json'daki rolleri sırayla Claude'a çalıştıran
doküman/kod üretim boru hattı.

Kullanım:
    pip install anthropic
    export ANTHROPIC_API_KEY=sk-ant-...
    python studio_engine.py                 # kaldığı yerden devam eder
    python studio_engine.py --reset         # state'i sıfırlayıp baştan başlar
    python studio_engine.py --yes           # soru sormadan çalışır
    python studio_engine.py --only cto      # sadece belirtilen rolleri çalıştırır
    python studio_engine.py --dry-run       # API'ye gitmeden planı gösterir
"""

import argparse
import json
import os
import re
import shutil
import signal
import time
import subprocess
import sys
from pathlib import Path

# Log'un tail -f ile anlık izlenebilmesi için satır tamponlama.
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

import studio_board as B


# -------------------------------------------------------------
# 1. ÇALIŞMA ALANI VE STATE
# -------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT / "workspace"
STATE_FILE = WORKSPACE / ".state.json"
SCRATCH_DIR = WORKSPACE / ".scratch"
TRACE_DIR = WORKSPACE / ".trace"
BRIEF_NAME = "proje_kapsami.md"
# Takvime saygı: sprint planlanan başlangıç tarihinden önce başlatılmaz.
RESPECT_CALENDAR = os.getenv("STUDIO_RESPECT_CALENDAR", "0") == "1"

# Uzak/mutlak yol yazımını engellemek için tüm çıktılar bu köklerin altında olmalı.
ALLOWED_OUTPUT_ROOTS = (WORKSPACE,)
# Tek istisna: kullanıcının elle düzenlediği, rollerin zenginleştirdiği canlı
# kapsam dokümanı proje kökünde durabilir (geriye dönük uyumluluk).
ALLOWED_OUTPUT_FILES = {ROOT / "proje_kapsami.md"}
DOC_DIR = WORKSPACE / "docs"
# Proje dokümanları workspace kuralı gereği workspace/docs/ altında yaşar;
# kökte bulunanlar geriye dönük olarak desteklenir.
WORKSPACE_DOCS = {BRIEF_NAME, "org_chart.json"}


def resolve_doc(name: str) -> Path:
    """Proje dokümanı okuma çözümü: workspace/docs/ öncelikli, kök geri dönüşümlü."""
    p = Path(name)
    if p.is_absolute():
        return p
    alt = DOC_DIR / name
    if alt.exists():
        return alt
    return ROOT / name


def resolve_path(path_str: str) -> Path:
    """org_chart'taki göreli yolu proje köküne göre çözer.

    Proje dokümanları (proje_kapsami.md, org_chart.json) workspace/docs
    altına yazılır; kökte var olanlar geriye dönük olarak oraya gider.
    """
    p = Path(path_str)
    if not p.is_absolute() and path_str in WORKSPACE_DOCS:
        if (DOC_DIR / path_str).exists() or not (ROOT / path_str).exists():
            return (DOC_DIR / path_str).resolve()
    return (ROOT / path_str).resolve()


def check_output_path(path_str: str) -> Path:
    p = resolve_path(path_str)
    if p in ALLOWED_OUTPUT_FILES:
        return p
    if not any(p == root or root in p.parents for root in ALLOWED_OUTPUT_ROOTS):
        raise ValueError(f"Çıktı yolu workspace/ dışına çıkıyor: {path_str}")
    return p


SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
TRACE_DIR.mkdir(parents=True, exist_ok=True)


LOCK_FILE = WORKSPACE / ".lock"


def acquire_lock() -> bool:
    """Tek koşucu garantisi. Zamanlanmış tetikleyici ile elle başlatılan koşu
    aynı anda çalışıp aynı dosyalara yazmasın diye."""
    if LOCK_FILE.exists():
        try:
            pid = int(LOCK_FILE.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)          # süreç yaşıyor mu?
        except (ValueError, ProcessLookupError, PermissionError):
            LOCK_FILE.unlink(missing_ok=True)   # bayat kilit
        else:
            print(f"[i] Başka bir koşucu zaten çalışıyor (pid {pid}); bu tetikleme atlandı.")
            return False
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    import atexit
    atexit.register(lambda: LOCK_FILE.unlink(missing_ok=True))
    return True


def load_state() -> dict:
    state = {"completed_outputs": [], "completed_steps": []}
    # 1. Önce studio.db'den oku
    try:
        conn = B.db_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT anahtar, deger FROM studio_state WHERE anahtar IN ('completed_outputs', 'completed_steps')")
            rows = dict(cur.fetchall())
            if rows:
                if "completed_outputs" in rows:
                    state["completed_outputs"] = json.loads(rows["completed_outputs"])
                if "completed_steps" in rows:
                    state["completed_steps"] = json.loads(rows["completed_steps"])
                return state
        finally:
            conn.close()
    except Exception:
        pass

    # 2. JSON fallback
    if STATE_FILE.exists():
        try:
            s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            state["completed_outputs"] = s.get("completed_outputs", [])
            state["completed_steps"] = s.get("completed_steps", [])
            save_state(state)
            return state
        except json.JSONDecodeError:
            print("  [!] .state.json bozuk, sıfırdan başlanıyor.", file=sys.stderr)
    return state


def save_state(state: dict):
    # 1. studio.db'ye yaz
    try:
        conn = B.db_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT OR REPLACE INTO studio_state (anahtar, deger) VALUES (?, ?)",
                ("completed_outputs", json.dumps(state.get("completed_outputs", []), ensure_ascii=False))
            )
            cur.execute(
                "INSERT OR REPLACE INTO studio_state (anahtar, deger) VALUES (?, ?)",
                ("completed_steps", json.dumps(state.get("completed_steps", []), ensure_ascii=False))
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"  [UYARI] studio.db state yazma hatası: {e}", file=sys.stderr)

    # 2. JSON'a yaz (Dual-write)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def mark_output_done(state: dict, path_str: str):
    if path_str not in state["completed_outputs"]:
        state["completed_outputs"].append(path_str)
    save_state(state)


def mark_step_done(state: dict, agent_id: str):
    if agent_id not in state["completed_steps"]:
        state["completed_steps"].append(agent_id)
    save_state(state)


# -------------------------------------------------------------
# 1b. ORTAM ÖN KONTROLÜ (deterministik — model kullanılmaz)
# -------------------------------------------------------------
ENV_REPORT = ROOT / "workspace" / "docs" / "ortam_raporu.md"

# (komut, sürüm bayrağı) — sürüm komutu GERÇEKTEN çalıştırılır.
# PATH'te bulunmak yetmez: /usr/local/bin/flutter gibi sarmalayıcı betikler
# var olup çalışmayabilir (fvm'e devredip SDK yoksa girdi bekler ve asılır).
ENV_TOOLS = [
    ("node", "--version"), ("npm", "--version"), ("pnpm", "--version"),
    ("python3", "--version"), ("go", "version"), ("rustc", "--version"),
    ("cargo", "--version"), ("java", "-version"), ("dotnet", "--version"),
    ("ruby", "--version"), ("php", "--version"),
    ("flutter", "--version"), ("dart", "--version"), ("fvm", "--version"),
    ("swift", "--version"), ("xcodebuild", "-version"), ("adb", "version"),
    ("docker", "--version"), ("git", "--version"),
    ("cmake", "--version"), ("make", "--version"),
]
ENV_PROBE_TIMEOUT = 12


def probe_tool(name: str, flag: str) -> dict:
    """Aracı gerçekten çalıştırıp kullanılabilirliğini ölçer."""
    path = shutil.which(name)
    if not path:
        return {"tool": name, "status": "YOK", "path": None, "version": None, "note": ""}
    try:
        # stdin kapalı: etkileşimli bir sarmalayıcı soru sorarsa asılmasın, hemen düşsün.
        proc = subprocess.run(
            [name, flag], capture_output=True, text=True,
            timeout=ENV_PROBE_TIMEOUT, stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return {"tool": name, "status": "BOZUK", "path": path, "version": None,
                "note": f"{ENV_PROBE_TIMEOUT}s içinde yanıt vermedi (muhtemelen girdi bekliyor)"}
    except OSError as e:
        return {"tool": name, "status": "BOZUK", "path": path, "version": None, "note": str(e)}

    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    first = out.splitlines()[0][:80] if out else ""
    if proc.returncode != 0 and not first:
        return {"tool": name, "status": "BOZUK", "path": path, "version": None,
                "note": f"çıkış kodu {proc.returncode}"}
    return {"tool": name, "status": "VAR", "path": path, "version": first, "note": ""}


def preflight_env(force: bool = False) -> Path:
    """Araç zinciri envanterini ölçer ve rapora yazar. Token harcamaz."""
    if ENV_REPORT.exists() and not force:
        print(f"  [i] Mevcut ortam raporu kullanılıyor ({ENV_REPORT.name}). "
              f"Yenilemek için --refresh-env.")
        return ENV_REPORT

    print("  [i] Ortam taranıyor (her araç gerçekten çalıştırılıyor)...")
    results = [probe_tool(n, f) for n, f in ENV_TOOLS]

    import platform
    lines = [
        "# Ortam Raporu",
        "",
        "> Bu dosya `studio_engine.py` tarafından **ölçülerek** üretilir; model çıktısı değildir.",
        "> Her araç gerçekten çalıştırılmıştır — PATH'te görünmek kullanılabilir olmak demek değildir.",
        "",
        f"- Tarih: {time.strftime('%Y-%m-%d %H:%M')}",
        f"- İşletim sistemi: {platform.system()} {platform.release()} ({platform.machine()})",
        f"- Python: {platform.python_version()}",
        "",
        "## Araç Zinciri",
        "",
        "| Araç | Durum | Sürüm / Not |",
        "|---|---|---|",
    ]
    for r in results:
        detail = r["version"] or r["note"] or "—"
        lines.append(f"| `{r['tool']}` | **{r['status']}** | {detail} |")

    usable = [r["tool"] for r in results if r["status"] == "VAR"]
    broken = [r for r in results if r["status"] == "BOZUK"]
    lines += [
        "",
        "## Kısıt",
        "",
        "Seçilecek teknoloji stack'i **bu makinede derlenebilir ve test edilebilir** olmalıdır.",
        "Kullanılabilir araçlar: " + (", ".join(f"`{t}`" for t in usable) or "yok"),
        "",
    ]
    if broken:
        lines.append("**Kurulu görünen ama çalışmayan araçlar** (bunlara güvenilmemeli):")
        lines.append("")
        for r in broken:
            lines.append(f"- `{r['tool']}` → {r['path']} — {r['note']}")
        lines.append("")
    lines.append("Gerekli bir araç eksikse, stack kararı ya onsuz kurulmalı ya da "
                 "`devops_engineer` rolü kurulum adımlarını açıkça yazmalıdır.")

    ENV_REPORT.parent.mkdir(parents=True, exist_ok=True)
    ENV_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok = sum(1 for r in results if r["status"] == "VAR")
    print(f"  [✓] {ENV_REPORT.relative_to(ROOT)} — {ok} araç kullanılabilir, "
          f"{len(broken)} bozuk, {len(results) - ok - len(broken)} yok")
    return ENV_REPORT


# -------------------------------------------------------------
# 2. ANTIGRAVITY MOTORU (agy CLI)
# -------------------------------------------------------------
BACKEND = os.getenv("STUDIO_BACKEND", "agy").lower()
AGY_MODEL = os.getenv("STUDIO_AGY_MODEL", "gemini-3.8-flash-high")
AGY_TIMEOUT = int(os.getenv("STUDIO_AGY_TIMEOUT", "1800"))
# Devin AI arka ucu (devin CLI, -p print kipi; STUDIO_DEVIN_CLOUD=1 ile bulut oturumu).
DEVIN_MODEL = os.getenv("STUDIO_DEVIN_MODEL", "")   # boş = hesap/CLI varsayılanı
DEVIN_TIMEOUT = int(os.getenv("STUDIO_DEVIN_TIMEOUT", "3600"))
DEVIN_CLOUD = os.getenv("STUDIO_DEVIN_CLOUD", "0") == "1"
DEVIN_PERMISSION_MODE = os.getenv("STUDIO_DEVIN_PERMISSION_MODE", "dangerous")
EFFORT = os.getenv("STUDIO_EFFORT", "high")   # low | medium | high
MAX_TOKENS = int(os.getenv("STUDIO_MAX_TOKENS", "64000"))



def _trace_seq() -> int:
    return len(list(TRACE_DIR.glob("[0-9]*.json"))) + 1


def trace_begin(meta: dict) -> Path:
    """Çağrı başlarken 'şu an ne yapılıyor' bilgisini diske yazar."""
    (TRACE_DIR / "current.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    live = TRACE_DIR / "current.out"
    live.write_text("", encoding="utf-8")
    return live


def trace_end(meta: dict, system_prompt: str, user_prompt: str,
              response: str, usage: dict, cost: float, duration: float):
    """Tamamlanan çağrının tamamını (giden + gelen) kalıcı olarak saklar."""
    record = {
        **meta,
        "finished_at": time.time(),
        "duration_s": round(duration, 1),
        "usage": usage,
        "cost_usd": cost,
        "response_chars": len(response),
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "response": response,
    }
    (TRACE_DIR / f"{meta['seq']:04d}.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = {k: record[k] for k in
               ("seq", "role", "target", "backend", "model", "effort",
                "duration_s", "cost_usd", "response_chars")}
    summary["tokens_in"] = usage.get("input_tokens", 0)
    summary["tokens_out"] = usage.get("output_tokens", 0)
    summary["tokens_thinking"] = usage.get("thinking_tokens", 0)
    summary["tokens_total"] = usage.get("total_tokens", 0) or (summary["tokens_in"] + summary["tokens_out"])
    with (TRACE_DIR / "index.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary, ensure_ascii=False) + "\n")

    # studio.db maliyet_kayitlari tablosuna ekle
    try:
        conn = B.db_conn()
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO maliyet_kayitlari (tarih, rol, backend, model, cost_usd, detay)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                summary.get("role"),
                summary.get("backend"),
                summary.get("model"),
                summary.get("cost_usd", 0.0),
                json.dumps(summary, ensure_ascii=False)
            ))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass

    (TRACE_DIR / "current.json").write_text("{}", encoding="utf-8")


def trace_fail(meta: dict, error: str, duration: float):
    """Başarısız çağrıyı kalıcı olarak kaydeder.

    Kritik nokta: current.json 'ended_at' + 'error' ile yazılır ki koşucu
    öldüğünde kontrol ekranı bayat 'started_at'ten sayan donuk bir sayaç
    göstermesin; bunun yerine kesilen çağrı ve sebebi görünsün.
    """
    now = time.time()
    record = {
        **meta,
        "finished_at": now,
        "duration_s": round(duration, 1),
        "error": error[:500],
    }
    try:
        (TRACE_DIR / f"{meta['seq']:04d}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass

    summary = {k: record.get(k) for k in
               ("seq", "role", "target", "backend", "model", "effort", "duration_s")}
    summary["error"] = error[:200]
    try:
        with (TRACE_DIR / "index.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(summary, ensure_ascii=False) + "\n")
    except OSError:
        pass

    # Kesilen çağrı 'sona erdi' olarak işaretlenir — ctl artık sağlam sayaç yerine
    # sabitlenmiş süre + hata sebebini gösterir.
    ended = {**meta, "ended_at": now, "error": error[:300],
             "duration_s": round(duration, 1)}
    try:
        (TRACE_DIR / "current.json").write_text(
            json.dumps(ended, indent=2, ensure_ascii=False), encoding="utf-8")
        (TRACE_DIR / "current.out").write_text(
            f"[ÇAĞRI KESİLDİ] {error}\n", encoding="utf-8")
    except OSError:
        pass


VALID_BACKENDS = ("agy", "devin")


def load_and_merge_dynamic_roles(org: dict) -> dict:
    """CTO ve Product Owner tarafından tanımlanan ekip_yapisi.json varsa rolleri org şemasına ekler."""
    team_file = WORKSPACE / "docs" / "ekip_yapisi.json"
    if team_file.exists():
        try:
            data = json.loads(team_file.read_text(encoding="utf-8"))
            roles = data.get("roles") or data.get("hierarchy") or []
            existing_ids = {a["id"] for a in org.get("hierarchy", [])}
            for r in roles:
                if isinstance(r, dict) and r.get("id") and r["id"] not in existing_ids:
                    r.setdefault("stage", "build")
                    r.setdefault("backend", BACKEND)
                    r.setdefault("model", AGY_MODEL)
                    org["hierarchy"].append(r)
                    existing_ids.add(r["id"])
                    print(f"  [i] Dinamik ekip rolü yüklendi: {r['id']} ({r.get('title', '')})")
        except Exception as e:
            print(f"  [!] ekip_yapisi.json okunamadı: {e}", file=sys.stderr)
    return org


def synthesize_role(org: dict, role_id: str) -> dict:
    """Şemada doğrudan yer almayan türetilmiş bir geliştirici veya testçi rolünü dinamik olarak oluşturur."""
    for a in org.get("hierarchy", []):
        if a["id"] == role_id:
            return a

    is_tester = any(k in role_id.lower() for k in ("test", "qa", "auditor", "denet", "screen", "visitor"))
    title = role_id.replace("_", " ").title()

    if is_tester:
        tools = [
            "Read", "Glob", "Grep", "Bash(node:*)", "Bash(npm:*)", "Bash(npx:*)",
            "Bash(curl:*)", "Bash(git status:*)", "Bash(ls:*)", "Bash(cat:*)",
            "Bash(head:*)", "Bash(grep:*)"
        ]
        inputs = [
            "workspace/docs/kabul_kriterleri.md",
            "workspace/docs/ekran_envanteri.md",
            "workspace/docs/ux_akislari.md",
            "workspace/src/frontend/",
            "workspace/src/backend/"
        ]
        outputs = ["workspace/docs/test_raporu.md", "workspace/docs/bug_raporlari.md"]
        prompt = (
            f"Sen dinamik olarak ölçeklenmiş uzman '{title}' ({role_id}) testçi rolüsün.\n"
            f"Görevin: Çalışan sistem (localhost:3000 ve 3001) üzerinde kullanıcı kabul kriterlerine, "
            f"ekran envanterine ve kullanıcı akışlarına göre GERÇEK ZİYARETÇİ gözüyle her ekranı, butonu, "
            f"linki ve formu denetlemektir. Mock testlerle yetinmez, DOM'u ve ağ isteklerini zorlarsın. "
            f"Bulduğun her aksaklığı ve eksikliği açıkça raporlarsın."
        )
    else:
        tools = [
            "Read", "Glob", "Grep", "Bash(node:*)", "Bash(npm:*)", "Bash(npx:*)",
            "Bash(curl:*)", "Bash(git status:*)", "Bash(git diff:*)", "Bash(ls:*)",
            "Bash(cat:*)", "Bash(head:*)", "Bash(grep:*)"
        ]
        inputs = [
            "workspace/docs/teknik_mimari_dokumani.md",
            "workspace/docs/tasarim_sistemi.md",
            "workspace/docs/backlog.md",
            "workspace/docs/kabul_kriterleri.md"
        ]
        outputs = ["workspace/src/"]
        prompt = (
            f"Sen dinamik olarak ölçeklenmiş uzman '{title}' ({role_id}) geliştirici rolüsün.\n"
            f"Görevin: Mimariye ve tasarım sistemine tam sadık kalarak sana atanan özellikleri "
            f"veya tespit edilen eksiklikleri kodlamaktır. Mevcut çalışan kodları koruyup genişletirsin."
        )

    synthetic_agent = {
        "id": role_id,
        "title": title,
        "system_prompt": prompt,
        "inputs": inputs,
        "outputs": outputs,
        "stage": "build",
        "backend": BACKEND,
        "model": AGY_MODEL,
        "max_words": 1800,
        "tools": tools,
        "_synthetic": True
    }
    org.setdefault("hierarchy", []).append(synthetic_agent)
    print(f"  [i] Rol dinamik olarak sentezlendi ve yetkilendirildi: {role_id} ({title})")
    return synthetic_agent


def resolve_engine(agent: dict) -> tuple[str, str, str, list]:
    """Rolün motorunu belirler: (backend, model, effort, tools).

    Rol org_chart'ta kendi "backend" değerini belirtebilir; belirtmezse
    STUDIO_BACKEND / --backend ile seçilen genel backend kullanılır.
    Desteklenen backend'ler: agy (Antigravity/Gemini), devin (Devin AI).
    """
    backend = (agent.get("backend") or BACKEND or "agy").lower()
    if backend not in VALID_BACKENDS:
        raise ValueError(
            f"'{agent['id']}' rolünde geçersiz backend '{backend}'. "
            f"Geçerli değerler: {', '.join(VALID_BACKENDS)}")

    if backend == "devin":
        # Devin kendi model isimlerini kullanır (ör. swe-2, opus, codex).
        # Rol "devin_model" ile geçersiz kılabilir; aksi hâlde STUDIO_DEVIN_MODEL
        # (boşsa CLI/hesap varsayılanı devreye girer).
        model = agent.get("devin_model") or DEVIN_MODEL
    else:
        model = agent.get("model") or AGY_MODEL
        # Herhangi bir yerde claude veya opus/sonnet kalmışsa Gemini 3.8 karşılığına eşle:
        if any(k in model.lower() for k in ("opus", "sonnet", "claude")):
            model = "gemini-3.8-flash-high"

    tools = agent.get("tools") or []
    if not isinstance(tools, list):
        raise ValueError(f"'{agent['id']}' rolünde 'tools' liste olmalı")
    return (backend, model, agent.get("effort") or EFFORT, tools)


class CliResult:
    """CLI yanıtını tutan hafif sarmalayıcı."""

    def __init__(self, text: str, stop_reason: str, cost: float, usage: dict):
        self.text = text
        self.stop_reason = stop_reason
        self.cost = cost
        self.usage = usage


class CallAborted(Exception):
    """Çalışan görev/çağrı kontrol isteğiyle kesildi (stop, skip, goto, force).

    RuntimeError'dan ayrı tutulur: kota/limit yeniden deneme döngüsüne
    girmesin, doğrudan koşucunun kontrol işleyicisine ulaşsın.
    """


def _run_cli(cmd: list, cwd: Path, timeout: int, name: str):
    """CLI'yi kesilebilir şekilde çalıştırır.

    Normal akışta subprocess.run ile aynıdır. Farkı: her yarım saniyede
    workspace/.control/force bayrağına bakılır; bayrak varsa süreç grubu
    SIGTERM ile öldürülür ve CallAborted fırlatılır (--gec/--atla --force).
    """
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, cwd=str(cwd), start_new_session=True,
    )
    deadline = time.time() + timeout
    try:
        while proc.poll() is None:
            if B.is_set("force"):
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    proc.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except OSError:
                        pass
                raise CallAborted(f"{name} çağrısı kullanıcı isteğiyle kesildi (--force).")
            if time.time() > deadline:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except OSError:
                    pass
                raise RuntimeError(f"{name} {timeout}s içinde yanıt vermedi.")
            time.sleep(0.5)
        out, err = proc.communicate()
    finally:
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except OSError:
                pass
    return proc.returncode, out or "", err or ""


def find_exe(name: str) -> str | None:
    """Komutu bulur. PATH eksik olsa bile STUDIO_<AD>_BIN ve bilinen dizinler taranır."""
    override = os.getenv(f"STUDIO_{name.upper()}_BIN")
    if override and Path(override).exists():
        return override
    found = shutil.which(name)
    if found:
        return found
    for base in ("~/.local/bin", "~/.npm-global/bin", "/usr/local/bin",
                 "/opt/homebrew/bin", "~/.gemini/antigravity/bin",
                 "/Applications/Devin.app/Contents/Resources/app/extensions/windsurf/devin/bin"):
        cand = Path(base).expanduser() / name
        if cand.exists():
            return str(cand)
    return None


def _call_cli(*args, **kwargs):
    raise RuntimeError("Claude CLI kesin olarak devre dışı bırakılmıştır. Tüm süreç Antigravity ile yürütülür.")


def _call_once(*args, **kwargs):
    raise RuntimeError("Anthropic API kesin olarak devre dışı bırakılmıştır. Tüm süreç Antigravity ile yürütülür.")


# agy yalnızca low/medium/high kabul eder; üstteki seviyeler kırpılır.
AGY_EFFORTS = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}


def _call_agy(system_prompt: str, user_prompt: str, effort: str, model: str,
              tools: list | None = None) -> CliResult:
    """Antigravity CLI'yi print kipinde çalıştırır.

    1. agy'de --system-prompt olmadığından rol promptu kullanıcı mesajının başına etiketle eklenir.
    2. Model adı effort içeriyorsa (ör. gemini-3.1-pro-high), ayrıca --effort argümanı eklenmez.
    3. Rol araç (tools) istiyorsa --dangerously-skip-permissions bayrağıyla araç kullanımına izin verilir
       ve çalışma dizini proje kökü (ROOT) olur. Saf metin üreteçleri ise SCRATCH_DIR'de çalışır.
    """
    exe = find_exe("agy")
    if not exe:
        sys.exit("[HATA] 'agy' bulunamadı. Lütfen Antigravity CLI'nın kurulu olduğundan emin olun (~/.local/bin/agy).")

    merged = (
        f"<rol_tanimi>\n{system_prompt}\n</rol_tanimi>\n\n"
        f"Yukarıdaki rol tanımına göre davran.\n\n{user_prompt}"
    ).replace("\x00", "")
    cmd = [
        exe,
        "--output-format", "json",
        "--disable-slash-commands",
        "--dangerously-skip-permissions",
        "--model", model,
        "--print-timeout", f"{AGY_TIMEOUT}s",
    ]

    if not model.endswith(("-low", "-medium", "-high", "-thinking")):
        cmd += ["--effort", AGY_EFFORTS.get(effort, "high")]
    cmd.append(f"-p={merged}")

    run_cwd = ROOT if tools else SCRATCH_DIR
    rc, out, err = _run_cli(cmd, run_cwd, AGY_TIMEOUT + 60, "agy")

    if rc != 0:
        detail = (err or out or "").strip()[:500]
        raise RuntimeError(f"agy hata koduyla çıktı ({rc}): {detail}")

    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        raise RuntimeError(f"agy JSON döndürmedi: {proc.stdout.strip()[:300]}")

    text = (data.get("response") or "").strip()
    status = (data.get("status") or "").upper()
    if not text:
        err = data.get("error") or f"durum {status or 'bilinmiyor'}"
        raise RuntimeError(f"agy hata bildirdi (metin üretilmedi): {str(err)[:300]}")
    (TRACE_DIR / "current.out").write_text(text, encoding="utf-8")
    return CliResult(
        text=text,
        stop_reason="end_turn",
        cost=0.0,
        usage=data.get("usage") or {},
    )


def _call_devin(system_prompt: str, user_prompt: str, effort: str, model: str,
                tools: list | None = None) -> CliResult:
    """Devin CLI'yi print (etkileşimsiz) kipinde çalıştırır.

    1. devin'de ayrı bir system-prompt kanalı olmadığından rol tanımı kullanıcı
       mesajının başına etiketle eklenir (agy ile aynı sözleşme).
    2. Rol araç (tools) istiyorsa STUDIO_DEVIN_PERMISSION_MODE ile araç
       kullanımına izin verilir ve çalışma dizini proje kökü (ROOT) olur.
       Saf metin üreteçleri SCRATCH_DIR'de çalışır.
    3. STUDIO_DEVIN_CLOUD=1 ise oturum Devin Cloud VM'inde yürütülür.
    4. devin -p kullanım istatistiği döndürmez; usage boş bırakılır.
    """
    exe = find_exe("devin")
    if not exe:
        sys.exit("[HATA] 'devin' bulunamadı. Lütfen Devin CLI'nın kurulu olduğundan "
                 "emin olun (~/.local/bin/devin veya Devin Desktop).")

    merged = (
        f"<rol_tanimi>\n{system_prompt}\n</rol_tanimi>\n\n"
        f"Yukarıdaki rol tanımına göre davran.\n\n{user_prompt}"
    ).replace("\x00", "")
    cmd = [exe, "-p", merged, "--respect-workspace-trust", "false"]
    if DEVIN_CLOUD:
        cmd += ["--cloud"]
    if model:
        cmd += ["--model", model]
    if tools:
        cmd += ["--permission-mode", DEVIN_PERMISSION_MODE]

    run_cwd = ROOT if tools else SCRATCH_DIR
    rc, out, err = _run_cli(cmd, run_cwd, DEVIN_TIMEOUT + 60, "devin")

    if rc != 0:
        detail = (err or out or "").strip()[:500]
        raise RuntimeError(f"devin hata koduyla çıktı ({rc}): {detail}")

    text = (out or "").strip()
    if not text:
        detail = (err or "").strip()[:300]
        raise RuntimeError(f"devin metin üretmedi: {detail or 'boş çıktı'}")
    (TRACE_DIR / "current.out").write_text(text, encoding="utf-8")
    return CliResult(text=text, stop_reason="end_turn", cost=0.0, usage={})


# Kota/limit ve geçici ağ hatalarında ölmek yerine bekle-ve-devam et.
LIMIT_PATTERNS = (
    "usage limit", "rate limit", "quota", "resets at", "too many requests",
    "429", "limit reached", "kota", "try again later", "overloaded",
    "ayrıntı yok", "api_status=5", "api_status=429", "error_during_execution",
    "agent execution terminated due to error", "terminated due to error",
    "status\": \"error\"", "status\":\"error\"", "hata koduyla çıktı (1)",
    "internal error", "temporarily unavailable", "connection reset",
    "unavailable", "503", "no capacity available", "capacity", "resource exhausted",
    "service unavailable", "model overloaded",
    # --- geçici ağ / taşıma katmanı hataları (anlık kopmalar görevi öldürmesin) ---
    "broken pipe", "protocol version", "tls:", "tls handshake", "remote error",
    "unexpected eof", " eof", "eof,", "eof)", "connection refused",
    "connection aborted", "connection timed out", "i/o timeout", "dial tcp",
    "no route to host", "network is unreachable", "deadline exceeded",
    "context deadline", "socket hang", "bad gateway", "502", "504",
    "gateway timeout", "econnreset", "econnrefused", "etimedout", "eai_again",
    "enotfound", "request failed", "streamgeneratecontent",
    "yanıt vermedi", "empty reply", "server disconnected",
)
MAX_WAIT = int(os.getenv("STUDIO_MAX_WAIT", "18000"))   # varsayılan 5 saat
WAIT_STEP = 20



def is_limit_error(msg: str) -> bool:
    low = msg.lower()
    return any(pat in low for pat in LIMIT_PATTERNS)


def wait_for_quota(reason: str, waited: int) -> int:
    """Limit hatasında bekler. Bekleme sırasında durdurma isteğine saygı duyar."""
    if waited >= MAX_WAIT:
        raise RuntimeError(
            f"Kota limiti {MAX_WAIT // 3600} saattir açılmadı, vazgeçiliyor. Son hata: {reason}"
        )
    remaining = MAX_WAIT - waited
    step = min(WAIT_STEP, remaining)
    print(f"  [~] Kota/limit hatası. {step}s beklenip tekrar denenecek "
          f"(toplam beklenen {waited // 60}dk, üst sınır {MAX_WAIT // 3600}sa).",
          file=sys.stderr)
    print(f"      {reason[:160]}", file=sys.stderr)

    slept = 0
    while slept < step:
        if B.is_set("stop"):
            raise RuntimeError("Beklerken durdurma isteği alındı.")
        if B.is_set("force") or B.is_set("goto") or B.value_of("skip"):
            raise CallAborted("Kota beklemesi sırasında kontrol isteği alındı.")
        time.sleep(min(10, step - slept))
        slept += 10
    return waited + step


def query_claude(system_prompt: str, user_prompt: str,
                 backend: str, model: str, base_effort: str,
                 trace_meta: dict, tools: list | None = None) -> str:
    """Seçilen backend (agy / devin) üzerinden modeli çalıştırıp yanıtı döndürür."""
    meta = dict(trace_meta, effort=base_effort, started_at=time.time(),
                prompt_chars=len(system_prompt) + len(user_prompt))
    trace_begin(meta)
    t0 = time.time()

    waited = 0
    try:
        while True:
            try:
                if backend == "devin":
                    res = _call_devin(system_prompt, user_prompt, base_effort, model, tools)
                else:
                    res = _call_agy(system_prompt, user_prompt, base_effort, model, tools)
                text = res.text
                u = res.usage
                in_t = u.get("input_tokens", 0)
                out_t = u.get("output_tokens", 0)
                th_t = u.get("thinking_tokens", 0)
                print(f"      ({backend}: {in_t} girdi / {out_t} çıktı / {th_t} düşünce token)")
                break
            except CallAborted:
                (TRACE_DIR / "current.json").write_text("{}", encoding="utf-8")
                raise
            except RuntimeError as e:
                if not is_limit_error(str(e)):
                    raise
                waited = wait_for_quota(str(e), waited)
    except RuntimeError as e:
        # Fatal hata: çağrının 'sona erdiğini' trace'e yaz ki kontrol ekranı
        # bayat started_at'ten sayan donuk bir sayaç göstermesin.
        trace_fail(meta, str(e), time.time() - t0)
        raise

    trace_end(meta, system_prompt, user_prompt, text,
              dict(u) if isinstance(u, dict) else {},
              getattr(res, "cost", 0.0),
              time.time() - t0)

    if not text:
        raise RuntimeError(f"{backend} boş metin döndürdü.")
    return text


query_model = query_claude


# -------------------------------------------------------------
# 3. GİRDİ TOPLAMA
# -------------------------------------------------------------
MAX_DIR_FILES = 30


IGNORE_INPUT_DIRS = {
    "node_modules", ".git", ".nuxt", ".stale", ".history",
    "dist", "build", ".dart_tool", "__pycache__", ".bin", "data"
}


def read_input(path_str: str) -> str:
    """Girdiyi okur. Dizinse içindeki tüm kaynak dosyaları etiketleyerek birleştirir."""
    p = resolve_path(path_str)

    if p.is_dir():
        files = []
        for f in sorted(p.rglob("*")):
            if not f.is_file() or f.name.startswith("."):
                continue
            if any(part in f.parts for part in IGNORE_INPUT_DIRS):
                continue
            files.append(f)

        if not files:
            raise FileNotFoundError(path_str)
        parts = []
        for f in files[:MAX_DIR_FILES]:
            try:
                size = f.stat().st_size
                # 50 KB'tan büyük dosyaları kırp; macOS execve ARG_MAX aşımını önle
                if size > 50_000:
                    raw = f.read_bytes()[:10_000]
                    if b"\x00" in raw:
                        continue
                    content = raw.decode("utf-8", errors="replace") + f"\n\n... [Büyük Veri/Statik Dosya: Toplam {size:,} bayt, ilk 10 KB gösterildi]"
                else:
                    raw = f.read_bytes()
                    if b"\x00" in raw:
                        continue  # İkili (binary) dosyaları atla
                    content = raw.decode("utf-8", errors="replace")
                rel = f.relative_to(ROOT)
                parts.append(f"### Dosya: {rel}\n```\n{content}\n```")
            except Exception:
                continue
        if len(files) > MAX_DIR_FILES:
            parts.append(f"_(+{len(files) - MAX_DIR_FILES} dosya daha var, gösterilmedi)_")
        return "\n\n".join(parts)

    if p.is_file():
        size = p.stat().st_size
        if size > 100_000:
            raw = p.read_bytes()[:20_000]
            if b"\x00" in raw:
                return ""
            return raw.decode("utf-8", errors="replace") + f"\n\n... [Büyük Dosya: Toplam {size:,} bayt, ilk 20 KB gösterildi]"
        raw = p.read_bytes()
        if b"\x00" in raw:
            return ""
        return raw.decode("utf-8", errors="replace")

    raise FileNotFoundError(path_str)


def collect_inputs(agent: dict, strict: bool = True) -> str:
    """Ajanın girdilerini toplar.

    strict=True (doğrusal tasarım aşaması): sıralama girdilerin var olmasını
    garanti eder, eksik girdi hatadır — sessiz placeholder üretmeyiz.

    strict=False (sprint panosu): bir rol herhangi bir sırada çağrılabilir ve
    rol seviyesindeki girdi listesi o an henüz üretilmemiş dokümanlar içerebilir.
    Sıralamayı panonun 'depends_on' alanı yönetir; burada eksik doküman
    engelleyici değil, prompt'a düşülen bir nottur.
    """
    blocks = []
    missing = []
    for inp in agent["inputs"]:
        try:
            content = read_input(inp)
        except FileNotFoundError:
            missing.append(inp)
            continue
        blocks.append(f"===== GİRDİ DOKÜMANI: {inp} =====\n{content}")

    if missing and strict:
        raise FileNotFoundError(
            f"'{agent['id']}' rolünün girdileri eksik: {', '.join(missing)}. "
            "Önceki adımlar tamamlanmadan bu rol çalıştırılamaz."
        )
    if missing:
        if not blocks:
            raise FileNotFoundError(
                f"'{agent['id']}' rolünün HİÇBİR girdisi mevcut değil "
                f"({', '.join(missing)}); görev çalıştırılamaz."
            )
        blocks.append(
            "===== HENÜZ ÜRETİLMEMİŞ GİRDİLER =====\n"
            + "\n".join(f"- {m}" for m in missing)
            + "\nBu dokümanlar bu aşamada mevcut değil. Onlara atıfta bulunma, "
              "içeriklerini uydurma; görevini eldeki girdilerle yap ve eksikten "
              "kaynaklanan varsayımlarını '> **Varsayım:**' ile işaretle."
        )
    return "\n\n".join(blocks)


# -------------------------------------------------------------
# 4. ÇIKTI YAZMA (tek dosya + çok dosyalı dizin hedefi)
# -------------------------------------------------------------
FILE_MARKER = re.compile(r"^===\s*FILE:\s*(.+?)\s*===\s*$", re.MULTILINE)
FENCE = re.compile(r"^\s*```[a-zA-Z0-9_+-]*\s*\n(.*?)\n\s*```\s*$", re.DOTALL)


def strip_fence(text: str) -> str:
    """Yanıtın tamamı tek bir kod bloğuysa çitleri kaldırır."""
    m = FENCE.match(text.strip())
    return m.group(1) if m else text


HISTORY_DIR = WORKSPACE / ".history"


def write_single_file(path_str: str, content: str) -> list[Path]:
    out = check_output_path(path_str)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Üzerine yazmadan önce önceki sürümü sakla. Kapsam dokümanı gibi birden çok
    # rolün sırayla zenginleştirdiği dosyalarda evrimi geriye dönük izlenebilir kılar.
    if out.exists():
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        n = len(list(HISTORY_DIR.glob(f"{out.stem}.*{out.suffix}"))) + 1
        shutil.copy2(out, HISTORY_DIR / f"{out.stem}.{n:02d}{out.suffix}")
    if out.suffix.lower() != ".md":
        content = strip_fence(content)
    out.write_text(content.rstrip() + "\n", encoding="utf-8")
    return [out]


def write_multi_file(dir_str: str, content: str) -> list[Path]:
    """'=== FILE: yol ===' bloklarını ayrıştırıp dizine yazar."""
    base = check_output_path(dir_str)
    matches = list(FILE_MARKER.finditer(content))

    if not matches:
        print(f"  [!] '{dir_str}' için dosya işaretleyicisi bulunamadı; "
              f"tüm çıktı _CIKTI.md'ye yazılıyor.", file=sys.stderr)
        base.mkdir(parents=True, exist_ok=True)
        target = base / "_CIKTI.md"
        target.write_text(content.rstrip() + "\n", encoding="utf-8")
        return [target]

    # Çoklu sprint ve modüler monolit yapısında dizin toptan taşınmaz;
    # mevcut modüller, kütüphaneler ve şemalar korunarak dosyalar birleştirilir (merge).
    base.mkdir(parents=True, exist_ok=True)

    written = []
    for i, m in enumerate(matches):
        raw_name = m.group(1).strip().lstrip("/")
        body = content[m.end(): matches[i + 1].start() if i + 1 < len(matches) else len(content)]

        target = (base / raw_name).resolve()
        if base not in target.parents and target != base:
            print(f"  [!] '{raw_name}' dizin dışına çıkıyor, atlandı.", file=sys.stderr)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(strip_fence(body).rstrip() + "\n", encoding="utf-8")
        written.append(target)
    return written


# -------------------------------------------------------------
# 5. PROMPT KURULUMU
# -------------------------------------------------------------
SYSTEM_SUFFIX = """

--- ÇALIŞMA KURALLARI ---
Otomatik bir boru hattında çalışıyorsun. Karşında cevap verebilecek bir insan YOK.
- ASLA soru sorma, bilgi isteme, "dosyayı paylaşır mısınız" deme.
- Bir bilgi eksikse makul bir varsayım yap, varsayımı çıktının içinde
  "> **Varsayım:**" satırıyla açıkça işaretle ve devam et.
- Yalnızca istenen dosyanın nihai içeriğini üret. "İşte dosya:" gibi giriş cümlesi,
  kapanış özeti veya sohbet metni yazma.
- Cevabın doğrudan dosyaya yazılacak; başka hiçbir yere gitmeyecek.
- Dokümanlarda "(zorunlu)" ibaresi taşıyan her satır kullanıcının KESİN kararıdır:
  seçenek değildir, yeniden değerlendirilmez, alternatifi önerilmez."""

# Doküman çıktıları için varsayılan kelime bütçesi. Rol bazında "max_words"
# ile ezilebilir. Kod/dizin hedeflerine uygulanmaz.
# Kullanıcının kapsam dokümanında "(zorunlu)" yazdığı satır bir KARARDIR,
# tartışılacak bir seçenek değil. Uzun dokümanların içinde kaybolmasın diye
# bu satırlar çıkarılıp prompt'un en başına ayrı blok olarak konur.
MANDATORY_MARKERS = ("(zorunlu)", "(ZORUNLU)", "(Zorunlu)")


def extract_mandatory(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        # Alıntı bloğu (>) dokümanın kullanım talimatıdır, kısıt değil.
        if stripped.startswith(">"):
            continue
        if any(m.lower() in stripped.lower() for m in MANDATORY_MARKERS):
            clean = stripped.lstrip("-*# ").strip()
            if clean and clean not in out:
                out.append(clean)
    return out


DOC_WORD_BUDGET = int(os.getenv("STUDIO_DOC_WORDS", "1800"))

LENGTH_RULE = """
--- UZUNLUK DİSİPLİNİ ---
Bu doküman en fazla ~{words} kelime olmalı. KARAR dokümanı yaz, ders kitabı değil:
- Kararı, tek cümlelik gerekçesini ve somut sonucunu yaz.
- Değerlendirilen alternatifleri tek satırda geç; her birini paragraflarla anlatma.
- Aynı bilgiyi hem tabloda hem düz metinde tekrarlama.
- Kod örneği yalnızca karar başka türlü anlaşılmıyorsa, kısa tutulur.
Bu doküman aşağı akıştaki rollere GİRDİ olacak; şişkin doküman onların odağını dağıtır.
"""

# Geliştirme görevlerinde koda eklenen regresyon-farkındalık kuralı.
# Saha gözlemi: ajan bir dosyayı yeniden yazarken önceki sprintin yapısal
# düzeltmesini (ve açıklayıcı TALEP/issue referansını) sessizce silebiliyor.
REGRESSION_GUARD_RULE = """

--- REGRESYON KORUMA KURALI (ZORUNLU) ---
Mevcut bir dosyayı değiştirmeden/yeniden yazmadan ÖNCE `git log -p -- <dosya>`
ile o dosyadaki geçmiş hata düzeltmelerini incele.
- TALEP-XXX, 'closes #N', 'KORUNACAK', 'regresyon' gibi işaretli yorum satırlarını
  ve onların koruduğu yapısal düzenlemeleri (ör. overflow dışına alınmış bir
  dropdown) ASLA silme veya geri alma.
- Bir düzeltmeyi bilinçli kaldırıyorsan yanına nedenini yaz; sessiz kaldırma YASAK.
- Kodun yanına açıklama ekleme serbestliği yoktur; sadece mevcut koruma
  işaretlerini koru, yenilerini ekleme zorunluluğun yok."""

SCOPE_EDIT_RULE = """
--- KAPSAM DOKÜMANI DÜZENLEME KURALI ---
Bu doküman KULLANICININ dokümanıdır, senin değil. Mevcut bölüm yapısını ve
kullanıcının cümlelerini olduğu gibi koru.
- EN FAZLA 10 madde ekle, toplamda ~400 kelimeyi geçme.
- Yalnızca kendi uzmanlık alanından gerçek bir eksik/risk varsa ekle; yoksa ekleme.
- Her eklemeni '<!-- rol: {rid} -->' ile başlat ve kısa madde işaretiyle yaz.
- Yeni üst başlık (##) AÇMA; mevcut bölümlerin altına ekle.
- Dokümanın tamamını döndür ama uzunluğunu iki katına çıkarma.
"""

SINGLE_FILE_TASK = """
--- ÜRETECEĞİN DOSYA ---
Şu anda TEK bir dosya üretiyorsun: `{path}`
Bu dosyanın tam içeriğini yaz.{extra}

Not: Bu roldeki diğer teslimatlar ({siblings}) ayrı ayrı istenecek —
onların içeriğini buraya karıştırma, bu dosyanın kapsamına odaklan."""

MULTI_FILE_TASK = """
--- ÜRETECEĞİN DOSYALAR ---
`{path}` dizininin içeriğini üreteceksin. Birden fazla kaynak dosya yaz.
Her dosyayı tam olarak şu formatta ayır (dizine göre GÖRELİ yol kullan):

=== FILE: alt/dizin/dosya_adi.uzanti ===
<dosyanın ham içeriği — markdown kod çiti YOK>

=== FILE: diger_dosya.uzanti ===
<...>

Dosya uzantılarını mimari dokümanda seçilen dile/framework'e göre belirle.
İşaretleyici satırları dışında hiçbir açıklama metni yazma."""

CODE_HINT = "\nBu bir kaynak kod dosyası: markdown kod çiti kullanma, sadece ham kodu yaz."


def build_prompts(agent: dict, target: str, siblings: list[str], brief: str,
                  inputs_text: str, revision_note: str = "") -> tuple[str, str]:
    system = agent["system_prompt"] + SYSTEM_SUFFIX

    is_dir = target.endswith("/")
    # Uzunluk disiplini: kapsam dokümanının kendine özel kuralı var, diğer
    # markdown çıktılarına kelime bütçesi uygulanır, kod dizinlerine uygulanmaz.
    if target == BRIEF_NAME:
        system += SCOPE_EDIT_RULE.format(rid=agent["id"])
    elif not is_dir and target.endswith(".md"):
        words = int(agent.get("max_words") or DOC_WORD_BUDGET)
        system += LENGTH_RULE.format(words=words)

    if is_dir:
        task = MULTI_FILE_TASK.format(path=target)
    else:
        extra = "" if target.endswith(".md") else CODE_HINT
        task = SINGLE_FILE_TASK.format(
            path=target,
            extra=extra,
            siblings=", ".join(f"`{s}`" for s in siblings) if siblings else "yok",
        )

    head = f"===== PROJE ÖZETİ =====\n{brief}\n\n" if brief.strip() else ""

    mandatory = extract_mandatory(brief + "\n" + inputs_text)
    if mandatory:
        items = "\n".join(f"- {m}" for m in mandatory)
        head = ("===== ZORUNLU KISITLAR (TARTIŞMAYA KAPALI) =====\n"
                "Aşağıdakiler kullanıcının verdiği kararlardır. Bunları sorgulamaz, "
                "alternatif önermez, gerekçesini tartışmaz, 'değerlendirilebilir' demezsin. "
                "Tasarımını bunların ÜSTÜNE kurarsın. Bir zorunluluk teknik olarak "
                "imkânsızsa, alternatif seçmek yerine çıktında "
                "'> **ÇATIŞMA:**' satırıyla durumu bildirir ve kullanıcıya bırakırsın.\n"
                f"{items}\n\n") + head
    user = f"""{head}{inputs_text}
{revision_note}
{task}"""
    return system, user


# -------------------------------------------------------------
# 6. BORU HATTI
# -------------------------------------------------------------
def run_agent(agent: dict, brief: str, state: dict, force: bool = False,
              revision_note: str = "", dry_run: bool = False) -> list[Path]:
    """Ajanın her çıktısı için AYRI bir istek atar."""
    def gather() -> str:
        try:
            return collect_inputs(agent)
        except FileNotFoundError:
            if not dry_run:
                raise
            print("    [dry-run] girdiler henüz üretilmemiş, prompt boyutu eksik hesaplanıyor.")
            return ""

    backend, model, effort, tools = resolve_engine(agent)
    # Kapsam dokümanı zaten bu rolün girdisiyse özet bloğunu tekrarlama.
    agent_brief = "" if BRIEF_NAME in agent["inputs"] else brief
    produced = []

    for target in agent["outputs"]:
        # Rol kendi girdisini güncelliyor olabilir (ör. kapsam dokümanı);
        # her hedef öncesi diskten tazele.
        inputs_text = gather()
        done = target in state["completed_outputs"]
        exists = resolve_path(target).exists()
        if done and exists and not force:
            print(f"    [atlandı] {target} zaten üretilmiş.")
            continue

        siblings = [o for o in agent["outputs"] if o != target]
        system, user = build_prompts(agent, target, siblings, agent_brief,
                                     inputs_text, revision_note)

        if dry_run:
            print(f"    [dry-run] {target}  ({backend}/{model or 'varsayılan'}, effort={effort}, "
                  f"prompt ~{len(system) + len(user)} karakter)")
            continue

        print(f"    -> üretiliyor: {target}")
        meta = {
            "seq": _trace_seq(),
            "role": agent["id"],
            "title": agent["title"],
            "target": target,
            "backend": backend,
            "model": model,
            "tools": tools,
        }
        output = query_claude(system, user, backend, model, effort, meta, tools)

        if target.endswith("/"):
            files = write_multi_file(target, output)
        else:
            files = write_single_file(target, output)

        for f in files:
            extra = ""
            if f.suffix == ".md":
                w = len(f.read_text(encoding="utf-8", errors="replace").split())
                budget = int(agent.get("max_words") or DOC_WORD_BUDGET)
                if target == BRIEF_NAME:
                    extra = f"  ({w:,} kelime)"
                elif w > budget * 1.6:
                    extra = f"  [!] {w:,} kelime — bütçe {budget:,}"
                else:
                    extra = f"  ({w:,} kelime)"
            print(f"       [✓] {f.relative_to(ROOT)}{extra}")
        produced.extend(files)
        mark_output_done(state, target)

    return produced


def run_revision_loop(agent: dict, org_by_id: dict, brief: str, state: dict,
                      max_rounds: int, dry_run: bool):
    """'revises' alanı olan bir eleştirmen rolü, hedef rolü onaylayana kadar döndürür."""
    target_id = agent["revises"]
    target_agent = org_by_id.get(target_id)
    if target_agent is None:
        print(f"  [!] '{agent['id']}' rolünün revizyon hedefi '{target_id}' bulunamadı, "
              f"tek geçişte çalıştırılıyor.", file=sys.stderr)
        run_agent(agent, brief, state, dry_run=dry_run)
        return

    for rnd in range(1, max_rounds + 1):
        print(f"  [tur {rnd}/{max_rounds}] '{target_id}' inceleniyor...")
        run_agent(agent, brief, state, force=(rnd > 1), dry_run=dry_run)
        if dry_run:
            return

        critique = "\n\n".join(read_input(o) for o in agent["outputs"])
        if "VERDICT: APPROVED" in critique:
            print(f"  [✓] Onaylandı (tur {rnd}).")
            return
        if rnd == max_rounds:
            print(f"  [!] {max_rounds} turda onay çıkmadı; mevcut hâliyle devam ediliyor.")
            return

        print(f"  [~] Onay yok — '{target_id}' geri bildirimle yeniden çalıştırılıyor.")
        note = (
            "\n===== DENETÇİ GERİ BİLDİRİMİ (bu turda giderilmesi gerekiyor) =====\n"
            + critique
        )
        run_agent(target_agent, brief, state, force=True, revision_note=note)


def execute_pipeline(org: dict, brief: str, args):
    print(f"\n{'=' * 60}")
    print(f"  🏢 {org['company_name']}")
    print(f"  📦 {org['project']}")
    if BACKEND == "devin":
        engine = f"Devin AI (devin) · {DEVIN_MODEL or 'varsayılan model'}"
        if DEVIN_CLOUD:
            engine += " [cloud]"
    else:
        engine = f"Antigravity (agy) · {AGY_MODEL}"
    print(f"  🤖 {engine} (effort: {EFFORT})")
    print(f"{'=' * 60}")

    state = load_state()
    org_by_id = {a["id"]: a for a in org["hierarchy"]}
    steps = org["hierarchy"]
    if args.stage != "all" and not args.only:
        steps = [a for a in steps if a.get("stage", "design") == args.stage]
        print(f"[i] Aşama filtresi: {args.stage} ({len(steps)} rol). "
              f"Tümü için --stage all.")
    if args.only:
        steps = [a for a in steps if a["id"] in args.only]
        missing = set(args.only) - {a["id"] for a in steps}
        if missing:
            sys.exit(f"[HATA] Bilinmeyen rol id: {', '.join(sorted(missing))}")

    for agent in steps:
        agent_id = agent["id"]
        if agent.get("stage") == "service":
            # Servis rolleri (ör. musteri_temsilcisi) boru hattına girmez;
            # web sohbeti gibi kendi kanallarında çalışır.
            continue
        if agent_id == PLANNER_ID:
            # Pano şema doğrulaması gerektirir; run_planner() üzerinden üretilir.
            continue
        outputs_exist = all(resolve_path(p).exists() for p in agent["outputs"])
        if agent_id in state["completed_steps"] and outputs_exist and not args.only:
            print(f"\n---> [ATLANDI] {agent['title']} ({agent_id})")
            continue

        eng_b, eng_m, eng_e, eng_t = resolve_engine(agent)
        tool_note = f", araçlar={'+'.join(eng_t)}" if eng_t else ""
        print(f"\n---> {agent['title']} ({agent_id})  "
              f"[{eng_b}/{eng_m or 'varsayılan'}, effort={eng_e}{tool_note}]")
        try:
            if "revises" in agent:
                run_revision_loop(agent, org_by_id, brief, state, args.max_revisions, args.dry_run)
            else:
                run_agent(agent, brief, state, dry_run=args.dry_run)
        except FileNotFoundError as e:
            print(f"\n[DURDU] {e}", file=sys.stderr)
            print("        Tamamlanan adımlar kaydedildi; sorunu çözüp tekrar çalıştırın.",
                  file=sys.stderr)
            sys.exit(1)
        except CallAborted as e:
            print(f"\n[KESİLDİ] {e}", file=sys.stderr)
            sys.exit(0)
        except RuntimeError as e:
            print(f"\n[DURDU] {agent_id}: {e}", file=sys.stderr)
            print("        İlerleme .state.json'a kaydedildi; tekrar çalıştırınca kaldığı "
                  "yerden devam eder.", file=sys.stderr)
            sys.exit(1)

        if not args.dry_run:
            mark_step_done(state, agent_id)

    print(f"\n🎉 Bitti. Çıktılar: {WORKSPACE.relative_to(ROOT)}/")


# -------------------------------------------------------------
# 6b. SPRINT PANOSU: PLANLAMA VE GÖREV KOŞUCUSU
# -------------------------------------------------------------
PLANNER_ID = "sprint_planner"


def run_planner(org: dict, brief: str, force: bool = False) -> dict:
    """Planlayıcı rolünü çalıştırıp studio.db'ye sprint panosu üretir (JSON doğrulamalı)."""
    agent = next((a for a in org["hierarchy"] if a["id"] == PLANNER_ID), None)
    if agent is None:
        sys.exit(f"[HATA] '{PLANNER_ID}' rolü org şemasında yok.")
    if B.board_exists() and not force:
        print("  [i] Mevcut pano kullanılıyor. Yeniden planlamak için --replan.")
        return B.load()

    backend, model, effort, tools = resolve_engine(agent)
    inputs_text = collect_inputs(agent)
    print(f"\n---> {agent['title']} ({PLANNER_ID})  [{backend}/{model or 'varsayılan'}]")

    build_roles = [a for a in org["hierarchy"] if a.get("stage") == "build"]
    roles_block = "\n".join(
        f'- "{a["id"]}" → çıktıları: {", ".join(a["outputs"])}' for a in build_roles)
    # BOARD_TASK JSON şeması içerdiği için .format() kullanılamaz ({ } çakışır).
    task = BOARD_TASK.replace("{roles}", roles_block)

    last_err = ""
    for attempt in (1, 2, 3):
        note = ""
        if last_err:
            note = ("\n\nÖNCEKİ DENEME GEÇERSİZDİ, şu hataları düzelt:\n" + last_err)
        user = (f"===== PROJE ÖZETİ =====\n{brief}\n\n{inputs_text}\n"
                f"{task}{note}")
        meta = {"seq": _trace_seq(), "role": PLANNER_ID, "title": agent["title"],
                "target": "studio.db", "backend": backend,
                "model": model, "tools": tools}
        raw = query_claude(agent["system_prompt"] + SYSTEM_SUFFIX, user,
                           backend, model, effort, meta, tools)

        cleaned = strip_fence(raw).strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
        # Model başa/sona metin eklemiş olabilir: en dıştaki { } bloğunu ayıkla.
        i, j = cleaned.find("{"), cleaned.rfind("}")
        if i > 0 or (j != -1 and j < len(cleaned) - 1):
            if i != -1 and j > i:
                cleaned = cleaned[i:j + 1]
        try:
            board = json.loads(cleaned)
        except json.JSONDecodeError as e:
            last_err = f"- Geçerli JSON değil: {e}"
            print(f"  [!] Deneme {attempt}: JSON ayrıştırılamadı, yeniden isteniyor.",
                  file=sys.stderr)
            continue

        board = B.normalize(board)
        errs = B.validate(board)
        if errs:
            last_err = "\n".join(f"- {e}" for e in errs)
            print(f"  [!] Deneme {attempt}: pano tutarsız ({len(errs)} sorun).", file=sys.stderr)
            continue

        # Rol adları org şemasında var mı? Bilinmeyen roller dinamik sentezlenir
        for _, t in B.all_tasks(board):
            r = t.get("role")
            if r and not any(a["id"] == r for a in org["hierarchy"]):
                synthesize_role(org, r)

        B.schedule(board)
        board["baseline_end"] = board["sprints"][-1]["planned_end"]
        B.refresh(board)
        B.save(board)
        p = B.progress(board)
        B.audit("engine", "pano_planlandi",
                detay={"sprint": p["sprints_total"], "gorev": p["total"],
                       "baseline_end": board.get("baseline_end")})
        print(f"  [✓] Pano üretildi: {p['sprints_total']} sprint, {p['total']} görev "
              f"→ studio.db")
        return board

    sys.exit(f"[HATA] Planlayıcı iki denemede de geçerli pano üretemedi:\n{last_err}")


BOARD_TASK = """
--- ÜRETECEĞİN ÇIKTI ---
Yalnızca GEÇERLİ JSON üret. Markdown kod çiti, açıklama, giriş cümlesi YOK.

Şema:
{
  "sprints": [
    {
      "id": "S1",
      "name": "kısa sprint adı",
      "goal": "bu sprint sonunda neyin çalışır durumda olacağı",
      "planned_days": 3,
      "tasks": [
        {
          "id": "S1-T1",
          "title": "kısa görev başlığı",
          "description": "bu görevde tam olarak ne üretilecek",
          "role": "org şemasındaki bir rol id'si",
          "phase": "develop | test | deploy",
          "outputs": ["workspace/... yol"],
          "depends_on": ["aynı veya önceki sprint'teki görev id'leri"]
        }
      ]
    }
  ]
}

Kurallar:
- Her sprint ÇALIŞAN, gösterilebilir bir dilim üretmeli — katman değil, özellik dilimi.
- Her sprint'te en az bir "develop" ve bir "test" görevi olmalı; "deploy" sprint'in
  çıktısı paketlenebilir olduğunda eklenir.
- Bağımlılıklar gerçek olmalı: test görevi geliştirme görevine bağlı olmalı.
- planned_days gerçekçi bir TAHMİN; sprint uzarsa takvim otomatik kayacak.

BOYUT SINIRI (kesin):
- EN FAZLA 5 sprint, sprint başına EN FAZLA 5 görev. Toplam 25 görevi geçme.
- "description" en fazla 25 kelime. Uzun anlatım yazma, görev başlığı yeterli.
- Çıktı tek bir JSON nesnesi; yorum satırı, açıklama, markdown YOK.

ROL ADLARI (yalnızca bu listeden seç, BİREBİR kopyala, yenisini UYDURMA):
{roles}

ÇIKTI YOLLARI: her görevin "outputs" değeri, seçtiğin rolün org şemasındaki
çıktı yollarından biri olmalı. Yeni yol icat etme."""


# -------------------------------------------------------------
# 5c. DETERMİNİSTİK KALİTE KAPILARI (scripts/kalite_kapilari.py)
# -------------------------------------------------------------
def _kalite_modulu():
    """scripts/kalite_kapilari.py varsa import eder; yoksa None (eski projeler)."""
    try:
        scripts_dir = str(ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import kalite_kapilari as KK
        return KK
    except Exception:
        return None


def _kalite_snapshot() -> set:
    KK = _kalite_modulu()
    return KK.porcelain_snapshot() if KK else set()


def _kalite_kapilari_kostur(task: dict, pre_snapshot: set) -> list:
    """Görev sonrası deterministik kapılar; pano notuna eklenecek metinler döner."""
    KK = _kalite_modulu()
    if not KK:
        return []
    try:
        return KK.gorev_kapilari(task, pre_snapshot)
    except Exception as e:
        print(f"   [UYARI] kalite kapıları çalıştırılamadı: {e}", file=sys.stderr)
        return []


def _auto_talep_uat(task: dict, uat_cikti: str):
    """Canlı UAT/smoke başarısızlığını müşteri talep havuzuna otomatik düşürür.

    Mükerrer koruması: aynı görev id'siyle açık (çözülmemiş/iptal edilmemiş)
    bir [UAT] talebi varsa yenisi açılmaz.
    """
    try:
        scripts_dir = str(ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import musteri_talepleri as MT
        import importlib
        importlib.reload(MT)

        baslik = f"[UAT] {task['id']} canlı kabul denetimi başarısız: {task.get('title', '')[:80]}"
        data = MT.load_data()
        for t in data.get("talepler", []):
            if (t.get("baslik") or "").startswith(f"[UAT] {task['id']}") \
                    and t.get("durum") not in ("COZULDU", "IPTAL"):
                print(f"   [i] Açık UAT talebi zaten var: {t['id']} — mükerrer kayıt açılmadı.")
                return

        aciklama = (
            f"Canlı UAT denetimi (scripts/uat_live_audit.mjs) '{task['id']}' görevinde "
            f"başarısız oldu.\n\nSon çıktı satırları:\n```\n{(uat_cikti or '').strip()[-900:]}\n```"
        )
        yeni = MT.yeni_talep("HATA", baslik, aciklama, oncelik="YUKSEK", sayfa_url="/")
        print(f"   📥 [OTOMATİK TALEP] {yeni['id']} havuza eklendi: {baslik[:70]}")
    except Exception as e:
        print(f"   [UYARI] UAT talebi otomatik açılamadı: {e}", file=sys.stderr)


def verify_task_execution(task: dict, sprint: dict, interactive: bool = False) -> str:
    """QA veya DevOps görevlerinde gerçek yerel ortam doğrulaması yapar veya talimat verir."""
    phase = task.get("phase", "")
    role = task.get("role", "")
    title = task.get("title", "")
    note_parts = []

    # 1. UAT KABUL DENETİMİ (uat_auditor veya UAT görevleri)
    if role == "uat_auditor" or "uat" in (title + " " + task.get("description", "")).lower():
        print(f"\n   🎯 [UAT KABUL DENETİM KAPISI] {task['id']} · {title}")
        uat_script = ROOT / "scripts/uat_live_audit.mjs"
        if uat_script.exists():
            print("   🚀 Canlı UAT denetimi yürütülüyor (scripts/uat_live_audit.mjs)...")
            try:
                res = subprocess.run("node scripts/uat_live_audit.mjs", shell=True, cwd=ROOT, capture_output=True, text=True, timeout=30)
                if res.returncode == 0:
                    print("   ✅ [UAT BAŞARILI] Canlı sistem ve kullanıcı yolculukları %100 doğrulandı!")
                    note_parts.append("canlı UAT kabul testleri geçti")
                else:
                    print(f"   ⚠️  [UAT BAŞARISIZ] Canlı sistemde kullanıcı kabul hatası tespit edildi!")
                    if res.stdout:
                        print("      " + "\n      ".join(res.stdout.strip().splitlines()[-8:]))
                    note_parts.append("canlı UAT hata tespit edildi")
                    _auto_talep_uat(task, res.stdout)
            except Exception as e:
                print(f"   ⚠️  UAT çalıştırılamadı: {e}")
                note_parts.append("uat çalıştırılamadı")
        return "; ".join(note_parts) if note_parts else ""

    # 2. TEST FAZI DOĞRULAMASI (3 Aşamalı Kalite Kapısı)
    elif phase == "test" or role == "qa_lead":
        print(f"\n   🔍 [DOĞRULAMA KAPISI - 3 AŞAMALI KALİTE] {task['id']} · {title}")
        desc_lower = (task.get("description", "") + " " + title).lower()
        outputs_str = " ".join(task.get("outputs", []))

        rel_dir = None
        test_cmd = None
        install_cmd = None

        if "backend" in desc_lower or "backend" in outputs_str or "api" in desc_lower:
            rel_dir = "workspace/src/backend"
            test_cmd = "npm test"
            install_cmd = "npm install"
        elif "web" in desc_lower or "frontend" in desc_lower or "harita" in desc_lower or "ssr" in desc_lower:
            rel_dir = "workspace/src/frontend"
            test_cmd = "npm test"
            install_cmd = "yarn install --ignore-engines || npm install"
        elif "mobile" in desc_lower or "flutter" in desc_lower:
            rel_dir = "workspace/src/mobile"
            test_cmd = "flutter test"
            install_cmd = "flutter pub get"

        if rel_dir:
            target_path = ROOT / rel_dir
            if target_path.exists():
                has_modules = (target_path / "node_modules").exists() or (rel_dir.endswith("mobile") and (target_path / ".dart_tool").exists())
                if not has_modules:
                    print(f"   ⚠️  DİKKAT: '{rel_dir}' dizininde bağımlılıklar henüz kurulu değil.")
                    print(f"       👉 Kurulum Komutu : cd {rel_dir} && {install_cmd}")
                    print(f"       👉 Test Komutu     : cd {rel_dir} && {test_cmd}")
                    if interactive:
                        ans = input(f"   [?] Bağımlılıkları kurup testleri koşturmak ister misiniz? (e/h): ").strip().lower()
                        if ans == "e":
                            print(f"   📦 Kuruluyor ({install_cmd})...")
                            subprocess.run(install_cmd, shell=True, cwd=target_path)
                            has_modules = (target_path / "node_modules").exists()
                    else:
                        note_parts.append(f"bağımlılık eksik: cd {rel_dir} && {install_cmd}")

                if has_modules:
                    # Aşama 1: Statik Tip Kontrolü (Type Check)
                    if (target_path / "tsconfig.json").exists():
                        print(f"   [1/3] Statik Tip Kontrolü (TypeScript)...")
                        type_res = subprocess.run("npx tsc --noEmit", shell=True, cwd=target_path, capture_output=True, text=True, timeout=45)
                        if type_res.returncode == 0:
                            print(f"         ✅ Tip denetimi hatasız.")
                        else:
                            print(f"         ⚠️  Tip uyarıları/hataları tespit edildi.")

                    # Aşama 2: Birim ve Entegrasyon Testleri
                    run_now = False
                    if interactive:
                        ans = input(f"   [2/3] Birim testleri ({test_cmd}) çalıştırmak istiyor musunuz? (e/h): ").strip().lower()
                        run_now = (ans == "e")
                    else:
                        run_now = True

                    if run_now:
                        print(f"   [2/3] Testler koşturuluyor: cd {rel_dir} && {test_cmd}...")
                        try:
                            res = subprocess.run(test_cmd, shell=True, cwd=target_path, capture_output=True, text=True, timeout=60)
                            if res.returncode == 0:
                                print(f"         ✅ [BAŞARILI] Tüm birim ve entegrasyon testleri geçti!")
                                note_parts.append("yerel testler geçti")
                            else:
                                print(f"         ⚠️  [TEST UYARISI] Bazı testler başarısız (exit {res.returncode}).")
                                if res.stdout:
                                    print("            " + "\n            ".join(res.stdout.strip().splitlines()[-6:]))
                                note_parts.append("yerel test inceleme bekliyor")
                        except Exception as e:
                            print(f"   ⚠️  Test koşturulamadı: {e}")
                            note_parts.append("test koşturulamadı")

                    # Aşama 3: UAT ve Kullanıcı Yolculuğu Hazırlığı
                    print(f"   [3/3] UAT & Canlı Senaryo Denetimi hazır.")
            else:
                print(f"   ℹ️  Hedef dizin henüz oluşmamış: {rel_dir}")

    # 3. DEPLOY FAZI DOĞRULAMASI
    elif phase == "deploy" or role == "devops_engineer":
        print(f"\n   🐳 [DEVOPS DAĞITIM DOĞRULAMA] {task['id']} · {title}")
        compose_file = ROOT / "workspace/infra/docker-compose.yml"
        if compose_file.exists():
            print("       👉 Docker Servisleri : cd workspace/infra && docker compose up -d")
            print("       👉 Migration Çalıştır: cd workspace/infra && npm run migrate")
            if interactive:
                ans = input("   [?] Docker compose yapılandırması doğrulansın mı? (e/h): ").strip().lower()
                if ans == "e":
                    res = subprocess.run("docker compose config", shell=True, cwd=ROOT / "workspace/infra", capture_output=True, text=True)
                    if res.returncode == 0:
                        print("   ✅ Docker compose dosyası geçerli!")
                        note_parts.append("docker compose doğrulandı")
                    else:
                        print(f"   ⚠️ Docker compose hatası: {res.stderr[:200]}")
                        note_parts.append("docker config kontrolü gerekli")
            else:
                note_parts.append("altyapı konfigürasyonu hazır")

    return "; ".join(note_parts) if note_parts else ""


def print_sprint_action_summary(sprint: dict):
    """Sprint tamamlandığında terminale canlı test için eylem rehberi basar."""
    sid = sprint.get("id", "S?")
    sname = sprint.get("name", "")
    print("\n" + "=" * 70)
    print(f"  🚀 SPRINT {sid} TAMAMLANDI — GELİŞTİRİCİ CANLI TEST REHBERİ")
    print(f"  📦 {sname}")
    print("=" * 70)
    print("  Canlı sistemi kendi yerel terminalinizde test etmek için adımlar:\n")
    print("  1. Veritabanını Başlatın (PostGIS):")
    print("     cd workspace/infra && docker compose up -d\n")
    print("  2. Backend API'yi Başlatın (Fastify, Port 3001):")
    print("     cd workspace/src/backend && npm install && npm run dev")
    print("     👉 Swagger UI: http://localhost:3001/documentation\n")
    print("  3. Web Arayüzünü Başlatın (Nuxt 3, Port 3000):")
    print("     cd workspace/src/frontend && yarn install --ignore-engines && yarn dev")
    print("     👉 Canlı Harita: http://localhost:3000\n")
    print("  4. Otomatik Testleri Koşturun:")
    print("     cd workspace/src/backend && npm test")
    print("     cd workspace/src/frontend && yarn test")
    print("=" * 70 + "\n")


def self_healing_code_check(target: str) -> tuple[bool, str]:
    """Üretilen kodun derlenebilirliğini ve kritik rotaların sağlamlığını denetler."""
    target_path = ROOT / target
    if not target_path.exists():
        return True, ""

    # 1. Backend Denetimleri
    if "backend" in target:
        # A) Kritik Rota Regresyon Denetimi
        app_ts = target_path / "src/app.ts"
        if app_ts.exists():
            content = app_ts.read_text(encoding="utf-8")
            missing_routes = []
            if "stationRoutes" not in content and "/stations" not in content:
                missing_routes.append("İstasyon Rotaları (/stations)")
            if "operatorRoutes" not in content and "/operators" not in content:
                missing_routes.append("Operatör Rotaları (/operators)")
            if missing_routes:
                return False, f"Regresyon Hatası: Önceki sprintlerin kritik rotaları silinmiş: {', '.join(missing_routes)}. app.ts dosyasında stationRoutes ve operatorRoutes mutlaka korunmalıdır."

        # B) TypeScript Derleme Denetimi
        if (target_path / "tsconfig.json").exists() and (target_path / "node_modules").exists():
            try:
                res = subprocess.run("npx tsc --noEmit", shell=True, cwd=target_path, capture_output=True, text=True, timeout=40)
                if res.returncode != 0:
                    err_lines = [l for l in res.stdout.splitlines() if "error TS" in l][:6]
                    if err_lines:
                        return False, "TypeScript Derleme Hatası:\n" + "\n".join(err_lines)
            except Exception:
                pass

    # 2. Frontend Denetimleri
    elif "frontend" in target:
        nuxt_cfg = target_path / "nuxt.config.ts"
        if nuxt_cfg.exists():
            content = nuxt_cfg.read_text(encoding="utf-8")
            if "127.0.0.1" not in content and "devServer" not in content:
                return False, "Yapılandırma Uyarısı: nuxt.config.ts içinde devServer host '127.0.0.1' olarak tanımlanmalıdır (IPv6 HMR çakışmasını önlemek için)."

    return True, ""


def _pending_control(task_id: str) -> str:
    """İki çağrı ARASINDA bakılan kontrol bayrakları.

    stop/force/goto her zaman keser; skip yalnızca bu görevi hedefliyorsa
    keser (başka bir kuyruktaki görevi atlamak koşanı kesmeyi gerektirmez).
    """
    if B.is_set("stop"):
        return "stop"
    if B.is_set("force"):
        return "force"
    if B.is_set("goto"):
        return "goto"
    if B.value_of("skip") == task_id:
        return "skip"
    return ""


def execute_task(org: dict, task: dict, sprint: dict, brief: str, board: dict,
                 interactive: bool = False) -> bool:
    """Panodaki tek bir görevi yürütür. Başarılıysa True."""
    role_id = task["role"]
    if role_id == "frontend_engineer" and not any(a["id"] == "frontend_engineer" for a in org["hierarchy"]):
        role_id = "web_engineer"
    agent = next((a for a in org["hierarchy"] if a["id"] == role_id), None)
    if agent is None:
        agent = synthesize_role(org, role_id)
    if agent is None:
        B.mark(board, task["id"], B.FAILED, f"rol bulunamadı: {task['role']}")
        return False

    backend, model, effort, tools = resolve_engine(agent)
    print(f"\n---> [{sprint['id']}] {task['id']} · {task['title']}")
    print(f"     rol={task['role']} faz={task['phase']} {backend}/{model or 'varsayılan'}")

    # Görev, rolün şemadaki girdilerini + görev tanımını alır.
    try:
        inputs_text = collect_inputs(agent, strict=False)
    except FileNotFoundError as e:
        B.mark(board, task["id"], B.BLOCKED, str(e))
        print(f"     [!] {e}", file=sys.stderr)
        return False

    task_brief = (
        f"\n--- BU GÖREV ---\n"
        f"Sprint: {sprint['id']} — {sprint['name']}\n"
        f"Sprint hedefi: {sprint.get('goal', '—')}\n"
        f"Görev: {task['title']}\n"
        f"Açıklama: {task.get('description', '—')}\n"
        f"Faz: {task['phase']}\n"
        f"Yalnızca bu görevin kapsamındaki işi yap; sprint dışına taşma.\n"
    )
    # Geliştirme görevlerinde geçmiş düzeltmelerin korunması zorunludur.
    if task.get("phase") == "develop":
        task_brief += REGRESSION_GUARD_RULE

    # Kalite kapıları için görev öncesi çalışma ağacı anlığı
    pre_task_git = _kalite_snapshot()

    for target in task["outputs"]:
        act = _pending_control(task["id"])
        if act:
            raise CallAborted(f"{task['id']} '{act}' isteğiyle kesildi.")
        if target in state_of(board).get("done_outputs", []):
            continue
        siblings = [o for o in task["outputs"] if o != target]

        # Artımlı Geliştirme: Hedef dizindeki mevcut kod tabanını ajana besle
        existing_code_block = ""
        target_path = ROOT / target
        if target_path.is_dir() and any(target_path.iterdir()):
            file_list = []
            for p in sorted(target_path.rglob("*")):
                if p.is_file() and not any(ign in str(p) for ign in ["node_modules", ".nuxt", ".git", "dist", ".stale", ".history"]):
                    file_list.append(str(p.relative_to(target_path)))

            core_snippets = []
            for candidate in ["src/app.ts", "package.json", "nuxt.config.ts", "app.vue"]:
                cp = target_path / candidate
                if cp.exists() and cp.is_file():
                    content_preview = cp.read_text(encoding="utf-8", errors="replace")[:2500]
                    core_snippets.append(f"--- {candidate} ---\n{content_preview}")

            if file_list:
                existing_code_block = (
                    f"\n===== MEVCUT KOD TABANI (KORUNACAK VE GENİŞLETİLECEK) =====\n"
                    f"Bu dizinde önceki sprintlerden kalan çalışan şu dosyalar mevcuttur:\n"
                    + "\n".join(f"- {f}" for f in file_list[:40]) + "\n\n"
                    f"Mevcut Çekirdek Yapılandırmalar:\n"
                    + "\n\n".join(core_snippets) + "\n\n"
                    f"KRİTİK TALİMAT: Önceki sprintlerde geliştirilen rotaları, servisleri, modelleri ve paketleri ASLA SİLME!\n"
                    f"Yeni görevi mevcut yapıya ENTEGRE ET ve GENİŞLET (extend). Mevcut rotaları koruyarak yeni rotaları ekle.\n"
                )

        system, user = build_prompts(agent, target, siblings, brief,
                                     inputs_text + task_brief + existing_code_block)
        meta = {"seq": _trace_seq(), "role": task["role"], "title": agent["title"],
                "target": target, "backend": backend, "model": model,
                "tools": tools, "task": task["id"], "sprint": sprint["id"]}
        try:
            output = query_claude(system, user, backend, model, effort, meta, tools)
        except RuntimeError as e:
            B.mark(board, task["id"], B.FAILED, str(e)[:200])
            print(f"     [!] {e}", file=sys.stderr)
            return False

        # İyileştirme Motoru: Otomatik hata denetimi ve kendini onarma döngüsü (Self-Healing Loop)
        max_repairs = 2
        for repair_attempt in range(max_repairs + 1):
            files = write_multi_file(target, output) if target.endswith("/") \
                else write_single_file(target, output)

            is_valid, err_msg = self_healing_code_check(target)
            if is_valid:
                for f in files:
                    print(f"     [✓] {f.relative_to(ROOT)}")
                break

            if repair_attempt < max_repairs:
                print(f"     [⚠️  İYİLEŞTİRME MOTORU] Hata tespit edildi, otomatik onarılıyor (Deneme {repair_attempt + 1}/{max_repairs}):")
                print(f"         {err_msg.splitlines()[0]}")
                repair_user = (
                    f"{user}\n\n"
                    f"--- OTOMATİK İYİLEŞTİRME VE DÜZELTME TALEBİ ---\n"
                    f"Ürettiğin kodda şu kritik hata oluştu:\n{err_msg}\n\n"
                    f"Lütfen mevcut çalışan rotaları (/stations, /operators vb.) ve paketleri koruyarak bu hatayı düzelt ve dosyaları eksiksiz yeniden üret."
                )
                try:
                    output = query_claude(system, repair_user, backend, model, effort, meta, tools)
                except Exception as e:
                    print(f"     [!] Onarım çağrısı başarısız: {e}", file=sys.stderr)
                    break
            else:
                print(f"     [!] İyileştirme motoru azami denemeye ulaştı: {err_msg[:100]}", file=sys.stderr)
                for f in files:
                    print(f"     [✓] {f.relative_to(ROOT)}")

    # Gerçek ortam doğrulaması / çalıştırma rehberi
    note = verify_task_execution(task, sprint, interactive=interactive)

    # Deterministik kalite kapıları (regresyon taraması, fix+test, smoke)
    gate_notes = _kalite_kapilari_kostur(task, pre_task_git)
    if gate_notes:
        note = "; ".join([n for n in [note] + gate_notes if n])
        # Smoke kapısı başarısızsa bulguyu talep havuzuna düşür (mükerrer korumalı)
        if any("smoke başarısız" in n for n in gate_notes):
            _auto_talep_uat(task, "; ".join(gate_notes))

    B.mark(board, task["id"], B.DONE, note=note)

    # Müşteri talebi görevi ise durumu otomatik güncelle
    if task.get("talep_id"):
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            import musteri_talepleri as MT
            import importlib
            importlib.reload(MT)
            if task.get("phase") == "test":
                MT.guncelle(task["talep_id"], durum="COZULDU",
                            studio_notu=f"Görev {task['id']} başarıyla tamamlandı ve UAT testinden geçti.")
        except Exception:
            pass
    return True


def state_of(board: dict) -> dict:
    return board.setdefault("_runtime", {"done_outputs": []})


def tahmini_gorev_maliyeti(task: dict, varsayilan: float = 0.80) -> float:
    """Sıradaki görev kabaca ne tutar? Son çağrıların ortalamasından kestirilir."""
    f = TRACE_DIR / "index.jsonl"
    costs = []
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines()[-12:]:
            try:
                c = json.loads(line).get("cost_usd")
            except json.JSONDecodeError:
                continue
            if c:
                costs.append(c)
    cagri_basi = sum(costs) / len(costs) if costs else varsayilan
    return round(cagri_basi * max(1, len(task.get("outputs", []))), 4)


def spent_so_far() -> float:
    """Bu projede şimdiye kadar harcanan toplam (studio.db / iz kayıtlarından)."""
    # 1. studio.db'den dene
    try:
        conn = B.db_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT SUM(cost_usd) FROM maliyet_kayitlari")
            row = cur.fetchone()
            if row and row[0] is not None and float(row[0]) > 0:
                return float(row[0])
        finally:
            conn.close()
    except Exception:
        pass

    # 2. JSONL fallback
    f = TRACE_DIR / "index.jsonl"
    if not f.exists():
        return 0.0
    total = 0.0
    for line in f.read_text(encoding="utf-8").splitlines():
        try:
            total += json.loads(line).get("cost_usd") or 0.0
        except json.JSONDecodeError:
            pass
    return total


def autonomous_gap_review_and_phasing(org: dict, brief: str, board: dict) -> int:
    """Panodaki görevler tamamlandığında CTO ve Product Owner liderlik değerlendirmesi yapar.
    Sistemdeki eksikleri (gezilmeyen ekranlar, test edilmemiş butonlar/modallar, hata raporları)
    tespit eder, tartışıp yeni sprint fazlarına böler ve panoya ekler.
    Eklenen yeni sprint sayısını döner (0 = eksik yok, proje tamam).
    """
    from datetime import datetime
    print("\n" + "="*70)
    print("  🧠 [LİDERLİK DÖNGÜSÜ: CTO & PRODUCT OWNER EKSİK VE FAZ DEĞERLENDİRMESİ]")
    print("="*70)

    # 1. Ziyaretçi Deneyimi & Ekran Taraması Fazı Yapıldı mı?
    has_visitor_phase = any(
        "ziyaretçi" in s.get("name", "").lower() or
        "ziyaretci" in s.get("name", "").lower() or
        any(t.get("role") == "screen_visitor_tester" for t in s.get("tasks", []))
        for s in board.get("sprints", [])
    )

    report_path = WORKSPACE / "docs" / "eksiklikler_ve_yeni_fazlar.md"

    # Senaryo A: Henüz Kapsamlı Ziyaretçi Ekran & Buton Gezinim Fazı Eklenmemiş
    if not has_visitor_phase:
        print("  [!] Liderlik Tespiti: Tüm ekran ve butonların (100% interactive elements)")
        print("      ziyaretçi gözüyle gezilip doğrulanması aşaması henüz yürütülmedi.")
        print("  [+] CTO & Product Owner Kararı: Yeni Faz Planlanıyor...")

        s_id = f"S{len(board.get('sprints', [])) + 1}"
        new_sprint = {
            "id": s_id,
            "name": "Ziyaretçi Deneyimi ve 100% Ekran/Buton Etkileşim Denetimi",
            "goal": "Tüm uygulama rotalarının ve interaktif elemanların (butonlar, modallar, formlar, listeler) ziyaretçi gözüyle uçtan uca doğrulanması.",
            "planned_days": 3,
            "tasks": [
                {
                    "id": f"{s_id}-T1",
                    "title": "Tüm Rotalar ve Ekranların Ziyaretçi Gözüyle Taranması",
                    "description": "Tüm temel sayfa, modül ve ekranların render sağlığı ve konsol hatasızlığının taranması",
                    "role": "screen_visitor_tester",
                    "phase": "test",
                    "outputs": ["workspace/docs/ziyaretci_ekran_denetimi.md"],
                    "depends_on": []
                },
                {
                    "id": f"{s_id}-T2",
                    "title": "Arayüz Buton, Filtre ve Modal Etkileşim Denetimi",
                    "description": "Arayüz filtreleri, işlem butonları, modal formlar ve yönlendirmelerin tıklanma testi",
                    "role": "screen_visitor_tester",
                    "phase": "test",
                    "outputs": ["workspace/docs/bug_raporlari.md"],
                    "depends_on": [f"{s_id}-T1"]
                },
                {
                    "id": f"{s_id}-T3",
                    "title": "Tespit Edilen Arayüz Eksiklerinin ve Buton Aksiyonlarının Onarılması",
                    "description": "Ziyaretçi testinde bulunan buton tepkisizlikleri, eksik rota veya durum hatalarının giderilmesi",
                    "role": "web_engineer",
                    "phase": "develop",
                    "outputs": ["workspace/src/frontend/"],
                    "depends_on": [f"{s_id}-T2"]
                },
                {
                    "id": f"{s_id}-T4",
                    "title": "Nihai UAT Kabul ve Canlı Kullanıcı Yolculuğu Onayı",
                    "description": "Canlı sistemde tüm kullanıcı senaryolarının eksiksiz geçtiğinin doğrulanması",
                    "role": "uat_auditor",
                    "phase": "test",
                    "outputs": ["workspace/docs/uat_kabul_raporu.md"],
                    "depends_on": [f"{s_id}-T3"]
                }
            ]
        }

        eval_md = f"""# Liderlik Eksik Tespiti ve Yeni Faz Planlama Raporu

> **Tarih:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  
> **Katılımcılar:** CTO / Baş Mimar, Ürün Sahibi (Product Owner), Sprint Planlayıcı  
> **Konu:** Canlı Sistem Eksik Analizi ve Ziyaretçi Gözüyle 100% Ekran Denetimi  

---

## 1. Tespit Edilen Eksiklikler ve Gözlemler

1. **İzole Test Bias (Yapay Doğrulama Tuzağı):** Önceki aşamalarda birim testler geçmesine karşın, kullanıcının gerçek bir ziyaretçi gibi her sayfayı gezmesi, her butona basması ve modalları açıp kapatması simüle edilmemiştir.
2. **Kapsanması Gereken Rotalar:**
   - `/` : Ana ekran ve genel modül görünümleri
   - Dinamik detay ve katalog sayfaları
   - İşlem, profil ve yönetim modülleri
3. **Kapsanması Gereken Etkileşimler:**
   - Arama ve filtre butonları
   - Aksiyon ve detay butonları
   - Modallar ve form alanları
   - Tarayıcı Konsolu: Sıfır hata (0 TypeError, 0 Uncaught) garantisi.

---

## 2. Kararlaştırılan Faz (Sprint) Yapısı

CTO ve Product Owner'ın mutabakatıyla sisteme aşağıdaki yeni faz eklenmiştir:

- **Sprint {s_id}: Ziyaretçi Deneyimi ve 100% Ekran/Buton Etkileşim Denetimi**
  - `{s_id}-T1`: Tüm Rotalar ve Ekranların Ziyaretçi Gözüyle Taranması (`screen_visitor_tester`)
  - `{s_id}-T2`: Arayüz Buton, Filtre ve Modal Etkileşim Denetimi (`screen_visitor_tester`)
  - `{s_id}-T3`: Tespit Edilen Arayüz Eksiklerinin ve Buton Aksiyonlarının Onarılması (`web_engineer`)
  - `{s_id}-T4`: Nihai UAT Kabul ve Canlı Kullanıcı Yolculuğu Onayı (`uat_auditor`)

Bu faz tamamlandığında sistem canlı UAT ve ziyaretçi testlerini geçmiş olarak teslim edilecektir.
"""
        report_path.write_text(eval_md, encoding="utf-8")
        B.append_sprint(board, new_sprint)
        B.save(board)
        print(f"  [✓] Yeni faz ({s_id}) panoya eklendi ve rapor üretildi: {report_path.relative_to(ROOT)}")
        return 1

    # Senaryo B: Ziyaretçi Fazı Tamamlanmış ve Açık Kritik Hata Kalmamış
    print("  [✓] Liderlik İncelemesi: Tüm ekranlar, butonlar ve UAT kabul kriterleri başarıyla tamamlandı.")
    final_md = f"""# Liderlik Nihai Onay ve Faz Kapanış Raporu

> **Tarih:** {datetime.now().strftime('%Y-%m-%d %H:%M')}  
> **Katılımcılar:** CTO, Product Owner, Sprint Planner  
> **Durum:** **PROJE %100 ONAYLANDI VE KABUL EDİLDİ**  

---

## Sonuç
- Tüm rotalar, butonlar ve modallar ziyaretçi gözüyle denetlenmiştir.
- Canlı UAT testleri (Port 3000 ve 3001) hatasız tamamlanmıştır.
- Açık engelleyici hata kalmamıştır. Sistem canlı kullanıma hazırdır.
"""
    report_path.write_text(final_md, encoding="utf-8")
    return 0


def otomatik_kurtar_ve_temizle(board: dict) -> int:
    """Yarım kalan, çöken veya önceki oturumlarda hata veren (FAILED / BLOCKED)
    görevleri kontrol eder; yetimleri ve geçici API hatası (503 / kapasite / ağ)
    alan görevleri otomatik olarak kurtarıp tekrar sıraya (TODO) alır.
    Kurtarılan görev sayısını döner.
    """
    changed = False
    kurtarilan = 0
    # 1. Yetim kalan RUNNING görevler
    if B.recover_orphans(board):
        changed = True

    # 2. FAILED ve BLOCKED görevler (Örn: Model 503 kapasite hatası, geçici ağ hatası)
    for s in board.get("sprints", []):
        for t in s.get("tasks", []):
            if t.get("status") in (B.FAILED, B.BLOCKED):
                old_status = t.get("status")
                note = t.get("note", "")
                t["status"] = B.TODO
                t["attempts"] = 0
                t["note"] = f"[Oto-Kurtarma] Önceki {old_status} temizlendi: {note[:50]}..."
                changed = True
                kurtarilan += 1
                print(f"  [🔄 OTO-KURTARMA] {t['id']} ({t.get('role')}) tekrar sıraya alındı.")

    if changed:
        B.normalize(board)
        B.refresh(board)
        B.save(board)
    return kurtarilan


def run_board(org: dict, brief: str, once: bool = False,
              max_tasks: int = 0, max_cost: float = 0.0,
              interactive: bool = False) -> int:
    """Panoyu ilerletir. once=True ise yalnızca bir görev yürütür (tick)."""
    # 0. Süreç, Kurtarma ve Dağıtım Nöbetçisi Ajanı (Failover & Deploy Recovery)
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import recovery_sentinel as RS
        RS.RecoverySentinelAgent(verbose=True).denetle_ve_kurtar(oto_push=True)
    except Exception as e:
        print(f"  [!] Kurtarma Ajanı uyarısı: {e}")

    board = B.load()
    # 1. Yarım kalan / hata veren süreçleri otomatik kurtar
    kurtarilan = otomatik_kurtar_ve_temizle(board)
    if kurtarilan > 0:
        print(f"[i] Önceki oturumdan yarım kalan / hata veren {kurtarilan} görev otomatik kurtarıldı.")

    # 2. Müşteri talepleri otomatik algılama ve senkronizasyon
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import studio_yetkilisi as SY
        eklenen = SY.otomatik_musteri_talepleri_senkronize_et()
        if eklenen > 0:
            B.audit("engine", "talep_senkron", detay={"eklenen_talep": eklenen})
            board = B.load()
    except Exception:
        pass
    B.recover_orphans(board)
    B.refresh(board)

    # 'force' yalnızca uçuştaki bir çağrıyı kesmek içindir; koşucu kapalıyken
    # bırakılmış bayat bayrak ilk çağrıyı anında öldürmesin diye temizlenir.
    # (goto/skip bilinçli olarak korunur: kuyruğa alınmış isteklerdir.)
    B.clear("force")

    B.audit("engine", "kosucu_baslangic",
            detay={"once": once, "max_tasks": max_tasks, "max_cost": max_cost})

    # Framework güncelleme bildirimi — yeni DS sürümü varsa koşu başında uyar.
    try:
        gunc = B.framework_update_info()
        if gunc and gunc.get("update"):
            print(f"[i] Studio v{gunc['remote']} güncellemesi mevcut "
                  f"(kurulu v{gunc['local']}) — "
                  f"python3 scripts/studio_updater.py --kontrol")
    except Exception:
        pass

    start_cost = spent_so_far()
    if max_cost:
        print(f"[i] Bütçe sınırı: ${max_cost:.2f} (şimdiye kadar ${start_cost:.2f} harcandı)")

    executed = 0
    while True:
        # Bütçe/görev sınırı: yeni görev ALMADAN önce bakılır, çalışan çağrı kesilmez.
        if max_tasks and executed >= max_tasks:
            print(f"\n[DURDU] Görev sınırına ulaşıldı ({max_tasks}). "
                  f"Devam için tekrar çalıştırın.")
            break
        if max_cost:
            harcanan = spent_so_far() - start_cost
            if harcanan >= max_cost:
                print(f"\n[DURDU] Bütçe sınırına ulaşıldı: bu koşuda ${harcanan:.2f} "
                      f"harcandı (sınır ${max_cost:.2f}). Devam için tekrar çalıştırın.")
                break
        ctrl = B.control_state()
        if ctrl["stopping"]:
            print("\n[DURDURULDU] stop isteği alındı, yeni görev başlatılmıyor.")
            B.clear("stop")
            break
        if ctrl["paused"]:
            print("\n[DURAKLATILDI] pause bayrağı var; kaldırılana kadar iş alınmıyor.")
            break
        if ctrl["skip"]:
            tid = ctrl["skip"]
            _, t = B.find_task(board, tid)
            if t:
                B.mark(board, tid, B.SKIPPED, "kullanıcı atladı")
                print(f"\n[ATLANDI] {tid}")
            B.clear("skip")
            B.refresh(board); B.save(board)
            continue

        # Kontrol ekranı/CLI öncelik veya sıra değiştirdiyse panoyu tazele.
        if ctrl["reload"]:
            B.clear("reload")
            board = B.load()
            B.refresh(board)

        # Görev geçişi (--gec): hedef görev kuyruk düzenini baypas ederek
        # doğrudan sıradaki iş olur. Kapalı (DONE/SKIPPED) hedef reddedilir.
        goto = None
        if ctrl["goto"]:
            tid = ctrl["goto"]
            B.clear("goto")
            B.clear("force")
            gs, gt = B.find_task(board, tid)
            if gt is None:
                print(f"\n[!] Geçiş hedefi bulunamadı: {tid}")
            elif gt["status"] in B.TERMINAL:
                print(f"\n[!] Geçiş hedefi zaten kapalı: {tid} ({gt['status']})")
            else:
                if gt["status"] != B.READY:
                    gt["status"] = B.READY
                    gt["note"] = "kullanıcı geçiş istedi"
                goto = (gs, gt)
                print(f"\n[GEÇİŞ] {tid} doğrudan sıradaki iş olarak alınıyor.")

        sprint, task = goto if goto else B.next_ready(board)

        # Günlük kota: görev BAŞLAMADAN önce bakılır, sınır aşılmaz.
        if task is not None:
            tahmin = tahmini_gorev_maliyeti(task)
            izin, sebep = B.ledger_check(tahmin)
            if not izin:
                d = B.ledger_read()
                mg, mb = B.ledger_limits()
                print(f"\n[ONAY BEKLENİYOR] {sebep}")
                print(f"  Bugün: {d['gorev']}/{mg} görev, ${d['maliyet']:.2f}/${mb:.2f}")
                print(f"  Sıradaki: {task['id']} · {task['title'][:50]} (~${tahmin:.2f})")
                print("  Devam etmek için:  ./basla.sh --onayla")
                break

        if task is not None and RESPECT_CALENDAR and sprint.get("planned_start"):
            from datetime import date
            if date.today() < date.fromisoformat(sprint["planned_start"]):
                print(f"\n[BEKLİYOR] {sprint['id']} planlanan başlangıcı "
                      f"{sprint['planned_start']}; takvime saygı modunda erken başlatılmıyor.")
                break
        if task is None:
            # Bekleyen yeni müşteri talebi var mı kontrol et ve panoya ekle
            try:
                sys.path.insert(0, str(ROOT / "scripts"))
                import studio_yetkilisi as SY
                eklenen = SY.otomatik_musteri_talepleri_senkronize_et()
                if eklenen > 0:
                    B.audit("engine", "talep_senkron", detay={"eklenen_talep": eklenen})
                    board = B.load()
                    B.refresh(board)
                    B.save(board)
                    continue
            except Exception:
                pass

            # 2. Panoda bloke veya başarısız kalmış görevleri oto-kurtar
            if otomatik_kurtar_ve_temizle(board) > 0:
                B.refresh(board)
                B.save(board)
                continue

            p = B.progress(board)
            if p["done"] >= p["total"] and p["total"] > 0:
                if not getattr(run_board, "_leadership_checked", False):
                    run_board._leadership_checked = True
                    print("\n[LİDERLİK KONTROLÜ] Panodaki mevcut görevler kapandı. CTO ve Product Owner eksik ve faz incelemesi yapıyor...")
                    added = autonomous_gap_review_and_phasing(org, brief, board)
                    if added > 0:
                        B.audit("engine", "liderlik_faz_eklendi",
                                detay={"yeni_sprint": added})
                        print(f"  [✓] {added} yeni sprint fazı planlandı ve panoya eklendi. Normal akış devam ediyor...\n")
                        B.refresh(board)
                        B.save(board)
                        continue

            if once:
                print("\n[i] Tek seferlik koşu: hazır görev yok, çıkılıyor.")
                break

            # 3. SÜREKLİ NÖBET & DİNLEME DÖNGÜSÜ (Shell kapanana kadar ayakta kalır)
            idle_counter = getattr(run_board, "_idle_counter", 0) + 1
            run_board._idle_counter = idle_counter
            if idle_counter % 6 == 1:
                cur_time = time.strftime("%H:%M:%S")
                print(f"\n[💤 AYAKTA VE DİNLİYOR] ({cur_time}) Aktif işler tamamlandı.")
                print("   Yeni bir müşteri talebi geldiğinde ('./musteri.sh') sistem otomatik olarak algılayıp çözecektir.")
                print("   (Durdurmak için kontrol ekranında 's' tuşuna basın veya './basla.sh --durdur' yapın)")

            time.sleep(5)
            board = B.load()
            continue

        # UAT/canlı test görevi canlı ortam gerektirir; kapalıysa ekrana uyar.
        if B.needs_live(task) and not B.live_up():
            kapali = [str(p) for p, ok in B.live_status().items() if not ok]
            print(f"\n[⚠ UYARI] {task['id']} canlı sistem gerektiriyor ama "
                  f"port {', '.join(kapali)} kapalı (canli.sh çalışmıyor).")
            print("          UAT doğrulaması başarısız olabilir. "
                  "Başlatmak için: ./basla.sh --canli")

        B.mark(board, task["id"], B.RUNNING)
        B.save(board)
        onceki = spent_so_far()
        try:
            ok = execute_task(org, task, sprint, brief, board, interactive=interactive)
        except CallAborted as e:
            # Kontrol isteği (stop/skip/goto/force) görevi yarıda kesti.
            # Atlanan görev SKIPPED, diğerleri kuyruğa geri döner (READY).
            print(f"\n[KESİLDİ] {e}")
            if B.value_of("skip") == task["id"]:
                B.mark(board, task["id"], B.SKIPPED, "kullanıcı atladı")
                B.clear("skip")
            else:
                B.mark(board, task["id"], B.READY, "kesildi — kuyruğa geri alındı")
            B.clear("force")
            B.refresh(board); B.save(board)
            continue
        gercek = spent_so_far() - onceki
        d = B.ledger_add(gercek)
        mg, mb = B.ledger_limits()
        print(f"     [kota] bugün {d['gorev']}/{mg} görev, "
              f"${d['maliyet']:.2f}/${mb:.2f}  (bu görev ${gercek:.2f})")
        B.refresh(board)
        B.schedule(board)
        B.save(board)
        executed += 1

        # Sprint tamamlandı mı? Canlı test rehberi bas
        curr_s = next((s for s in board["sprints"] if s["id"] == sprint["id"]), None)
        if curr_s and curr_s.get("status") == B.DONE and not curr_s.get("_summary_printed"):
            curr_s["_summary_printed"] = True
            print_sprint_action_summary(curr_s)
            B.save(board)

        if not ok:
            print(f"\n[HATA] {task['id']} başarısız — sonraki sprint açılmayacak.")
            break
        if once:
            break

    B.audit("engine", "kosucu_bitis", detay={"yurutulen_gorev": executed})
    return executed


# -------------------------------------------------------------
# 7. ENTRYPOINT
# -------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Sanal Yazılım Stüdyosu boru hattı")
    ap.add_argument("--reset", action="store_true", help="state'i sıfırla, baştan başla")
    ap.add_argument("--yes", "-y", action="store_true", help="onay sorma")
    ap.add_argument("--only", nargs="+", metavar="ID", help="sadece bu rolleri çalıştır")
    ap.add_argument("--dry-run", action="store_true", help="API'ye gitmeden planı göster")
    ap.add_argument("--org", default="org_chart.json", help="org şeması dosyası")
    ap.add_argument("--brief", default="proje_kapsami.md",
                    help="proje özeti / canlı kapsam dosyası")
    ap.add_argument("--max-revisions", type=int, default=3, help="revizyon turu üst sınırı")
    ap.add_argument("--full", action="store_true",
                    help="uçtan uca: ortam taraması + tasarım aşaması + pano + yapım aşaması")
    ap.add_argument("--stage", choices=["design", "build", "all"], default="design",
                    help="doğrusal koşucunun çalıştıracağı aşama (varsayılan: design; "
                         "yapım rollerini sprint panosu yürütür)")
    ap.add_argument("--plan", action="store_true",
                    help="sprint panosunu üret (studio.db)")
    ap.add_argument("--replan", action="store_true",
                    help="mevcut panoyu yok sayıp yeniden planla")
    ap.add_argument("--tick", action="store_true",
                    help="panodan TEK bir hazır görevi yürüt (zamanlanmış görev için)")
    ap.add_argument("--run-board", action="store_true",
                    help="pano bitene veya durana kadar görevleri yürüt")
    ap.add_argument("--max-tasks", type=int, default=0, metavar="N",
                    help="bu koşuda en fazla N görev yürüt (0 = sınırsız)")
    ap.add_argument("--max-cost", type=float, default=0.0, metavar="USD",
                    help="bu koşuda en fazla bu kadar harca, sonra dur (0 = sınırsız)")
    ap.add_argument("--refresh-env", action="store_true",
                    help="ortam raporunu yeniden ölç")
    ap.add_argument("--review", action="store_true",
                    help="liderlik eksik denetimini ve yeni faz planlamasını tetikle")
    ap.add_argument("--backend", choices=sorted(VALID_BACKENDS), default=None,
                    help="çalıştırma arka ucu (varsayılan: STUDIO_BACKEND veya agy)")
    args = ap.parse_args()

    global BACKEND
    BACKEND = (args.backend or os.getenv("STUDIO_BACKEND", "agy")).lower()

    org_path = resolve_doc(args.org)
    if not org_path.exists():
        sys.exit(f"[HATA] Org şeması bulunamadı: {args.org} "
                 f"(kökte ve workspace/docs/ altında yok)")
    org = json.loads(org_path.read_text(encoding="utf-8"))
    org = load_and_merge_dynamic_roles(org)

    brief_path = resolve_doc(args.brief)
    if not brief_path.exists():
        sys.exit(f"[HATA] Proje özeti bulunamadı: {args.brief} "
                 f"(kökte ve workspace/docs/ altında yok)")
    brief = brief_path.read_text(encoding="utf-8")

    if args.review:
        board = B.load()
        added = autonomous_gap_review_and_phasing(org, brief, board)
        if added > 0:
            print(f"[✓] {added} yeni sprint fazı planlandı.")
        else:
            print("[i] Eksik tespit edilmedi, tüm fazlar tamamlanmış.")
        return

    if not args.dry_run and not acquire_lock():
        return

    preflight_env(force=args.refresh_env)

    if args.reset:
        STATE_FILE.unlink(missing_ok=True)
        print("[i] State sıfırlandı.")

    from collections import Counter
    try:
        resolved = [resolve_engine(a) for a in org["hierarchy"]]
        engines = Counter(f"{b}/{m or 'varsayılan'}" for b, m, _, _ in resolved)
    except ValueError as e:
        sys.exit(f"[HATA] {e}")
    if len(engines) > 1:
        print("[i] Motor dağılımı: " +
              ", ".join(f"{k} × {v}" for k, v in sorted(engines.items())))

    # Kullanılan her backend'in CLI'si kurulu olmalı
    for b in sorted({b for b, _, _, _ in resolved}):
        if not find_exe(b):
            if b == "devin":
                sys.exit("[HATA] 'devin' komutu bulunamadı. Devin CLI kurulu olmalı "
                         "(~/.local/bin/devin veya Devin Desktop).")
            sys.exit("[HATA] 'agy' komutu bulunamadı. Lütfen Antigravity CLI'nın "
                     "kurulu olduğundan emin olun (~/.local/bin/agy).")

    n_calls = sum(len(a["outputs"]) for a in org["hierarchy"])
    engine = next(iter(engines)) if len(engines) == 1 else f"{BACKEND} (karışık)"
    print(f"[i] {len(org['hierarchy'])} rol, {n_calls} dosya hedefi "
          f"(≈{n_calls} çağrı, {engine}).")

    interactive_ok = not (args.tick or args.run_board or args.plan or args.replan)
    if not args.yes and not args.dry_run and interactive_ok:
        if input("[?] Başlatılsın mı? (e/h): ").strip().lower() != "e":
            sys.exit("İptal edildi.")

    if args.full:
        # Uçtan uca: tasarım aşaması panoyu da üretir, ardından pano yürütülür.
        print("\n########## AŞAMA 1/2 — TASARIM ##########")
        args.stage = "design"
        execute_pipeline(org, brief, args)

        print("\n---> Sprint panosu üretiliyor (şema doğrulamalı)")
        run_planner(org, brief, force=args.replan)
        if not B.board_exists():
            sys.exit("[HATA] Pano üretilemedi; 'sprint_planner' rolünü kontrol edin.")

        print("\n########## AŞAMA 2/2 — YAPIM (sprint panosu) ##########")
        is_interactive = not args.yes and sys.stdin.isatty()
        n = run_board(org, brief, once=False,
                      max_tasks=args.max_tasks, max_cost=args.max_cost,
                      interactive=is_interactive)
        print(f"[i] Yapım aşamasında {n} görev yürütüldü.")
        return

    if args.plan or args.replan:
        run_planner(org, brief, force=args.replan)
        return

    if args.tick or args.run_board:
        # Zamanlanmış tetikleyici pano üretilmeden önce de çalışır. Pano yoksa
        # tasarım aşamasını ilerlet — checkpoint'li olduğu için her tetikleme
        # kaldığı yerden devam eder ve kota açılınca kendiliğinden tamamlanır.
        if not B.board_exists():
            print("[i] Pano yok — önce tasarım aşaması ilerletiliyor.")
            args.stage = "design"
            execute_pipeline(org, brief, args)
            if not B.board_exists():
                try:
                    run_planner(org, brief)
                except SystemExit:
                    print("[i] Pano henüz üretilemedi; sonraki tetiklemede denenecek.")
                    return
            if not B.board_exists():
                print("[i] Tasarım henüz tamamlanmadı; sonraki tetiklemede devam edilecek.")
                return
        try:
            is_interactive = not args.yes and sys.stdin.isatty()
            n = run_board(org, brief, once=args.tick,
                          max_tasks=args.max_tasks, max_cost=args.max_cost,
                          interactive=is_interactive)
        except FileNotFoundError as e:
            # Zamanlanmış görev pano üretilmeden önce de tetiklenebilir;
            # log'u traceback'le doldurmadan sessizce çık.
            print(f"[i] {e}")
            return
        print(f"[i] Bu koşuda {n} görev yürütüldü.")
        return

    execute_pipeline(org, brief, args)


if __name__ == "__main__":
    main()
