#!/usr/bin/env python3
"""Kaynak proje deterministik tarayıcısı.

Var olan bir kod tabanını (ör. Angular uygulaması) analiz edip studio
rollerinin girdi olarak kullanacağı tarama dokümanları üretir. LLM
kullanmaz — yalnızca dosya sistemi ve regex ile çalışır; çıktı yol
tabanlı ve doğrulanabilirdir.

Üretilen parçalar (her biri read_input'un 100 KB kesme sınırının altında
tutulur):

  <prefix>taramasi.md        — teknoloji yığını, enum'lar, guard'lar,
                               erişim servisleri, TÜM routing dosyaları
  <prefix>yetki_taramasi.md  — ngxPermissionsOnly/Except, rol/feature
                               kontrolleri, koşullu görünürlük
  <prefix>envanter.md        — modül/dizin/component/servis envanteri

Motor, `workspace/docs/` altında `<prefix>*.md` desenli dosyaları design
aşamasındaki rollerin girdilerine OTOMATİK ekler (bkz. collect_inputs).

Kullanım:
  python3 scripts/kaynak_tarama.py --kaynak /path/to/kaynak-proje
  python3 scripts/kaynak_tarama.py --kaynak ../api --docs workspace/docs \
      --prefix kaynak_proje_ --max-part-kb 90
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROUTE_GLOBS = ("*-routing.module.ts", "*.routing.module.ts",
               "app.routes.ts", "routes.ts")


def read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"[okunamadı: {e}]"


def code_block(p: Path, base: Path) -> str:
    try:
        rel = p.relative_to(base)
    except ValueError:
        rel = p
    return f"### `{rel}`\n```ts\n{read_text(p)}\n```\n"


def kapasite_yaz(parts: list[str], cap: int) -> str:
    """Parçayı bayt sınırına göre kırpar; kırpıldıysa not ekler."""
    metin = "\n".join(parts) + "\n"
    veri = metin.encode("utf-8")
    if len(veri) <= cap:
        return metin
    kesik = veri[:cap].decode("utf-8", errors="ignore")
    return (kesik.rsplit("\n", 1)[0]
            + f"\n\n> **[KIRPILDI]** Bu parça {cap // 1024} KB sınırına ulaştı; "
              "kalan satırlar atlandı. Tam envanter için kaynak depoyu doğrudan "
              "inceleyin.\n")


def tablo_satirlari(kok: Path, glob_pat: str, desen: str,
                    uzunluk: int = 160, spec_atla: bool = True) -> list[tuple[str, int, str]]:
    """glob ile eşleşen dosyalarda desen arar; (dosya, satır, kod) döner."""
    rx = re.compile(desen)
    rows: list[tuple[str, int, str]] = []
    for p in sorted(kok.rglob(glob_pat)):
        if spec_atla and ".spec." in p.name:
            continue
        for i, line in enumerate(read_text(p).splitlines(), 1):
            for m in rx.finditer(line):
                rows.append((str(p.relative_to(kok)), i, (m.group(0) or line.strip())[:uzunluk]))
    return rows


def md_tablo(rows: list[tuple[str, int, str]]) -> list[str]:
    out = ["| dosya | satır | kod |", "|---|---|---|"]
    out += [f"| `{f}` | {ln} | `{c}` |" for f, ln, c in rows]
    out.append(f"\n_toplam {len(rows)} eşleşme_")
    return out


def header(prefix: str, kaynak: Path) -> str:
    return (f"> Bu doküman `{kaynak}` kaynak projesinden OTOMATİK ve "
            "DETERMİNİSTİK üretildi (LLM yorumu yoktur). Otorite kaynaktır: "
            "üretilen analiz dokümanlarıyla çelişirse BU tarama esas alınır.\n"
            f"> Eş parçalar: `{prefix}taramasi.md`, `{prefix}yetki_taramasi.md`, "
            f"`{prefix}envanter.md`\n"
            "> Not: kimlik bilgisi / secret içeren dosyalar bu taramaya "
            "kopyalanmaz; yalnızca dosya yoluna referans verilir.\n")


def scan(kaynak: Path, docs: Path, prefix: str, cap_kb: int) -> list[Path]:
    app = kaynak / "src/app"
    kok = app if app.is_dir() else kaynak / "src"
    if not kok.is_dir():
        sys.exit(f"[HATA] Kaynak proje yapısı tanınamadı: {kaynak} "
                 "(src/app veya src bekleniyor)")
    cap = cap_kb * 1024
    docs.mkdir(parents=True, exist_ok=True)

    # ---------------- parça 1: stack + enum + guard + route'lar ----------
    p1 = ["# Kaynak Proje Taraması (1/3) — Route'lar, Guard'lar, Enum'lar\n",
          header(prefix, kaynak)]
    pkg_path = kaynak / "package.json"
    if pkg_path.exists():
        try:
            pkg = json.loads(read_text(pkg_path))
            p1.append("## 1. Teknoloji Yığını (package.json)\n\n**dependencies:**")
            for k, v in sorted(pkg.get("dependencies", {}).items()):
                p1.append(f"- `{k}`: `{v}`")
            p1.append("\n**devDependencies:**")
            for k, v in sorted(pkg.get("devDependencies", {}).items()):
                p1.append(f"- `{k}`: `{v}`")
        except json.JSONDecodeError:
            p1.append("## 1. Teknoloji Yığını\n\n_package.json çözümlenemedi._")

    p1.append("\n## 2. Rol ve Menü Enum'ları\n")
    enums = sorted(kok.rglob("*enum*.ts"))
    for p in enums:
        if any(s in p.name for s in ("role", "menu", "permission", "feature")):
            p1.append(code_block(p, kaynak))
    if not enums:
        p1.append("_enum dosyası bulunamadı._")

    p1.append("\n## 3. Guard / Security Dosyaları (tam kaynak)\n")
    guards = [p for p in sorted(kok.rglob("*.ts"))
              if ".spec." not in p.name and
              ("guard" in p.name or "security" in p.parent.name)]
    for p in guards:
        p1.append(code_block(p, kaynak))
    if not guards:
        p1.append("_guard dosyası bulunamadı._")

    p1.append("\n## 4. Erişim Servisleri (access/permission/auth içerenler)\n")
    srvs = [p for p in sorted(kok.rglob("*.service.ts"))
            if ".spec." not in p.name and
            re.search(r"access|permission|auth|feature", p.name, re.I)]
    for p in srvs:
        p1.append(code_block(p, kaynak))
    if not srvs:
        p1.append("_eşleşen servis yok._")

    p1.append("\n## 5. Routing Dosyaları (tam kaynak)\n")
    seen: set[Path] = set()
    for pat in ROUTE_GLOBS:
        for p in sorted(kok.rglob(pat)):
            if p in seen or ".spec." in p.name:
                continue
            seen.add(p)
            p1.append(code_block(p, kaynak))
    if not seen:
        p1.append("_routing dosyası bulunamadı._")

    p1.append("""
## 6. Route Verisi Yetki Anahtarları Sözlüğü

| anahtar | anlam |
|---|---|
| `requiredMenu` | menü guard'ı: kullanıcının menüsünde görünür olmalı |
| `permissions.only` | yalnız listelenen roller girebilir |
| `permissions.except` | listelenen roller HARİÇ herkes girebilir |
| `redirectTo` / `forbiddenRedirect` | yetkisizlikte yönlenecek route |
| `canActivate` zinciri | sırayla çalışır; biri false dönerse erişim yok |
| `canLoad` / `canMatch` | lazy modül yüklenmeden önce kontrol |
""")

    # ---------------- parça 2: yetki / feature kullanımları --------------
    p2 = ["# Kaynak Proje Taraması (2/3) — Yetki ve Feature Kullanımları\n",
          header(prefix, kaynak)]
    p2.append("## 1. Element-Seviyesi Yetki Direktifleri "
              "(`ngxPermissionsOnly` / `ngxPermissionsExcept` / `*permissions`)\n")
    rows = []
    for f in sorted(kok.rglob("*.html")):
        for i, line in enumerate(read_text(f).splitlines(), 1):
            for m in re.finditer(
                    r"\w*[Pp]ermissions\w*\s*=\s*(\"[^\"]*\"|'[^']*'|\[[^\]]*\])",
                    line):
                rows.append((str(f.relative_to(kok)), i, m.group(0)[:160]))
    p2 += md_tablo(rows)

    p2.append("\n## 2. `.ts` İçinde Rol / Permission Kontrolleri\n")
    rows = tablo_satirlari(
        kok, "*.ts",
        r"hasPermission|PermissionsService|ROLE_[A-Z_]+|\.roles\b|roleId\b")
    p2 += md_tablo(rows)

    p2.append("\n## 3. Feature Flag / Erişim Servisi Referansları\n")
    rows = tablo_satirlari(
        kok, "*.ts",
        r"isFeatureEnabled|featureEnabled|\.features\b|FeatureToggle|"
        r"AccessService|setFeatures|feature_map|toggle")
    p2 += md_tablo(rows)

    p2.append("\n## 4. Template Koşullu Görünürlük (`*ngIf`/`[hidden]` içinde "
              "permission/rol/feature/admin/access)\n")
    rows = tablo_satirlari(
        kok, "*.html",
        r"(\*ngIf|\[hidden\])\s*=\s*\"[^\"]*"
        r"(permission|role|feature|admin|superuser|access)[^\"]*\"")
    p2 += [f"- `{f}`:{ln} → `{c}`" for f, ln, c in rows]
    p2.append(f"\n_toplam {len(rows)} satır_")

    # ---------------- parça 3: envanter -----------------------------------
    p3 = ["# Kaynak Proje Taraması (3/3) — Modül ve Dosya Envanteri\n",
          header(prefix, kaynak)]
    mod_kok = kok / "modules"
    p3.append(f"## 1. `{mod_kok.relative_to(kaynak) if mod_kok.is_dir() else 'modules'}` Modülleri\n")
    if mod_kok.is_dir():
        for d in sorted(x for x in mod_kok.iterdir() if x.is_dir()):
            comps = list(d.rglob("*.component.ts"))
            srvs2 = list(d.rglob("*.service.ts"))
            htmls = list(d.rglob("*.component.html"))
            p3.append(f"- **`{d.name}`**: {len(comps)} component, "
                      f"{len(srvs2)} service, {len(htmls)} template")
    else:
        p3.append("_modules dizini yok._")
    rt = kok / "routes"
    p3.append(f"\n## 2. `{rt.relative_to(kaynak) if rt.is_dir() else 'routes'}` Ekran Dizinleri\n")
    if rt.is_dir():
        for d in sorted(rt.iterdir()):
            if d.is_dir():
                p3.append(f"- **`{d.name}`**: "
                          f"{len(list(d.rglob('*.component.ts')))} component")
    p3.append("\n## 3. Servis Dosyaları (`*.service.ts`)\n")
    for p in sorted(kok.rglob("*.service.ts")):
        if ".spec." not in p.name:
            p3.append(f"- `{p.relative_to(kaynak)}`")
    p3.append("\n## 4. Tüm Component Dosyaları (`*.component.ts`)\n")
    for p in sorted(kok.rglob("*.component.ts")):
        p3.append(f"- `{p.relative_to(kaynak)}`")

    outputs = []
    for name, parts in ((f"{prefix}taramasi.md", p1),
                        (f"{prefix}yetki_taramasi.md", p2),
                        (f"{prefix}envanter.md", p3)):
        out = docs / name
        out.write_text(kapasite_yaz(parts, cap), encoding="utf-8")
        outputs.append(out)
    return outputs


def main() -> None:
    ap = argparse.ArgumentParser(description="Kaynak proje deterministik tarayıcısı")
    ap.add_argument("--kaynak", required=True,
                    help="taranacak kaynak proje kökü (src/app veya src içermeli)")
    ap.add_argument("--docs", default="workspace/docs",
                    help="çıktı dizini (varsayılan: workspace/docs)")
    ap.add_argument("--prefix", default="kaynak_proje_",
                    help="dosya adı öneki (varsayılan: kaynak_proje_)")
    ap.add_argument("--max-part-kb", type=int, default=90,
                    help="parça başına bayt sınırı KB (varsayılan: 90, "
                         "read_input 100 KB üstünü kırpar)")
    args = ap.parse_args()

    kaynak = Path(args.kaynak).expanduser().resolve()
    if not kaynak.is_dir():
        sys.exit(f"[HATA] Kaynak dizin yok: {kaynak}")
    outs = scan(kaynak, Path(args.docs), args.prefix, args.max_part_kb)
    # Ajanların referans projeyi okuyabilmesi için dizini kaydet (claude --add-dir).
    try:
        kayit = Path(args.docs).resolve().parent / ".kaynak_projeler.json"
        try:
            d = json.loads(kayit.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        dizinler = list(d.get("dizinler", []))
        if str(kaynak) not in dizinler:
            dizinler.append(str(kaynak))
        kayit.write_text(json.dumps({"dizinler": dizinler}, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    except OSError:
        pass
    for o in outs:
        print(f"[✓] {o} ({o.stat().st_size:,} bayt)")
    print("\n[i] Bu dosyalar design aşaması rollerinin girdilerine otomatik "
          "eklenir. Mevcut çıktıları yeniden ürettirmek için state'i sıfırlayıp "
          "motoru --replan ile başlatın.")


if __name__ == "__main__":
    main()
