#!/usr/bin/env python3
"""Kapsam açığı denetimi (issue #271): pano tamamen kapalıyken sistem eksik kapsamı kendisi bulur, yeni faz açar.

Akış (insan müdahalesi yok; sistem kararı audit_log'a düşer, §10.5):
  1. `tetikle`  → pano boşta (hepsi DONE/SKIPPED), bekleyen faz planı yok, son denetim "tamam" demedi:
                  deterministik kanıt dosyası yazılır (kaynak envanter dosyaları, üretilen UI kaynak dosyaları,
                  SKIPPED görevler) ve "Kapsam denetimi" sprinti (T1: sprint_planner) eklenir.
  2. `kontrol`  → T1 bitti → JSON doğrulanır (geçersizse hata listesiyle yeniden açılır);
                  eksik varsa fazlar açılır (aktif faz TAMAMLANDI, ilk yeni faz AKTIF) ve mevcut faz planlama
                  akışı (faz_planla.gerekli) yeni fazı planlar. Eksik yoksa denetim "tamam" kapanır, döngü durur.
Uydurma yok: rapordaki her eksik birim, envanter dosyalarının metninde geçmelidir.
Kapatma: STUDIO_KAPSAM_DENETIMI=0 ya da studio.config.json → kapsam_denetimi.acik=false. Üst sınır: kapsam_denetimi.en_fazla (varsayılan 5).

Dosyalar: workspace/docs/kapsam_denetimleri/K<n>.json (rapor), K<n>.uygulandi (sonuç), _sema.md, kapsam_kanit.md
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import studio_board as B  # noqa: E402

DIZIN = "workspace/docs/kapsam_denetimleri"
KANIT = f"{DIZIN}/kapsam_kanit.md"
EN_FAZLA_FAZ = 3
UI_UZANTILARI = {".vue", ".tsx", ".jsx", ".svelte", ".html", ".dart", ".kt", ".swift", ".xml", ".storyboard"}
ATLA_DIZIN = {"node_modules", ".git", ".nuxt", ".output", "dist", "build", ".next", "__pycache__", ".trace", ".scratch"}
ENVANTER_ADAYLARI = ("proje_kapsami.md", "workspace/docs/proje_kapsami.md", "workspace/docs/ekran_envanteri.md", "workspace/docs/backlog.md",
                     "workspace/docs/kabul_kriterleri.md", "workspace/docs/rol_gorunurluk_matrisi.md", "workspace/docs/envanter/_indeks.md")


def acik_mi(cfg: dict | None) -> bool:
    if os.environ.get("STUDIO_KAPSAM_DENETIMI") == "0":
        return False
    return bool(((cfg or {}).get("kapsam_denetimi") or {}).get("acik", True))


def en_fazla(cfg: dict | None) -> int:
    return int(((cfg or {}).get("kapsam_denetimi") or {}).get("en_fazla", 5))


def envanter_dosyalari(kok: Path = ROOT, cfg: dict | None = None) -> list[str]:
    """Kaynak kapsamı anlatan, var olan dosyalar (kök-göreli). Keşif çıktısı ve '*envanter*' adlı dokümanlar dahil."""
    bulunan = [g for g in ENVANTER_ADAYLARI if (kok / g).exists()]
    docs = kok / "workspace" / "docs"
    if docs.exists():
        for p in sorted(docs.glob("*envanter*")):
            r = p.relative_to(kok).as_posix()
            if r not in bulunan and p.is_file():
                bulunan.append(r)
    cikti = ((cfg or {}).get("analysis") or {}).get("output_dir")
    if cikti:
        b = kok / cikti / "_birimler.md"
        if b.exists():
            bulunan.append(b.relative_to(kok).as_posix())
    return bulunan


def uretilen_ui_dosyalari(kok: Path = ROOT, sinir: int = 600) -> list[str]:
    src = kok / "workspace" / "src"
    sonuc: list[str] = []
    if not src.exists():
        return sonuc
    for yol, dizinler, dosyalar in os.walk(src):
        dizinler[:] = sorted(d for d in dizinler if d not in ATLA_DIZIN)
        for f in sorted(dosyalar):
            if Path(f).suffix in UI_UZANTILARI:
                sonuc.append((Path(yol) / f).relative_to(kok).as_posix())
                if len(sonuc) >= sinir:
                    return sonuc
    return sonuc


def kanit_yaz(board: dict, kok: Path = ROOT, cfg: dict | None = None) -> str:
    """Deterministik kanıt dosyası (LLM'siz): ajan araç kullanmadan kapsamı karşılaştırabilsin."""
    atlanan = [(t["id"], t.get("title", ""), (t.get("note") or "")[:100]) for _, t in B.all_tasks(board) if t["status"] == B.SKIPPED]
    ui = uretilen_ui_dosyalari(kok)
    L = ["# Kapsam kanıtı (motor üretti, yorum yok)", "", "## Kaynak kapsamı anlatan dosyalar", ""]
    L += [f"- `{e}`" for e in envanter_dosyalari(kok, cfg)] or ["- (yok)"]
    L += ["", f"## Üretilen arayüz kaynak dosyaları ({len(ui)}{'+' if len(ui) >= 600 else ''})", ""]
    L += [f"- `{u}`" for u in ui] or ["- (yok)"]
    L += ["", f"## Atlanan (SKIPPED) görevler ({len(atlanan)})", ""]
    L += [f"- {i} — {a} ({n})" for i, a, n in atlanan] or ["- (yok)"]
    p = kok / KANIT
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(L) + "\n", encoding="utf-8")
    return KANIT


def sema_metni() -> str:
    return f"""# Kapsam denetimi çıktı şeması

Yalnızca GEÇERLİ JSON üret (kod çiti ve açıklama YOK):
{{"tamam": false, "ozet": "tek cümle durum",
  "eksikler": [{{"birim": "kaynak envanterde AYNEN geçen ekran/rota/modül adı", "kanit": "üretilen kodda neden yok/eksik (dosya veya SKIPPED görev)"}}],
  "fazlar": [{{"ad": "kısa ad", "aciklama": "bu fazda tamamlanacak kapsam", "birimler": ["eksikler listesinden birim adları"]}}]}}

Kurallar: kaynak kapsamı anlatan dosyalardaki birimleri, kanıt dosyasındaki üretilen kaynak dosyalarıyla karşılaştır. Envanterde geçmeyen birim UYDURMA.
Eksik yoksa {{"tamam": true, "ozet": "...", "eksikler": [], "fazlar": []}}. En fazla {EN_FAZLA_FAZ} faz; her eksik birim bir fazda olmalı;
benzer/aynı modül birimlerini aynı fazda topla; kritik ve bağımlılık veren birimler (kabuk, kimlik, ortak bileşen) önceki fazda olsun.
"""


def _sonraki_no(kok: Path) -> int:
    d = kok / DIZIN
    nolar = [int(m.group(1)) for p in d.glob("K*.json") if (m := re.fullmatch(r"K(\d+)\.json", p.name))] if d.exists() else []
    return max(nolar, default=0) + 1


def _denetim_gorevleri(board: dict) -> dict[str, dict]:
    """{K<n>: T1 görevi} — çıktı yolundan tanınır."""
    sonuc = {}
    for _, t in B.all_tasks(board):
        for o in t.get("outputs") or []:
            m = re.fullmatch(re.escape(DIZIN) + r"/(K\d+)\.json", o)
            if m:
                sonuc[m.group(1)] = t
    return sonuc


def _sonuc(kid: str, kok: Path) -> str | None:
    p = kok / DIZIN / f"{kid}.uygulandi"
    return p.read_text(encoding="utf-8").strip() if p.exists() else None


def gerekli(board: dict, kok: Path = ROOT, cfg: dict | None = None) -> bool:
    if not acik_mi(cfg):
        return False
    if any(t["status"] not in B.TERMINAL for _, t in B.all_tasks(board)):
        return False
    if not any(t["status"] == B.DONE for _, t in B.all_tasks(board)):
        return False
    try:
        import faz_planla as FP
        if FP.gerekli(board, kok) is not None:           # önce bekleyen faz planı
            return False
    except Exception:
        pass
    gorevler = _denetim_gorevleri(board)
    for kid in gorevler:
        if _sonuc(kid, kok) is None:                      # sonuçlanmamış denetim var
            return False
    if gorevler and _sonuc(max(gorevler, key=lambda k: int(k[1:])), kok) in ("tamam", "atlandi"):
        return False
    return len(gorevler) < en_fazla(cfg)


def tetikle(board: dict, org: dict, cfg: dict | None = None, kok: Path = ROOT) -> str | None:
    if not gerekli(board, kok, cfg):
        return None
    (kok / DIZIN).mkdir(parents=True, exist_ok=True)
    (kok / DIZIN / "_sema.md").write_text(sema_metni(), encoding="utf-8")
    kanit = kanit_yaz(board, kok, cfg)
    girdiler = ", ".join(envanter_dosyalari(kok, cfg) + [kanit, f"{DIZIN}/_sema.md"])
    no = _sonraki_no(kok)
    kid = f"K{no}"
    sid = f"S{len(board.get('sprints', [])) + 1}"
    cikti = f"{DIZIN}/{kid}.json"
    sprint = {
        "id": sid, "name": f"Kapsam denetimi — {kid}", "goal": "Kaynak kapsamı ile üretilen kodu karşılaştırıp eksik kapsamı fazlara bölmek",
        "planned_days": 1,
        "tasks": [{"id": f"{sid}-T1", "title": f"{kid} kapsam açığı denetimi", "role": "sprint_planner", "phase": "develop",
                   "description": ("Tüm görevler bitti; kaynak kapsamın hâlâ eksik kalan kısmını bul. Kaynak kapsamı anlatan dosyalardaki her ekranı/modülü, "
                                   "kanıt dosyasındaki üretilen arayüz kaynak dosyaları ve atlanan görevlerle karşılaştır. Şema ve kurallar _sema.md'de. "
                                   f"Çıktı yalnız JSON. Girdi: {girdiler}"),
                   "outputs": [cikti], "depends_on": []}],
    }
    B.append_sprint(board, sprint)
    B.audit("engine", "kapsam_denetimi_baslatildi", detay={"denetim": kid, "sprint": sid})
    return sid


def rapor_dogrula(rapor: object, kok: Path = ROOT, cfg: dict | None = None) -> list[str]:
    if not isinstance(rapor, dict) or not isinstance(rapor.get("tamam"), bool):
        return ["rapor geçersiz: 'tamam' (true/false) yok"]
    eksikler, fazlar = rapor.get("eksikler"), rapor.get("fazlar")
    if not isinstance(eksikler, list) or not isinstance(fazlar, list):
        return ["'eksikler' ve 'fazlar' liste olmalı"]
    if rapor["tamam"]:
        return [] if not eksikler and not fazlar else ["tamam=true iken eksikler/fazlar boş olmalı"]
    errs = []
    if not eksikler or not fazlar:
        errs.append("tamam=false iken en az bir eksik ve bir faz gerekli")
    if len(fazlar) > EN_FAZLA_FAZ:
        errs.append(f"en fazla {EN_FAZLA_FAZ} faz")
    metin = ""
    for e in envanter_dosyalari(kok, cfg):
        try:
            metin += (kok / e).read_text(encoding="utf-8", errors="ignore").lower() + "\n"
        except OSError:
            pass
    adlar = set()
    for e in eksikler:
        b = (e.get("birim") if isinstance(e, dict) else "") or ""
        if not b.strip() or not (isinstance(e, dict) and (e.get("kanit") or "").strip()):
            errs.append(f"eksik kaydı birim/kanit eksik: {b[:40]!r}")
            continue
        if b.strip().lower() not in metin:
            errs.append(f"birim envanterde geçmiyor (uydurma?): {b[:60]}")
        adlar.add(b.strip())
    kapsanan = set()
    for f in fazlar:
        if not isinstance(f, dict) or not (f.get("ad") or "").strip() or not (f.get("aciklama") or "").strip() or not f.get("birimler"):
            errs.append("faz ad/aciklama/birimler eksik")
            continue
        for b in f["birimler"]:
            if str(b).strip() not in adlar:
                errs.append(f"fazdaki birim eksikler listesinde yok: {str(b)[:60]}")
            kapsanan.add(str(b).strip())
    for b in sorted(adlar - kapsanan):
        errs.append(f"eksik birim hiçbir fazda değil: {b[:60]}")
    return errs


def rapor_oku(kid: str, kok: Path = ROOT, cfg: dict | None = None) -> tuple[dict | None, list[str]]:
    p = kok / DIZIN / f"{kid}.json"
    if not p.exists():
        return None, ["rapor dosyası yok"]
    ham = p.read_text(encoding="utf-8")
    try:
        rapor = json.loads(ham[ham.index("{"):ham.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return None, ["rapor geçerli JSON değil"]
    return rapor, rapor_dogrula(rapor, kok, cfg)


def fazlari_ac(rapor: dict) -> list[str]:
    """Aktif fazı TAMAMLANDI yapar, rapordaki fazları ekler (ilki AKTIF). Açılan faz id'lerini döndürür."""
    import karar_verici_triage as KVT
    data = KVT.load_fazlar()
    fazlar = data.setdefault("fazlar", [])
    for f in fazlar:
        if f.get("durum") == "AKTIF":
            f["durum"], f["kilitli"] = "TAMAMLANDI", True
    sayilar = [int(m.group(1)) for f in fazlar if (m := re.fullmatch(r"FAZ-(\d+)", f.get("id", "")))]
    no = max(sayilar, default=0)
    onceki = fazlar[-1]["id"] if fazlar else None
    acilan = []
    for i, f in enumerate(rapor["fazlar"]):
        no += 1
        fid = f"FAZ-{no}"
        birimler = ", ".join(str(b) for b in f["birimler"])
        fazlar.append({"id": fid, "ad": f["ad"].strip(), "aciklama": f"{f['aciklama'].strip()} Kapsam: {birimler}", "durum": "AKTIF" if i == 0 else "PLANLANDI",
                       "hedef_tarih": "", "kilitli": i != 0, "onkosul_faz": onceki})
        onceki = fid
        acilan.append(fid)
    KVT.save_fazlar(data)
    return acilan


def kontrol(board: dict, cfg: dict | None = None, kok: Path = ROOT) -> bool:
    """Her koşucu turunda: biten denetim raporunu doğrular/uygular. Panoyu değiştirdiyse True."""
    degisti = False
    for kid, t in _denetim_gorevleri(board).items():
        if _sonuc(kid, kok) is not None:
            continue
        if t["status"] == B.SKIPPED:
            (kok / DIZIN / f"{kid}.uygulandi").write_text("atlandi", encoding="utf-8")
            B.audit("engine", "kapsam_denetimi_atlandi", detay={"denetim": kid})
            continue
        if t["status"] != B.DONE:
            continue
        rapor, errs = rapor_oku(kid, kok, cfg)
        if errs:
            t["description"] = re.sub(r"\n\nGEÇERSİZ RAPOR:.*$", "", t["description"], flags=re.S) + "\n\nGEÇERSİZ RAPOR: " + "; ".join(errs[:8]) + " — düzeltip JSON'u yeniden yaz."
            B.mark(board, t["id"], B.TODO, "rapor doğrulanamadı: " + errs[0][:120])
            B.refresh(board)
            degisti = True
            continue
        if rapor["tamam"]:
            (kok / DIZIN / f"{kid}.uygulandi").write_text("tamam", encoding="utf-8")
            B.audit("engine", "kapsam_denetimi_tamam", detay={"denetim": kid, "ozet": rapor.get("ozet", "")[:200]})
        else:
            acilan = fazlari_ac(rapor)
            (kok / DIZIN / f"{kid}.uygulandi").write_text("faz:" + ",".join(acilan), encoding="utf-8")
            B.audit("engine", "kapsam_fazlari_acildi", detay={"denetim": kid, "fazlar": acilan, "eksik": len(rapor["eksikler"]), "ozet": rapor.get("ozet", "")[:200]})
        degisti = True
    return degisti
