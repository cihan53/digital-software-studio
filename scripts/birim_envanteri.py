#!/usr/bin/env python3
"""Keşif ham verisinden planlayıcı girdileri üretir (issue #171): _birimler.md, _modul/<modül>.md, _api/<modül>.json.

Girdi : <analysis.output_dir>/_ham/*.json, _ham/_durum.json, _roller.json (opsiyonel), _api_semalari.json (opsiyonel)
Çıktı : _birimler.md (rota başına özet), _modul/<m>.md (modül özeti + erişim kuralları), _api/<m>.json (yalnız modüle özgü API şema dilimi)
Kişisel veri içermez: yalnız sayılar, rota, rol/menü adları ve şema (alan adı/tip).
  python3 scripts/birim_envanteri.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as C  # noqa: E402


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower() or "kok"


def modul_adi(rota: str) -> str:
    return (rota.strip("/").split("/")[0] or "kok").replace(":", "")


def yukle(out: Path) -> list[dict]:
    """[{rota, modul, durum, widget, kolon, grafik, modal, api, erisim, not}] — rota sırasıyla."""
    durum = json.loads((out / "_ham" / "_durum.json").read_text(encoding="utf-8"))["bitti"]
    roller = json.loads((out / "_roller.json").read_text(encoding="utf-8")) if (out / "_roller.json").exists() else {}
    rows = []
    for rota, d in sorted(durum.items()):
        row = {"rota": rota, "modul": modul_adi(rota), "durum": d, "widget": "-", "kolon": "-", "grafik": "-", "modal": "-", "api": "-",
               "erisim": "-", "not": "ÖRNEKSİZ: 2. tur keşif görevi" if d != "tamam" else ""}
        f = out / "_ham" / f"{slug(rota)}.json"
        if d == "tamam" and f.exists():
            r = json.loads(f.read_text(encoding="utf-8"))
            ac = sum(1 for m in r.get("modals", []) if m.get("acildi"))
            rl = roller.get(rota, {})
            erisim = ", ".join(filter(None, [("rol:" + "+".join(x.replace("ROLE_", "") for x in rl["only"])) if rl.get("only") else "",
                                              ("menü:" + rl["menu"]) if rl.get("menu") else ""])) or "yalnız oturum"
            row.update(widget=len(r.get("wid", [])), kolon=len(r.get("th", [])), grafik=r.get("cv", 0), modal=f"{ac}/{len(r.get('modals', []))}",
                       api=len(r.get("api", [])), erisim=erisim,
                       **{"not": ("yönlendirir→" + r["yonlendirme"]) if r.get("yonlendirme") else ("tahmin-kimlik" if r.get("tahmin") else "")})
        rows.append(row)
    return rows


def ortak_uclar(out: Path, toplam: int, oran: float = 0.4) -> list[str]:
    p = out / "_api_semalari.json"
    if not p.exists():
        return []
    s = json.loads(p.read_text(encoding="utf-8"))
    return sorted(k for k, v in s.items() if len(v.get("birimler", [])) >= oran * max(1, toplam))


def yaz(out: Path | None = None) -> dict:
    cfg = C.load_config() or {"analysis": C.DEFAULTS["analysis"]}
    out = out or C.ROOT / cfg["analysis"]["output_dir"]
    rows = yukle(out)
    roller = json.loads((out / "_roller.json").read_text(encoding="utf-8")) if (out / "_roller.json").exists() else {}
    sema = json.loads((out / "_api_semalari.json").read_text(encoding="utf-8")) if (out / "_api_semalari.json").exists() else {}
    ortak = ortak_uclar(out, len(rows))
    L = ["# Birim Envanteri (planlayıcı girdisi)", "", f"{len(rows)} birim. Her satır bir ekrandır; ayrıntı: `ekranlar/<modül>/<rota>.md`.", "",
         "| Modül | Rota | Widget | Tablo kolon | Grafik | Modal | API | Erişim | Not |", "|---|---|---|---|---|---|---|---|---|"]
    L += [f"| {r['modul']} | {r['rota']} | {r['widget']} | {r['kolon']} | {r['grafik']} | {r['modal']} | {r['api']} | {r['erisim']} | {r['not']} |" for r in rows]
    (out / "_birimler.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    moduller: dict[str, list[dict]] = {}
    for r in rows:
        moduller.setdefault(r["modul"], []).append(r)
    (out / "_modul").mkdir(exist_ok=True)
    (out / "_api").mkdir(exist_ok=True)
    for m, us in moduller.items():
        uclar = sorted(k for k, v in sema.items() if set(v.get("birimler", [])) & {u["rota"] for u in us} and k not in ortak)
        ml = [f"# Modül özeti: {m}", "", "Kaynak: gezgin keşfi, kod kaynaklı erişim kuralları (`_roller.json`), gözlenen API şemaları. `bilinmiyor` = gözlenmedi, tahmin edilmez.", "",
              "| Rota | Widget | Kolon | Grafik | Modal | API | Erişim (kod) |", "|---|---|---|---|---|---|---|"]
        for u in us:
            rl = roller.get(u["rota"], {})
            e = "; ".join(filter(None, [("guard: " + ", ".join(rl["guards"])) if rl.get("guards") else "", ("roller: " + ", ".join(rl["only"])) if rl.get("only") else "",
                                        ("menü: " + rl["menu"]) if rl.get("menu") else "", ("yönlendirir→" + rl["redirect_to"]) if rl.get("redirect_to") else ""])) or "yalnız oturum"
            ml.append(f"| `{u['rota']}` | {u['widget']} | {u['kolon']} | {u['grafik']} | {u['modal']} | {u['api']} | {e} |")
        ml += ["", "## Bu modüle özgü API uçları (kabuk uçları hariç)", ""] + ([f"- `{k}`" for k in uclar] or ["- (gözlenmedi)"])
        (out / "_modul" / f"{m}.md").write_text("\n".join(ml) + "\n", encoding="utf-8")
        (out / "_api" / f"{m}.json").write_text(json.dumps({k: {"sema": sema[k].get("sema"), "durum": sema[k].get("durum")} for k in uclar if k in sema},
                                                           ensure_ascii=False, indent=1), encoding="utf-8")
    return {"birim": len(rows), "modul": len(moduller), "ortak_uc": len(ortak)}


if __name__ == "__main__":
    print(yaz())
