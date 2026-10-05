#!/usr/bin/env python3
"""Deney kolları: aynı girdi paketiyle birden çok yalıtılmış proje klasörü kurar (issue #175). Servis BAŞLATMAZ.

  python3 scripts/deney_kur.py kur --kaynak <mevcut proje> --hedef <ana dizin> --onek oobeya-ui-vue-studio \\
        --brief <tohum brief.md> [--kollar claude,gemini,devin] [--framework-url URL] [--github-sahip cihan53] [--plan]
  python3 scripts/deney_kur.py esitle --kaynak-kol <dizin> --hedefler <dizin>,<dizin> [--plan]    # son brief'i diğer kollara kopyalar

Kol başına: framework `git clone` (origin → `framework`, push kapalı), kaynak projeden org_chart + keşif/ekran analizleri + kaynak taramaları + config kopyası,
kola özgü backend/model/port (`workspace/calistir.sh`, `workspace/deney.json`), depo hijyeni, ilk commit, isteğe bağlı özel GitHub deposu.
Süreci (koşucu, panel, ortam) kullanıcı `workspace/calistir.sh` ile başlatır.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

KOLLAR = {
    "claude": {"backend": "claude", "model": "sonnet", "model_env": "STUDIO_CLAUDE_MODEL"},
    "gemini": {"backend": "agy", "model": "gemini-3.8-flash-high", "model_env": "STUDIO_AGY_MODEL"},
    "devin": {"backend": "devin", "model": "", "model_env": "STUDIO_DEVIN_MODEL"},
}
FRAMEWORK_URL = "https://github.com/cihan53/digital-software-studio.git"
KOPYALA_DOSYA = ["workspace/docs/org_chart.json", "workspace/studio.config.json"]
KOPYALA_GLOB = ["workspace/docs/kaynak_proje_*.md"]
KOPYALA_DIZIN = ["workspace/docs/ekranlar"]          # _ham ve _gorsel yerel kalır (git dışı), envanter ve onay kartları için gerekir


def sh(*a, cwd=None, check=True):
    r = subprocess.run(a, cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(a)} → {r.stderr.strip() or r.stdout.strip()}")
    return r


def portlar(i: int) -> dict:
    return {"nuxt": 3000 + 100 * i, "backend": 8080 + 100 * i, "mock": 4010 + 100 * i, "panel": 8090 + i}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12] if p.exists() else "-"


def girdi_ozeti(d: Path) -> dict:
    cfg = {}
    try:
        cfg = json.loads((d / "workspace/studio.config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    plan = "-"
    try:
        sys.path.insert(0, str(d))
        import sqlite3
        db = d / "workspace" / "studio.db"
        if db.exists():
            c = sqlite3.connect(db)
            rows = c.execute("select id, rol, baslik, aciklama, ciktilar, bagimlilik from pano_gorevleri order by sprint_id, sira").fetchall()
            plan = hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()[:12] if rows else "-"
    except Exception:
        pass
    return {"brief": sha(d / "workspace/docs/proje_kapsami.md"), "org_chart": sha(d / "workspace/docs/org_chart.json"),
            "planlama": hashlib.sha256(json.dumps(cfg.get("planlama"), sort_keys=True).encode()).hexdigest()[:12],
            "envanter": sha(d / "workspace/docs/ekranlar/_birimler.md"), "plan": plan}


def calistir_yaz(d: Path, ad: str, kol: dict, p: dict) -> None:
    model = (f'export {kol["model_env"]}="{kol["model"]}"\n' if kol["model"] else "")
    s = f'''#!/usr/bin/env bash
# {ad} kolu — backend={kol["backend"]}{(" model=" + kol["model"]) if kol["model"] else ""}. Süreci SİZ başlatırsınız: bu betik yalnız ortamı hazırlar ve basla.sh'i çağırır.
# Aynı girdi paketi (brief, org_chart, plan, keşif) diğer kollarla aynıdır; farklı olan yalnız backend/model ve portlardır.
cd "$(dirname "$0")/.." || exit 1
export STUDIO_BACKEND="{kol["backend"]}"
{model}export STUDIO_WEB_PORT="{p["panel"]}"
export NUXT_PORT="{p["nuxt"]}" BACKEND_PORT="{p["backend"]}" MOCK_PORT="{p["mock"]}"
echo "[{ad}] backend={kol["backend"]} panel=http://127.0.0.1:{p["panel"]}/panel nuxt={p["nuxt"]}"
exec ./basla.sh "$@"
'''
    f = d / "workspace" / "calistir.sh"
    f.write_text(s, encoding="utf-8", newline="\n")
    f.chmod(f.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)


def kol_kur(ad: str, i: int, a) -> Path:
    kol = KOLLAR[ad]
    p = portlar(i)
    hedef = Path(a.hedef) / f"{a.onek}-{ad}"
    if hedef.exists():
        raise SystemExit(f"[HATA] {hedef} zaten var; silmeden/üzerine yazmadan çıkıldı.")
    kaynak = Path(a.kaynak or a.kaynak_yol or ".")
    sh("git", "clone", "-q", a.framework_url, str(hedef))
    sh("git", "remote", "rename", "origin", "framework", cwd=hedef)
    sh("git", "remote", "set-url", "--push", "framework", "DISABLED", cwd=hedef)       # framework deposuna yanlışlıkla push edilemez
    (hedef / "workspace" / "docs").mkdir(parents=True, exist_ok=True)
    if not a.sifir:
        for rel in KOPYALA_DOSYA:
            if (kaynak / rel).exists():
                shutil.copy2(kaynak / rel, hedef / rel)
        for g in KOPYALA_GLOB:
            for f in kaynak.glob(g):
                shutil.copy2(f, hedef / f.relative_to(kaynak))
        for rel in KOPYALA_DIZIN:
            if (kaynak / rel).exists():
                shutil.copytree(kaynak / rel, hedef / rel, dirs_exist_ok=True)
    elif (kaynak / ".env").exists():
        shutil.copy2(kaynak / ".env", hedef / ".env")           # yalnız giriş bilgisi; .gitignore ile git dışı
    if a.brief:
        shutil.copy2(a.brief, hedef / "workspace/docs/proje_kapsami.md")
    elif (kaynak / "workspace/docs/proje_kapsami.md").exists():
        shutil.copy2(kaynak / "workspace/docs/proje_kapsami.md", hedef / "workspace/docs/proje_kapsami.md")
    cfgp = hedef / "workspace/studio.config.json"
    cfg = json.loads(cfgp.read_text(encoding="utf-8")) if cfgp.exists() else {}
    if a.sifir:
        cfg = {"source": {"path": a.kaynak_yol, "live_url": a.canli_url, "kind": a.tur}}   # sıfır: yalnız kaynak tanımı; analiz/keşif/plan çerçeveyle üretilir
    else:
        cfg.setdefault("planlama", {})["uretici"] = "birim"
    cfg["live"] = {"ports": [p["nuxt"], p["backend"]]}
    cfg["deney"] = {"kol": ad, "backend": kol["backend"], "model": kol["model"], "portlar": p}
    cfgp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    calistir_yaz(hedef, ad, kol, p)
    (hedef / "workspace" / "deney.json").write_text(json.dumps({"kol": ad, **kol, "portlar": p, "girdi": girdi_ozeti(hedef)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sh(sys.executable, "scripts/depo_hijyeni.py", "--uygula", cwd=hedef)
    sh("git", "add", "-A", cwd=hedef)
    sh("git", "commit", "-q", "-m", f"chore: {ad} kolu kurulumu (framework klonu, ortak girdi paketi, depo hijyeni)", cwd=hedef, check=False)
    if a.github_sahip:
        repo = f"{a.github_sahip}/{a.onek}-{ad}"
        sh("gh", "repo", "create", repo, "--private", "-d", f"Deney kolu: {ad} ({kol['backend']})")
        sh("git", "remote", "add", "origin", f"https://github.com/{repo}.git", cwd=hedef)
        sh("git", "push", "-q", "-u", "origin", "HEAD:main", cwd=hedef)
    if a.plan:
        plan_uret(hedef)
    return hedef


def plan_uret(d: Path) -> str:
    sh(sys.executable, "scripts/birim_envanteri.py", cwd=d)
    r = sh(sys.executable, "scripts/plan_birim.py", "--yaz", cwd=d)
    return r.stdout.strip().splitlines()[0] if r.stdout.strip() else ""


def tablo(dizinler: list[Path]) -> str:
    oz = {d.name: girdi_ozeti(d) for d in dizinler}
    alanlar = ["brief", "org_chart", "planlama", "envanter", "plan"]
    satir = ["| Girdi | " + " | ".join(oz) + " | Aynı mı |", "|---|" + "---|" * (len(oz) + 1)]
    for al in alanlar:
        v = [o[al] for o in oz.values()]
        satir.append(f"| {al} | " + " | ".join(v) + f" | {'✓' if len(set(v)) == 1 else '✗'} |")
    return "\n".join(satir)


def esitle(a) -> None:
    kay = Path(a.kaynak_kol)
    for h in [Path(x) for x in a.hedefler.split(",")]:
        if (h / "workspace/studio.db").exists():
            import sqlite3
            c = sqlite3.connect(h / "workspace/studio.db")
            basladi = c.execute("select count(*) from pano_gorevleri where durum not in ('TODO','READY')").fetchone()[0] if c.execute(
                "select name from sqlite_master where name='pano_gorevleri'").fetchone() else 0
            if basladi and a.plan:
                print(f"[!] {h.name}: görevler başlamış ({basladi}); plan yeniden üretilmedi.")
                continue
        shutil.copy2(kay / "workspace/docs/proje_kapsami.md", h / "workspace/docs/proje_kapsami.md")
        src = json.loads((kay / "workspace/studio.config.json").read_text(encoding="utf-8"))
        cfgp = h / "workspace/studio.config.json"
        cfg = json.loads(cfgp.read_text(encoding="utf-8"))
        cfg["planlama"] = src.get("planlama", cfg.get("planlama"))
        cfgp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if a.plan:
            plan_uret(h)
    print(tablo([kay] + [Path(x) for x in a.hedefler.split(",")]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    k = sp.add_parser("kur")
    k.add_argument("--kaynak", default="")
    k.add_argument("--hedef", required=True)
    k.add_argument("--onek", required=True)
    k.add_argument("--brief", default=None)
    k.add_argument("--kollar", default="claude,gemini,devin")
    k.add_argument("--framework-url", default=FRAMEWORK_URL)
    k.add_argument("--github-sahip", default=None)
    k.add_argument("--plan", action="store_true")
    k.add_argument("--sifir", action="store_true", help="hiçbir analiz/org_chart/plan kopyalama; yalnız brief + kaynak tanımı")
    k.add_argument("--kaynak-yol", default="", help="--sifir: kaynak proje yolu")
    k.add_argument("--canli-url", default="", help="--sifir: canlı referans URL")
    k.add_argument("--tur", default="", help="--sifir: kaynak türü (örn. angular-spa)")
    e = sp.add_parser("esitle")
    e.add_argument("--kaynak-kol", required=True)
    e.add_argument("--hedefler", required=True)
    e.add_argument("--plan", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "kur":
        ds = []
        for i, ad in enumerate(a.kollar.split(",")):
            if ad not in KOLLAR:
                raise SystemExit(f"[HATA] bilinmeyen kol: {ad} ({', '.join(KOLLAR)})")
            d = kol_kur(ad, i, a)
            ds.append(d)
            print(f"✓ {d}")
        print(tablo(ds))
    else:
        esitle(a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
