#!/usr/bin/env python3
"""Kaynak koddan rota başına erişim bilgisi çıkarır (issue #134) — deterministik, LLM'siz.

Adaptör: Angular router (source.kind 'angular-*'). Lazy-load zincirini çözer; her rota için
canActivate guard'ları, `data.permissions.only/except/redirectTo`, `requiredMenu`,
`forbiddenRedirect`, `redirectTo` ve true/false bayrakları (requires*/allow*/is*) çıkarır;
üst rotalardan miras alır (guard'lar birikir, rol/menü en yakın tanım geçerlidir).

Çıktı: <analysis.output_dir>/_roller.json
  { "/rota/:id": {"guards":[..], "only":[..], "except":[..], "perm_redirect":"..", "menu":"..",
                  "forbidden":"..", "redirect_to":"..", "bayraklar":{..}, "dosya":"rel/yol.ts"} }
Kullanım: python3 scripts/kesif_roller.py [--kaynak yol]   (varsayılan: studio.config.json → source.path)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import studio_config as C  # noqa: E402

TOK = re.compile(r"\{|\}|\[|\]|path:\s*'([^']*)'|loadChildren:[^;]*?import\('([^']+)'\)", re.S)


def routing_for(modfile: str) -> str | None:
    base = modfile[:-len(".module.ts")] if modfile.endswith(".module.ts") else modfile
    for c in (base + "-routing.module.ts", base + ".routing.module.ts"):
        if os.path.exists(c):
            return c
    return None


def _match(src: str, i: int, op: str, cl: str) -> int:
    """src[i]==op iken eşleşen kapanış indeksi (yoksa len)."""
    d = 0
    for j in range(i, len(src)):
        if src[j] == op:
            d += 1
        elif src[j] == cl:
            d -= 1
            if d == 0:
                return j
    return len(src)


def own_text(src: str, a: int, b: int) -> str:
    """Rota nesnesinin kendi metni: children: [...] bloğu çıkarılır."""
    body = src[a:b + 1]
    m = re.search(r"children\s*:\s*\[", body)
    if m:
        s = m.end() - 1
        e = _match(body, s, "[", "]")
        body = body[:m.start()] + body[e + 1:]
    return body


def parse_own(txt: str) -> dict:
    o: dict = {}
    m = re.search(r"canActivate\s*:\s*\[([^\]]*)\]", txt)
    o["guards"] = [g.strip() for g in m.group(1).split(",") if g.strip()] if m else []
    pm = re.search(r"permissions\s*:\s*\{", txt)
    if pm:
        blk = txt[pm.end() - 1:_match(txt, pm.end() - 1, "{", "}") + 1]
        for k in ("only", "except"):
            km = re.search(rf"{k}\s*:\s*\[([^\]]*)\]", blk)
            if km:
                o[k] = [re.sub(r".*\.", "", r.strip()) for r in km.group(1).split(",") if r.strip()]
        rm = re.search(r"redirectTo\s*:\s*'([^']*)'", blk)
        if rm:
            o["perm_redirect"] = rm.group(1)
    mm = re.search(r"requiredMenu\s*:\s*[\w.]*?(\w+)\s*[,}\n]", txt)
    if mm:
        o["menu"] = mm.group(1)
    fm = re.search(r"forbiddenRedirect\s*:\s*'([^']*)'", txt)
    if fm:
        o["forbidden"] = fm.group(1)
    rd = re.search(r"(?<![\w.])redirectTo\s*:\s*'([^']*)'", re.sub(r"permissions\s*:\s*\{.*?\}", "", txt, flags=re.S))
    if rd:
        o["redirect_to"] = rd.group(1)
    fl = {k: v for k, v in re.findall(r"\b((?:requires|allow|is)\w+)\s*:\s*(true|false)\b", txt)}
    if fl:
        o["bayraklar"] = fl
    return o


def collect(file: str, prefix: str, parent: dict, out: dict, root: str, seen: set) -> None:
    src = open(file, encoding="utf-8").read()
    # Rota nesneleri: path: token'ının içinde bulunduğu en yakın { ... } bloğu
    stack: list[int] = []
    objs: list[tuple[int, int, str, str | None]] = []   # (start,end,path,loadChildren)
    pending: dict[int, list] = {}
    for m in TOK.finditer(src):
        t = m.group(0)
        if t == "{":
            stack.append(m.start())
        elif t == "}":
            if stack:
                stack.pop()
        elif t.startswith("path"):
            if stack:
                pending.setdefault(stack[-1], []).append(m.group(1))
        elif t.startswith("loadChildren") and stack:
            pending.setdefault(stack[-1], []).append(("LC", m.group(2)))
    nodes = []
    for start, items in pending.items():
        path = next((i for i in items if isinstance(i, str)), None)
        lc = next((i[1] for i in items if isinstance(i, tuple)), None)
        if path is None:
            continue
        end = _match(src, start, "{", "}")
        nodes.append((start, end, path, lc))
    nodes.sort()
    # üst-alt ilişkisi: kapsayan en küçük rota nesnesi
    resolved: dict[int, dict] = {}
    for start, end, path, lc in nodes:
        par = None
        for ps, pe, *_ in nodes:
            if ps < start and pe >= end and (par is None or ps > par[0]):
                par = (ps, pe)
        pn = resolved[par[0]] if par else {"full": prefix, "eff": parent}
        full = "/".join(x for x in [pn["full"].strip("/"), path.strip("/")] if x)
        own = parse_own(own_text(src, start, end))
        eff = {
            "guards": list(dict.fromkeys(pn["eff"].get("guards", []) + own["guards"])),
            "only": own.get("only", pn["eff"].get("only")),
            "except": own.get("except", pn["eff"].get("except")),
            "perm_redirect": own.get("perm_redirect", pn["eff"].get("perm_redirect")),
            "menu": own.get("menu", pn["eff"].get("menu")),
            "forbidden": own.get("forbidden", pn["eff"].get("forbidden")),
            "bayraklar": {**pn["eff"].get("bayraklar", {}), **own.get("bayraklar", {})},
        }
        if own.get("redirect_to") is not None:
            eff["redirect_to"] = own["redirect_to"]
        resolved[start] = {"full": full, "eff": eff}
        key = "/" + full
        rec = {k: v for k, v in eff.items() if v not in (None, [], {})}
        rec["dosya"] = os.path.relpath(file, root)
        if key not in out or (rec.get("guards") and not out[key].get("guards")):
            out[key] = rec
        if lc:
            mf = os.path.normpath(os.path.join(os.path.dirname(file), lc)) + ".ts"
            r = routing_for(mf)
            if r and (r, full) not in seen:
                seen.add((r, full))
                collect(r, full, eff, out, root, seen)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--kaynak", default=None)
    ap.add_argument("--cikti", default=None)
    a = ap.parse_args(argv)
    cfg = C.load_config()
    kaynak = a.kaynak or (cfg or {}).get("source", {}).get("path")
    kind = (cfg or {}).get("source", {}).get("kind", "")
    if not kaynak:
        print("[HATA] kaynak yolu yok (--kaynak veya source.path)", file=sys.stderr)
        return 1
    if kind and not kind.startswith("angular"):
        print(f"[HATA] adaptör yok: source.kind={kind} (desteklenen: angular-*)", file=sys.stderr)
        return 1
    app = Path(kaynak) / "src" / "app"
    entry = next((p for p in (app / "routes" / "routes-routing.module.ts", app / "app-routing.module.ts") if p.exists()), None)
    if not entry:
        print(f"[HATA] kök routing dosyası bulunamadı: {app}", file=sys.stderr)
        return 1
    out: dict = {}
    collect(str(entry), "", {}, out, str(app), set())
    out = {k: v for k, v in sorted(out.items()) if k != "/**" and "**" not in k}
    yol = Path(a.cikti) if a.cikti else C.ROOT / ((cfg or C.DEFAULTS)["analysis"]["output_dir"]) / "_roller.json"
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    kor = sum(1 for v in out.values() if v.get("only") or v.get("menu"))
    print(f"{len(out)} rota, {kor} tanesi rol/menü kısıtlı → {yol}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
