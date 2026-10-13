#!/usr/bin/env python3
"""Referans sistem (issue #277): taşıma/dönüştürme projelerinde ESKİ sistem analiz, plan ve tasarım kararlarının doğrulama kaynağıdır.

İKİ AYRI KAVRAM:
  - yeni sistemin canlı ortamı (live.ports, yerel_ortam.sh): UAT/ziyaretçi testleri için; yoksa o görevler beklemez ya da geçilir.
  - REFERANS sistem (burası): eski sistemin kaynak kodu (clone) ve/veya canlı adresi. Analiz/plan/tasarım görevleri yalnız kaynak koddan karar
    vermesin diye referans erişilemezse görev ATLANMAZ, bekletilir ve panelde/logda sebep gösterilir.
Tanım (hepsi isteğe bağlı; yoksa source.path ve source.live_url kullanılır):
  workspace/studio.config.json → "referans": {"kaynak": "/yol/clone", "url": "https://...", "baslat": "komut (clone'u ayağa kaldırır)", "tur": "url|clone"}
"""
from __future__ import annotations

import time
import urllib.error
import urllib.request
from pathlib import Path

_ONBELLEK: dict = {}
TTL = 30


def tanim(cfg: dict | None) -> dict:
    src = (cfg or {}).get("source") or {}
    ref = (cfg or {}).get("referans") or {}
    return {"kaynak": ref.get("kaynak") or src.get("path") or "", "url": ref.get("url") or src.get("live_url") or "",
            "baslat": ref.get("baslat") or "", "tur": ref.get("tur") or ("clone" if ref.get("baslat") else "url")}


def tanimli(cfg: dict | None) -> bool:
    t = tanim(cfg)
    return bool(t["kaynak"] or t["url"])


def _url_erisilebilir(url: str, sn: float = 6.0) -> tuple[bool, str]:
    try:
        urllib.request.urlopen(urllib.request.Request(url, method="GET", headers={"User-Agent": "studio-referans/1"}), timeout=sn)
        return True, ""
    except urllib.error.HTTPError as e:
        return (e.code < 500), f"HTTP {e.code}"          # 401/403/302 = ayakta (giriş istiyor); 5xx = sorunlu
    except Exception as e:                                   # noqa: BLE001
        return False, f"{type(e).__name__}: {str(e)[:80]}"


def durum(cfg: dict | None, onbellek: bool = True) -> dict:
    t = tanim(cfg)
    anahtar = (t["kaynak"], t["url"])
    simdi = time.time()
    if onbellek and anahtar in _ONBELLEK and simdi - _ONBELLEK[anahtar][0] < TTL:
        return _ONBELLEK[anahtar][1]
    sorunlar = []
    kaynak_ok = True
    if t["kaynak"]:
        kaynak_ok = Path(t["kaynak"]).exists()
        if not kaynak_ok:
            sorunlar.append(f"referans kaynak kodu yok: {t['kaynak']}")
    url_ok = True
    if t["url"]:
        url_ok, neden = _url_erisilebilir(t["url"])
        if not url_ok:
            sorunlar.append(f"referans sistem erişilemiyor: {t['url']} ({neden})")
    sonuc = {"hazir": kaynak_ok and url_ok, "kaynak_ok": kaynak_ok, "url_ok": url_ok, "sorunlar": sorunlar, **t}
    _ONBELLEK[anahtar] = (simdi, sonuc)
    return sonuc


_BEKLEME_BAS: dict = {}


def bekleme_dk(cfg: dict | None) -> int:
    """Referans erişilemezken görev en fazla bu kadar bekletilir (0 = sınırsız); sonra kaynak koda dayanarak sürer."""
    return int(((cfg or {}).get("referans") or {}).get("bekleme_dk", 30))


def bekleme_baslangici(cfg: dict | None) -> float:
    return _BEKLEME_BAS.setdefault("t", time.time())


def bekleme_asildi(cfg: dict | None) -> bool:
    """Erişilemez durum başladığından beri bekleme süresi doldu mu? Erişilince sayaç sıfırlanır (hazir_mi içinde)."""
    dk = bekleme_dk(cfg)
    bas = _BEKLEME_BAS.setdefault("t", time.time())
    return dk > 0 and time.time() - bas >= dk * 60


def hazir_mi(cfg: dict | None) -> tuple[bool, str]:
    if not tanimli(cfg):
        return True, ""
    d = durum(cfg)
    if d["hazir"]:
        _BEKLEME_BAS.clear()
    return d["hazir"], "; ".join(d["sorunlar"])
