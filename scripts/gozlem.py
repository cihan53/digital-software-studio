#!/usr/bin/env python3
"""Gözlem paneli verisi (v2, issue #259): neden beklediği, etkinlik akışı, görev değişikliği (git farkı).

Saf işlevler: panel (studio_web.py) ve testler çağırır; kendi başına durum tutmaz.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import studio_board as B  # noqa: E402

KIMLIK_RX = re.compile(r"OAuth session expired|Failed to authenticate|credits balance too low|Invalid API key|not logged in", re.I)
KOTA_RX = re.compile(r"rate limit|usage limit|quota|429|overloaded", re.I)
DIFF_LIMIT = 200_000


def log_kuyrugu(kok: Path = ROOT, n: int = 6000) -> str:
    p = kok / "workspace" / "logs" / "pipeline.log"
    try:
        with p.open("rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - n))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def bekleme_nedeni(board: dict | None, ctrl: dict, kosucu: bool, onay_bekliyor: dict | None,
                   canli: dict, canli_baslatilabilir: bool, log: str = "", cur: dict | None = None) -> dict | None:
    """Koşucu bir çağrı yürütmüyorsa NEDEN bekledi/durduğunu söyler: {kod, mesaj, eylem}. Çalışan görev varsa None."""
    cur = cur or {}
    if cur.get("role") and not cur.get("ended_at") and not cur.get("error") and kosucu:
        return None
    if board:
        _, run = B.find_running(board)
        if run and kosucu:
            return None
    if ctrl.get("stopping"):
        return {"kod": "durduruluyor", "mesaj": "Koşucu durduruluyor: çalışan görev bitince duracak.", "eylem": ""}
    if ctrl.get("paused"):
        return {"kod": "duraklatildi", "mesaj": "Duraklatıldı: görevler başlamıyor.", "eylem": "Sürdür düğmesi / ./basla.sh --surdur"}
    if onay_bekliyor:
        ob = onay_bekliyor
        return {"kod": "kota_onayi",
                "mesaj": f"Kota onayı bekleniyor: {ob.get('gorev')}/{ob.get('sinir_gorev')} görev, ${ob.get('maliyet', 0):.2f}/${ob.get('sinir_butce', 0):.2f}; sıradaki {ob.get('sonraki', '?')}.",
                "eylem": "Kota Onayla düğmesi / ./basla.sh --onayla"}
    tail = log or ""
    if KIMLIK_RX.search(tail[-3000:]):
        m = KIMLIK_RX.search(tail[-3000:]).group(0)
        return {"kod": "kimlik", "mesaj": f"Kimlik/hesap hatası: '{m}'. Bu kota değil; yeniden denemek işe yaramaz.",
                "eylem": "AI CLI'ya yeniden giriş yap (ör. claude /login), sonra koşucuyu yeniden başlat"}
    if not kosucu:
        return {"kod": "kosucu_yok", "mesaj": "Koşucu çalışmıyor.", "eylem": "./basla.sh (ya da workspace/yeniden_baslat.sh)"}
    if not board:
        return {"kod": "pano_yok", "mesaj": "Pano henüz yok: tasarım/planlama aşamasında.", "eylem": ""}
    _, nxt = B.next_ready(board)
    if nxt is not None:
        if B.needs_live(nxt) and not all(canli.values() or [False]):
            kapali = [str(p) for p, v in canli.items() if not v]
            return {"kod": "canli_kapali",
                    "mesaj": f"Canlı sistem kapalı (port {', '.join(kapali) or '?'}): {nxt['id']} bunu gerektiriyor.",
                    "eylem": "Panel → Yerel Ortam ya da ./basla.sh --canli" if canli_baslatilabilir else "Önce yerel_ortam.sh üretilmeli"}
        if KOTA_RX.search(tail[-1500:]):
            return {"kod": "limit", "mesaj": "AI servisi limit/kota hatası veriyor; motor bekleyerek yeniden deniyor.", "eylem": "Beklemek ya da motoru değiştirmek (panel → Motor)"}
        return {"kod": "baslamak_uzere", "mesaj": f"Sıradaki görev başlamak üzere: {nxt['id']} — {nxt.get('title', '')}", "eylem": ""}
    insan = B.pending_human(board)
    if insan:
        t = insan[0]
        return {"kod": "insan_onayi", "mesaj": f"İnsan onayı bekleniyor: {t['id']} — {t.get('title', '')}", "eylem": "Panel → Onaylar"}
    acik = [t for _, t in B.all_tasks(board) if t["status"] not in B.TERMINAL]
    bloke = [t for t in acik if t["status"] in (B.BLOCKED, B.FAILED)]
    if bloke:
        t = bloke[0]
        return {"kod": "bloke", "mesaj": f"Bloke/başarısız görev var: {t['id']} ({t['status']}) {(t.get('note') or '')[:120]}", "eylem": "Pano → görevi aç / telafi talebini kontrol et"}
    skip = [t for _, t in B.all_tasks(board) if t["status"] == B.SKIPPED and "telafi" in (t.get("note") or "") and "devredildi" in (t.get("note") or "")]
    if acik and skip:
        return {"kod": "telafi_bekliyor", "mesaj": f"{skip[0]['id']} telafi talebini bekliyor; çözülene kadar bağımlıları bekler.", "eylem": "Talepler sekmesinden talebi izle/onayla"}
    if acik:
        return {"kod": "bagimlilik", "mesaj": f"Hazır görev yok; {len(acik)} açık görev bağımlılık bekliyor.", "eylem": ""}
    return {"kod": "bitti", "mesaj": "Tüm görevler tamamlandı; yeni talep ya da faz bekleniyor.", "eylem": "Fazlar sekmesi: aktif fazı planla"}


def _ac(v):
    """İç içe JSON metinlerini açar (audit detayı ayrıca kaçışlanmış JSON taşıyabilir)."""
    if isinstance(v, str):
        t = v.strip()
        if t[:1] in "{[":
            try:
                return _ac(json.loads(t))
            except (ValueError, TypeError):
                return v
        return v
    if isinstance(v, dict):
        return {k: _ac(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_ac(x) for x in v]
    return v


def _kisalt(v, n=220):
    v = _ac(v)
    if isinstance(v, dict):
        s = " · ".join(f"{k}={x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)}" for k, x in v.items())
    else:
        s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[: n - 1] + "…"


def akis(limit: int = 200, gorev: str | None = None, olay: str | None = None, kaynak: str | None = None) -> list[dict]:
    """audit_log kayıtları (yeniden eskiye), insan okunur özetle."""
    kayitlar = B.audit_list(limit=max(limit * 3, 300) if gorev else limit, kaynak=kaynak, olay=olay)
    out = []
    for r in kayitlar:
        if gorev and (r.get("gorev_id") or "") != gorev:
            continue
        d = r.get("detay")
        try:
            d = json.loads(d) if d else None
        except (TypeError, ValueError):
            pass
        out.append({"id": r.get("id"), "zaman": r.get("zaman"), "kaynak": r.get("kaynak"), "olay": r.get("olay"),
                    "gorev": r.get("gorev_id"), "talep": r.get("talep_id"), "ozet": _kisalt(d) if d is not None else ""})
        if len(out) >= limit:
            break
    return out


def gorev_commit(gorev_id: str, kok: Path = ROOT) -> str | None:
    """Görevin otomatik commit'i ('studio: görev DONE — ID'); yoksa None."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", gorev_id or ""):
        return None
    try:
        r = subprocess.run(["git", "log", "--branches", "-n", "1", "--format=%H", "--fixed-strings", f"--grep=görev DONE — {gorev_id}"],
                           cwd=kok, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    h = (r.stdout or "").strip()
    return h or None


def degisiklik(gorev_id: str, kok: Path = ROOT) -> dict:
    """Görevin gerçek git farkı (kısaltılmış). Commit yoksa çalışma ağacındaki bekleyen fark."""
    h = gorev_commit(gorev_id, kok)
    try:
        if h:
            stat = subprocess.run(["git", "show", "--stat", "--format=%h %s%n%ci", h], cwd=kok, capture_output=True, text=True, timeout=20).stdout
            diff = subprocess.run(["git", "show", "--format=", "-U3", h], cwd=kok, capture_output=True, text=True, timeout=30).stdout
            kaynak = "commit"
        else:
            stat = subprocess.run(["git", "diff", "--stat", "HEAD"], cwd=kok, capture_output=True, text=True, timeout=20).stdout
            diff = subprocess.run(["git", "diff", "HEAD", "-U3"], cwd=kok, capture_output=True, text=True, timeout=30).stdout
            kaynak = "calisma_agaci"
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "mesaj": f"git okunamadı: {e}"}
    kesik = len(diff) > DIFF_LIMIT
    return {"ok": True, "kaynak": kaynak, "commit": h, "stat": stat.strip(), "diff": diff[:DIFF_LIMIT], "kesik": kesik}


def arac_olayi(arac: str, ozet: str, gorev_id: str | None, rol: str | None = None) -> None:
    """Ajanın araç çağrısını kalıcı etkinlik olarak kaydeder (audit_log)."""
    B.audit("ajan", "arac_cagrisi", gorev_id=gorev_id, detay={"arac": arac, "ozet": _kisalt(ozet, 300), "rol": rol})
