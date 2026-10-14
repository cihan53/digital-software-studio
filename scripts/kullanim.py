#!/usr/bin/env python3
"""LLM kullanım/kota ekranı verisi (issue #295): agy (Gemini), claude ve devin için kalan kullanım oranları.

Kaynaklar (hiçbiri model çağrısı harcamaz):
  agy    : `agy -p="/usage"`      → model grubu · pencere · kalan % · sıfırlanma (tab ayrımlı)
  claude : `claude -p "/usage"`   → oturum ve hafta % kullanılan + sıfırlanma
  devin  : `devin auth status`    → yalnız oturum durumu (CLI kalan kota bilgisi vermiyor)
Önbellek: 3 dk; panel arka planda yenilettirir (claude npx çağrısı ~10 sn sürebilir). CLI: python3 scripts/kullanim.py [--yenile] [--json]
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TTL = 180
_KILIT = threading.Lock()
_ONBELLEK: dict = {"zaman": 0.0, "veri": None, "yenileniyor": False}


def _calistir(cmd: list[str], sn: int = 60, cwd: str | None = None) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=sn, cwd=cwd or str(Path.home()))
        return r.returncode, (r.stdout or "") + (("\n" + r.stderr) if r.returncode != 0 else "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, f"{type(e).__name__}: {e}"


def _yerel(iso: str) -> str:
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
        return d.strftime("%d.%m %H:%M")
    except ValueError:
        return iso


def agy_ayristir(metin: str) -> list[dict]:
    """'Gemini Models\\tWeekly Limit Remaining\\t0%\\t2026-10-14T06:20:41Z' satırları."""
    satirlar = []
    for ln in metin.splitlines():
        p = [x.strip() for x in ln.split("\t")]
        if len(p) < 3 or "Remaining" not in p[1]:
            continue
        m = re.fullmatch(r"(\d+)\s*%", p[2])
        sifir = p[3] if len(p) > 3 else ""
        satirlar.append({"grup": p[0], "pencere": p[1].replace(" Remaining", "").replace("Weekly Limit", "Haftalık").replace("Five Hour Limit", "5 saatlik"),
                         "kalan": int(m.group(1)) if m else None, "durum": "" if m else p[2], "sifirlanma": _yerel(sifir) if sifir else ""})
    return satirlar


def claude_ayristir(metin: str) -> list[dict]:
    satirlar = []
    for ad, rx in (("Oturum", r"Current session:\s*(\d+)%\s*used\s*·\s*resets\s*([^\n]+)"),
                   ("Haftalık (tüm modeller)", r"Current week \(all models\):\s*(\d+)%\s*used\s*·\s*resets\s*([^\n]+)"),
                   ("Haftalık (Opus)", r"Current week \(Opus[^)]*\):\s*(\d+)%\s*used\s*·\s*resets\s*([^\n]+)"),
                   ("Haftalık (Sonnet)", r"Current week \(Sonnet[^)]*\):\s*(\d+)%\s*used\s*·\s*resets\s*([^\n]+)")):
        m = re.search(rx, metin)
        if m:
            satirlar.append({"grup": "Claude", "pencere": ad, "kalan": max(0, 100 - int(m.group(1))), "durum": "", "sifirlanma": m.group(2).strip()})
    return satirlar


def agy_kullanim() -> dict:
    exe = os.getenv("STUDIO_AGY_BIN") or shutil.which("agy") or str(Path.home() / ".local/bin/agy")
    kod, cikti = _calistir([exe, "-p=/usage"], 60)
    satirlar = agy_ayristir(cikti)
    return {"ad": "Gemini (agy)", "satirlar": satirlar, "hata": "" if satirlar else cikti.strip()[:200] or f"kod {kod}"}


def claude_kullanim() -> dict:
    exe = os.getenv("STUDIO_CLAUDE_BIN") or shutil.which("claude")
    cmd = [exe, "-p", "/usage"] if exe else ["npx", "-y", "@anthropic-ai/claude-code", "-p", "/usage"]
    kod, cikti = _calistir(cmd, 120)
    satirlar = claude_ayristir(cikti)
    return {"ad": "Claude", "satirlar": satirlar, "hata": "" if satirlar else cikti.strip()[:200] or f"kod {kod}"}


def devin_kullanim() -> dict:
    exe = os.getenv("STUDIO_DEVIN_BIN") or shutil.which("devin") or str(Path.home() / ".local/bin/devin")
    kod, cikti = _calistir([exe, "auth", "status"], 30)
    acik = cikti.strip().lower().startswith("logged in")
    return {"ad": "Devin", "satirlar": [], "oturum": acik, "not": "Devin CLI kalan kota/ACU bilgisi vermiyor; yalnız oturum durumu ve proje içi kullanım gösterilir.",
            "hata": "" if acik else (cikti.strip()[:200] or f"kod {kod}")}


def proje_kullanimi(kok: Path = ROOT) -> dict:
    """Bu projenin kendi sayaçları: çağrı/token (trace) ve günlük kota (ledger)."""
    sonuc = {"cagri": 0, "token_in": 0, "token_out": 0, "bugun_cagri": 0, "backend": {}}
    idx = kok / "workspace/.trace/index.jsonl"
    bugun = datetime.now().strftime("%Y-%m-%d")
    if idx.exists():
        for ln in idx.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            sonuc["cagri"] += 1
            sonuc["token_in"] += int(r.get("tokens_in") or 0)
            sonuc["token_out"] += int(r.get("tokens_out") or 0)
            b = r.get("backend") or "?"
            sonuc["backend"][b] = sonuc["backend"].get(b, 0) + 1
            if str(r.get("ended_at") or r.get("started_at") or "").startswith(bugun):
                sonuc["bugun_cagri"] += 1
    try:
        sys.path.insert(0, str(kok))
        import studio_board as B
        d = B.ledger_read()
        mg, mb = B.ledger_limits()
        sonuc["gunluk"] = {"gorev": d.get("gorev"), "sinir_gorev": mg, "maliyet": d.get("maliyet"), "sinir_butce": mb}
    except Exception:
        sonuc["gunluk"] = None
    return sonuc


def topla(kok: Path = ROOT) -> dict:
    """Üç sağlayıcıyı eşzamanlı toplar."""
    sonuc, is_parcalari = {}, []

    def al(anahtar, fn):
        try:
            sonuc[anahtar] = fn()
        except Exception as e:                                   # noqa: BLE001
            sonuc[anahtar] = {"ad": anahtar, "satirlar": [], "hata": f"{type(e).__name__}: {e}"}

    for a, f in (("agy", agy_kullanim), ("claude", claude_kullanim), ("devin", devin_kullanim)):
        t = threading.Thread(target=al, args=(a, f), daemon=True)
        t.start()
        is_parcalari.append(t)
    for t in is_parcalari:
        t.join(150)
    return {"zaman": time.strftime("%H:%M:%S"), "saglayicilar": sonuc, "proje": proje_kullanimi(kok)}


def _arka_plan(kok: Path):
    try:
        veri = topla(kok)
        with _KILIT:
            _ONBELLEK.update(zaman=time.time(), veri=veri)
    finally:
        with _KILIT:
            _ONBELLEK["yenileniyor"] = False


def getir(kok: Path = ROOT, zorla: bool = False) -> dict:
    """Önbellekteki veriyi hemen döndürür; bayatsa arka planda yeniler (panel bloklanmaz)."""
    with _KILIT:
        bayat = zorla or time.time() - _ONBELLEK["zaman"] > TTL
        if bayat and not _ONBELLEK["yenileniyor"]:
            _ONBELLEK["yenileniyor"] = True
            threading.Thread(target=_arka_plan, args=(kok,), daemon=True).start()
        veri = _ONBELLEK["veri"] or {"zaman": "", "saglayicilar": {}, "proje": {}}
        return {**veri, "yenileniyor": _ONBELLEK["yenileniyor"]}


def metin(veri: dict) -> str:
    L = []
    for a, s in veri.get("saglayicilar", {}).items():
        L.append(f"── {s.get('ad', a)} ──")
        for r in s.get("satirlar", []):
            kalan = f"%{r['kalan']} kalan" if r.get("kalan") is not None else (r.get("durum") or "-")
            L.append(f"  {r['grup']:<22} {r['pencere']:<26} {kalan:<14} sıfırlanma: {r.get('sifirlanma') or '-'}")
        if "oturum" in s:
            L.append(f"  Oturum: {'açık' if s['oturum'] else 'KAPALI'}")
        if s.get("not"):
            L.append(f"  {s['not']}")
        if s.get("hata"):
            L.append(f"  ! {s['hata']}")
    p = veri.get("proje", {})
    if p:
        L.append("── Bu proje ──")
        L.append(f"  Çağrı {p.get('cagri', 0)} (bugün {p.get('bugun_cagri', 0)}) · token girdi {p.get('token_in', 0):,} / çıktı {p.get('token_out', 0):,}")
        g = p.get("gunluk")
        if g:
            L.append(f"  Günlük kota: {g.get('gorev')}/{g.get('sinir_gorev')} görev · ${(g.get('maliyet') or 0):.2f}/${(g.get('sinir_butce') or 0):.2f}")
    return "\n".join(L)


if __name__ == "__main__":
    v = topla(ROOT)
    print(json.dumps(v, ensure_ascii=False, indent=1) if "--json" in sys.argv else metin(v))
