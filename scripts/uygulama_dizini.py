#!/usr/bin/env python3
"""Uygulama dizini sözleşmesi (issue #195): devops, web, test görevleri AYNI uygulama dizinini kullanır.

Sorun: devops görevi `workspace/src/frontend`, web görevi `workspace/src/web` varsaydı; yerel_ortam.sh "Frontend dizini yok" ile çıktı.
Çözüm: tek dizin sözleşmesi (config `planlama.dizinler.uygulama`, varsayılan `workspace/src/web`):
  - planlayıcı istemine eklenir,
  - üretilen panodaki ilgili görevlerin açıklamasına ve eş-anlamlı çıktı yollarına (frontend/app/client/ui) uygulanır,
  - yerel_ortam.sh üreten göreve "dizini sabit yazma, keşfet" kuralı eklenir.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VARSAYILAN = "workspace/src/web"
ESANLAMLI = ("frontend", "web", "app", "client", "ui")
MARKER = "Uygulama dizini sözleşmesi"
_ROL_RX = re.compile(r"devops|web|frontend|qa|uat|visitor|tester|auditor|e2e", re.I)


def dizin(cfg: dict | None) -> str:
    d = (((cfg or {}).get("planlama") or {}).get("dizinler") or {}).get("uygulama") or VARSAYILAN
    return str(d).strip().rstrip("/")


def sozlesme(d: str) -> str:
    return (f"{MARKER}: web uygulaması (package.json, nuxt.config.*) `{d}/` altındadır. Tüm görevler bu yolu kullanır; "
            f"farklı bir uygulama dizini (frontend, app, client...) uydurma. Mevcut yapıyı önce incele.")


def planlayici_notu(cfg: dict | None) -> str:
    return "\n\n" + sozlesme(dizin(cfg)) + " Çıktı yollarında ve görev açıklamalarında bu dizini aynen kullan."


def _esanlamli_duzelt(yol: str, d: str) -> str:
    m = re.match(r"^workspace/src/(%s)(/.*)?$" % "|".join(ESANLAMLI), yol)
    if not m:
        return yol
    return d + (m.group(2) or "/") if (m.group(2) or "/") else d


def uygula(board: dict, cfg: dict | None = None, kok: Path = ROOT) -> int:
    """Panodaki ilgili görevlere sözleşmeyi uygular; değiştirilen görev sayısını döndürür."""
    d = dizin(cfg)
    sayi = 0
    for s in board.get("sprints", []):
        for t in s.get("tasks", []):
            if t.get("role") == "human" or t.get("phase") == "design":
                continue
            ciktilar = t.get("outputs") or []
            yeni = [_esanlamli_duzelt(o, d) for o in ciktilar]
            yerel = any("yerel_ortam" in o for o in yeni)
            ilgili = bool(_ROL_RX.search(t.get("role", ""))) or any(o.startswith("workspace/src/") for o in yeni) or yerel
            if not ilgili:
                continue
            degisti = yeni != ciktilar
            t["outputs"] = yeni
            ac = t.get("description", "")
            if MARKER not in ac:
                ac = (ac.rstrip() + " " + sozlesme(d)).strip()
                degisti = True
            if yerel and "SABİT yazmaz" not in ac:
                ac += (" yerel_ortam.sh uygulama dizinini SABİT yazmaz: önce sözleşmedeki dizine bakar, yoksa nuxt.config.* / package.json bulunan dizini keşfeder; "
                       "bulunamazsa hata mesajında beklenen yolu ve bulunan adayları listeler.")
                degisti = True
            if yerel and (kok / "workspace/docs/teknoloji_stack_karari.md").is_file() and "teknoloji_stack_karari.md" not in ac:
                ac += " Girdi: workspace/docs/teknoloji_stack_karari.md"
                degisti = True
            t["description"] = ac
            sayi += degisti
    return sayi
