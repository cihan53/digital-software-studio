#!/usr/bin/env python3
"""Envanter aşaması (issue #273): taşıma/dönüştürme projelerinde kod yazılmadan ÖNCE kaynak sistemin tam envanteri çıkar.

Sıra (hepsi panoya görev olarak eklenir; insan müdahalesi yok, sistem kararı audit_log'a düşer):
  1. Rota listesi  : `envanter_analisti` kaynaktaki TÜM ekran/modal/çekmeceleri listeler (_rotalar.json).
                     Motor doğrular: her birimin kaynak dosyası diskte var mı, kimlikler tekil mi, modalın üst ekranı var mı.
  2. Birim envanteri: her birim için AYRI dosya (ekranlar/<id>.md): veri yapısı, bileşenler, tablolar, butonlar ve aksiyonlar,
                     yönlendirmeler, modal/çekmeceler, yetki, API. Tamlık kapısı: dosya yok/başlık boş → görev yeniden açılır.
  3. Ana şablon    : tasarım sistemi + layout/kabuk tasarımı (envanterin ortak kalıplarından).
  4. Ekran tasarımı: modül/parça başına ekran tasarımları (envanter dosyaları girdi).
  5. Plan          : mevcut faz planlama (#249) bu girdilerle sprintleri planlar; eksik kalan, kapsam denetimi (#271) ile fazlara açılır.
Uydurma yok: rota listesindeki her kaynak yolu diskte bulunmalı; envanter dosyası boş/yalnız başlık olamaz.
Durum: workspace/docs/envanter/_durum.json {"asama": rotalar|envanter|tasarim|plan|tamam}. Kapatma: STUDIO_ENVANTER=0 ya da
studio.config.json → envanter.acik=false. Ayar: envanter.parca (görev başına birim, varsayılan 4).
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

DIZIN = "workspace/docs/envanter"
ROTALAR = f"{DIZIN}/_rotalar.json"
EKRAN_DIZIN = f"{DIZIN}/ekranlar"
INDEKS = f"{DIZIN}/_indeks.md"
DURUM = f"{DIZIN}/_durum.json"
TASARIM_DIZIN = "workspace/docs/tasarim"
SABLON = f"{TASARIM_DIZIN}/_ana_sablon.md"
ANALIST, TASARIMCI = "envanter_analisti", "ui_designer"
TASARIM_ATLANAN_ROLLER = {"ux_lead", "ui_designer", "design_auditor", "tech_scout", "security_lead"}   # kaynak okumadan envanter uydurmasınlar; görev olarak sonra çalışırlar
TURLER = {"ekran", "modal", "cekmece"}
BASLIKLAR = ["Veri yapısı", "Bileşenler", "Tablolar", "Butonlar ve aksiyonlar", "Yönlendirmeler", "Modal ve çekmeceler", "Yetki ve görünürlük", "API çağrıları"]
EN_FAZLA_GOREV_SPRINT = 6
TEKRAR_SINIRI = 3


def acik_mi(cfg: dict | None, kok: Path = ROOT) -> bool:
    if os.environ.get("STUDIO_ENVANTER") == "0":
        return False
    e = (cfg or {}).get("envanter") or {}
    if not e.get("acik", True):
        return False
    if ((cfg or {}).get("planlama") or {}).get("uretici") == "birim":      # keşif tabanlı yol seçilmiş
        return False
    kaynak = ((cfg or {}).get("source") or {}).get("path")
    return bool(kaynak) and Path(kaynak).exists()


def parca(cfg: dict | None) -> int:
    return max(1, int(((cfg or {}).get("envanter") or {}).get("parca", 4)))


def kaynak_yolu(cfg: dict) -> Path:
    return Path(cfg["source"]["path"])


def durum_oku(kok: Path = ROOT) -> dict:
    try:
        return json.loads((kok / DURUM).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def durum_yaz(durum: dict, kok: Path = ROOT) -> None:
    p = kok / DURUM
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(durum, ensure_ascii=False, indent=1), encoding="utf-8")


def gerekli(cfg: dict | None, kok: Path = ROOT) -> bool:
    """Pano ilk kez kurulurken: envanter aşaması başlamalı mı? (kaynak tanımlı, daha önce tamamlanmamış)"""
    return acik_mi(cfg, kok) and durum_oku(kok).get("asama") is None


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "birim"


def sema_metni() -> str:
    return f"""# Envanter şemaları

## Rota listesi (_rotalar.json) — yalnızca GEÇERLİ JSON
{{"birimler": [{{"id": "kısa-kebab-id", "ad": "ekranın okunur adı", "rota": "/yol veya modal anahtarı", "tur": "ekran | modal | cekmece",
  "ust": "modal/çekmece ise bağlı olduğu ekranın id'si, değilse boş", "modul": "üst düzey modül adı", "kaynak": "kaynak projeye göre göreli dosya yolu (bileşen/şablon)"}}]}}
Kural: kaynaktaki HER rota/ekran, içindeki HER modal ve çekmece ayrı birimdir (yönlendirmeyle açılanlar dahil). Dosya yolları kaynakta GERÇEKTEN var olmalı.

## Birim envanter dosyası ({EKRAN_DIZIN}/<id>.md) — aşağıdaki başlıkların HEPSİ, her biri dolu
""" + "\n".join(f"## {b}" for b in BASLIKLAR) + """

İçerik kuralları: kaynak kodu oku; yalnız gördüğünü yaz; bilmediğine 'bilinmiyor', olmayana 'yok' yaz — başlık boş KALAMAZ, değer/davranış UYDURMA.
Veri yapısı: ekranın kullandığı model/alanlar ve tipleri. Bileşenler: kullanılan bileşenler/widget'lar. Tablolar: kolonlar, sıralama/filtre/sayfalama.
Butonlar ve aksiyonlar: her buton/menü öğesi → ne yapar (API/gezinme/modal). Yönlendirmeler: gelen ve giden rotalar. Modal ve çekmeceler: açan öğe, içerik, kendi birim id'si.
Yetki ve görünürlük: rol/menü/özellik koşulları. API çağrıları: yöntem + uç + ne zaman.
"""


def rota_dogrula(rapor: object, cfg: dict) -> list[str]:
    if not isinstance(rapor, dict) or not isinstance(rapor.get("birimler"), list) or not rapor["birimler"]:
        return ["'birimler' listesi yok ya da boş"]
    errs, ids = [], set()
    kaynak = kaynak_yolu(cfg)
    for b in rapor["birimler"]:
        if not isinstance(b, dict):
            errs.append("birim kaydı nesne değil")
            continue
        i = b.get("id") or ""
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", i):
            errs.append(f"geçersiz id: {i!r}")
        if i in ids:
            errs.append(f"yinelenen id: {i}")
        ids.add(i)
        for k in ("ad", "rota", "modul", "kaynak"):
            if not (b.get(k) or "").strip():
                errs.append(f"{i}: '{k}' boş")
        if b.get("tur") not in TURLER:
            errs.append(f"{i}: tur {sorted(TURLER)} olmalı")
        k = (b.get("kaynak") or "").strip()
        if k and not (kaynak / k).exists():
            errs.append(f"{i}: kaynak dosyası yok (uydurma?): {k[:80]}")
    for b in rapor["birimler"]:
        if isinstance(b, dict) and b.get("tur") in ("modal", "cekmece") and b.get("ust") not in ids:
            errs.append(f"{b.get('id')}: üst ekran listede yok: {b.get('ust')!r}")
    return errs


def rota_oku(cfg: dict, kok: Path = ROOT) -> tuple[list[dict] | None, list[str]]:
    p = kok / ROTALAR
    if not p.exists():
        return None, ["rota listesi dosyası yok"]
    ham = p.read_text(encoding="utf-8")
    try:
        rapor = json.loads(ham[ham.index("{"):ham.rindex("}") + 1])
    except (ValueError, json.JSONDecodeError):
        return None, ["rota listesi geçerli JSON değil"]
    errs = rota_dogrula(rapor, cfg)
    return (None, errs) if errs else (rapor["birimler"], [])


def baslangic_panosu(cfg: dict, kok: Path = ROOT) -> dict:
    """İlk pano: yalnız rota listesi görevi. Devamı kontrol() ile eklenir."""
    d = kok / DIZIN
    d.mkdir(parents=True, exist_ok=True)
    (d / "_sema.md").write_text(sema_metni(), encoding="utf-8")
    kaynak = kaynak_yolu(cfg)
    sprint = {"id": "S1", "name": "Envanter — rota listesi", "goal": "Kaynak sistemdeki tüm ekran, modal ve çekmecelerin doğrulanmış listesi", "planned_days": 1,
              "tasks": [{"id": "S1-T1", "title": "Kaynak rota ve modal listesi", "role": ANALIST, "phase": "develop",
                         "description": (f"Kaynak proje ({kaynak}) kodunu oku ve TÜM ekranları (yönlendirme tanımlarından), her ekranın modal ve çekmecelerini ayrı birim olarak listele. "
                                         f"Şema ve kurallar _sema.md'de. Çıktı yalnız JSON. Girdi: {DIZIN}/_sema.md"),
                         "outputs": [ROTALAR], "depends_on": []}]}
    durum_yaz({"asama": "rotalar"}, kok)
    B.audit("engine", "envanter_asamasi_baslatildi", detay={"kaynak": str(kaynak)})
    return {"created_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"), "sprints": [sprint]}


def _gorev_ekle(board: dict, sprint_adi: str, hedef: str, gorevler: list[dict]) -> list[str]:
    """Görevleri ≤EN_FAZLA_GOREV_SPRINT'lik sprintlere bölüp ekler; eklenen sprint id'leri."""
    idler = []
    for i in range(0, len(gorevler), EN_FAZLA_GOREV_SPRINT):
        grup = gorevler[i:i + EN_FAZLA_GOREV_SPRINT]
        sid = f"S{len(board.get('sprints', [])) + 1}"
        for n, t in enumerate(grup, 1):
            t["id"] = f"{sid}-T{n}"
        no = f" ({i // EN_FAZLA_GOREV_SPRINT + 1})" if len(gorevler) > EN_FAZLA_GOREV_SPRINT else ""
        B.append_sprint(board, {"id": sid, "name": f"{sprint_adi}{no}", "goal": hedef, "planned_days": 1, "tasks": grup})
        idler.append(sid)
    return idler


def _gruplar(birimler: list[dict], n: int) -> list[tuple[str, list[dict]]]:
    """Modül sırasıyla n'li parçalar: [(modul, [birim...])]."""
    sonuc = []
    modullar: dict[str, list[dict]] = {}
    for b in birimler:
        modullar.setdefault(b["modul"], []).append(b)
    for m, us in modullar.items():
        for i in range(0, len(us), n):
            sonuc.append((m, us[i:i + n]))
    return sonuc


def _envanter_gorevleri(birimler: list[dict], cfg: dict) -> list[dict]:
    kaynak = kaynak_yolu(cfg)
    gorevler = []
    for m, us in _gruplar(birimler, parca(cfg)):
        liste = "; ".join(f"{u['id']} = {u['ad']} ({u['tur']}, rota {u['rota']}, kaynak {u['kaynak']})" for u in us)
        gorevler.append({"title": f"Envanter: {m} ({', '.join(u['id'] for u in us)[:60]})", "role": ANALIST, "phase": "develop",
                         "description": (f"Kaynak proje ({kaynak}) kodunu oku; şu birimlerin HER BİRİ için AYRI dosya yaz ({EKRAN_DIZIN}/<id>.md): {liste}. "
                                         f"Her dosyada şu başlıkların HEPSİ dolu olmalı: {', '.join(BASLIKLAR)}. Şema/kurallar: {DIZIN}/_sema.md. "
                                         f"Bilmediğine 'bilinmiyor' yaz, uydurma. Girdi: {DIZIN}/_sema.md"),
                         "outputs": [f"{EKRAN_DIZIN}/"], "depends_on": []})
    return gorevler


def _task_sprint(board: dict, task_id: str):
    for s in board.get("sprints", []):
        for t in s["tasks"]:
            if t["id"] == task_id:
                return s, t
    return None, None


def dosya_eksikleri(birim_id: str, kok: Path = ROOT) -> list[str]:
    p = kok / EKRAN_DIZIN / f"{birim_id}.md"
    if not p.exists():
        return ["dosya yok"]
    m = p.read_text(encoding="utf-8", errors="ignore")
    eksik = []
    for b in BASLIKLAR:
        mm = re.search(r"^#{2,4}\s*" + re.escape(b) + r"\s*$(.*?)(?=^#{2,4}\s|\Z)", m, re.S | re.M | re.I)
        if not mm:
            eksik.append(f"başlık yok: {b}")
        elif len(mm.group(1).strip()) < 3:
            eksik.append(f"başlık boş: {b}")
    return eksik


def indeks_yaz(birimler: list[dict], kok: Path = ROOT) -> None:
    L = ["# Envanter indeksi (motor üretti)", "", f"{len(birimler)} birim. Ayrıntı: `{EKRAN_DIZIN}/<id>.md`.", "",
         "| id | Ad | Tür | Rota | Modül | Üst | Dosya |", "|---|---|---|---|---|---|---|"]
    L += [f"| {b['id']} | {b['ad']} | {b['tur']} | {b['rota']} | {b['modul']} | {b.get('ust') or '-'} | {EKRAN_DIZIN}/{b['id']}.md |" for b in birimler]
    (kok / INDEKS).write_text("\n".join(L) + "\n", encoding="utf-8")


def _tasarim_gorevleri(birimler: list[dict], cfg: dict) -> tuple[dict, list[dict]]:
    ekran_tur = [b for b in birimler if b["tur"] == "ekran"]
    ornek = ", ".join(f"{EKRAN_DIZIN}/{b['id']}.md" for b in ekran_tur[:6])
    sablon = {"title": "Ana şablon ve tasarım sistemi", "role": TASARIMCI, "phase": "develop",
              "description": ("Kaynak sistemin envanterinden ortak kalıpları çıkararak ANA ŞABLONU tasarla: layout (üst çubuk, yan menü, içerik alanı), filtre/başlık düzeni, "
                              "ortak bileşenler (tablo, kart, modal, çekmece, boş/yükleme/hata/yetkisiz durumları), karanlık mod, çoklu dil. Brief'teki stil politikasına uy. "
                              f"Çıktılar: tasarım sistemi + ana şablon. Girdi: {INDEKS}, {ornek}"),
              "outputs": ["workspace/docs/tasarim_sistemi.md", SABLON], "depends_on": []}
    gorevler = [{"title": "Paket ve kütüphane seçimi", "role": "tech_scout", "phase": "develop",
                 "description": f"Brief'teki teknoloji kararına ve ana şablondaki bileşen ihtiyaçlarına (tablo, grafik, form, i18n) göre paket/kütüphane seçimi. Girdi: {SABLON}, {INDEKS}",
                 "outputs": ["workspace/docs/paket_secim_raporu.md"], "depends_on": []}]
    gorevler.append({"title": "Güvenlik ve gizlilik tasarımı", "role": "security_lead", "phase": "develop",
                     "description": f"Teknik mimari, backlog ve paket seçimine göre güvenlik tasarımı ve tehdit modeli. Girdi: workspace/docs/paket_secim_raporu.md, {INDEKS}",
                     "outputs": ["workspace/docs/guvenlik_tasarimi.md", "workspace/docs/tehdit_modeli.md"], "depends_on": []})
    for m, us in _gruplar([b for b in birimler], parca(cfg)):
        dosyalar = ", ".join(f"{EKRAN_DIZIN}/{u['id']}.md" for u in us)
        gorevler.append({"title": f"Ekran tasarımı: {m} ({', '.join(u['id'] for u in us)[:60]})", "role": TASARIMCI, "phase": "develop",
                         "description": (f"Şu birimlerin her biri için ekran tasarımı: yerleşim, tablolar, butonlar/aksiyonlar, modal/çekmeceler, durumlar. Ana şablona ({SABLON}) uy. "
                                         f"Envanterdeki hiçbir widget/aksiyon/modalı düşürme; iyileştirmeleri belirt. Girdi: {SABLON}, {dosyalar}"),
                         "outputs": [f"{TASARIM_DIZIN}/ekranlar/{slug(m)}.md"], "depends_on": []})
    for i, g in enumerate([g for g in gorevler if "/ekranlar/" in g["outputs"][0]], 1):   # çıktı adı çakışmasını önle
        g["outputs"] = [f"{TASARIM_DIZIN}/ekranlar/{i:02d}-{g['outputs'][0].rsplit('/', 1)[1]}"]
    return sablon, gorevler


def kontrol(board: dict, org: dict | None = None, cfg: dict | None = None, kok: Path = ROOT) -> bool:
    """Her koşucu turunda: aşamaları ilerletir. Panoyu değiştirdiyse True."""
    durum = durum_oku(kok)
    asama = durum.get("asama")
    if asama is None or asama == "tamam":
        return False
    degisti = False
    if asama == "rotalar":
        _, t = _task_sprint(board, "S1-T1")
        if t is None or t["status"] != B.DONE:
            return False
        birimler, errs = rota_oku(cfg, kok)
        if errs:
            t["description"] = re.sub(r"\n\nGEÇERSİZ LİSTE:.*$", "", t["description"], flags=re.S) + "\n\nGEÇERSİZ LİSTE: " + "; ".join(errs[:8]) + " — düzeltip JSON'u yeniden yaz."
            B.mark(board, t["id"], B.TODO, "rota listesi doğrulanamadı: " + errs[0][:120])
            B.refresh(board)
            return True
        gorevler = _envanter_gorevleri(birimler, cfg)
        sprintler = _gorev_ekle(board, "Envanter — birim dosyaları", "Her ekran/modal için eksiksiz envanter dosyası", gorevler)
        durum.update(asama="envanter", sprintler=sprintler, birim_sayisi=len(birimler))
        durum_yaz(durum, kok)
        B.audit("engine", "envanter_rotalar_dogrulandi", detay={"birim": len(birimler), "gorev": len(gorevler)})
        B.refresh(board)
        return True
    if asama == "envanter":
        birimler, _ = rota_oku(cfg, kok)
        gorevler = [t for s in board["sprints"] if s["id"] in durum.get("sprintler", []) for t in s["tasks"]]
        if not gorevler or any(t["status"] not in B.TERMINAL for t in gorevler):
            return False
        tekrar = durum.setdefault("tekrar", {})
        eksik_toplam, yeniden = {}, 0
        for t in gorevler:
            ids = re.findall(r"([a-z0-9][a-z0-9-]*) = ", t["description"].split("AYRI dosya yaz", 1)[-1])
            eks = {i: dosya_eksikleri(i, kok) for i in ids}
            eks = {i: e for i, e in eks.items() if e}
            if not eks:
                continue
            if tekrar.get(t["id"], 0) >= TEKRAR_SINIRI:
                eksik_toplam.update(eks)
                continue
            tekrar[t["id"]] = tekrar.get(t["id"], 0) + 1
            t["description"] = re.sub(r"\n\nEKSİK ENVANTER:.*$", "", t["description"], flags=re.S) + "\n\nEKSİK ENVANTER: " + "; ".join(f"{i}: {', '.join(e[:3])}" for i, e in list(eks.items())[:6]) + " — yalnız bunları tamamla/yaz."
            B.mark(board, t["id"], B.TODO, "envanter eksik: " + next(iter(eks))[:60])
            yeniden += 1
        if yeniden:
            durum_yaz(durum, kok)
            B.refresh(board)
            return True
        indeks_yaz(birimler, kok)
        durum.update(asama="tasarim", eksik_birimler=sorted(eksik_toplam))
        sablon, tasarim = _tasarim_gorevleri(birimler, cfg)
        ids = _gorev_ekle(board, "Ana şablon tasarımı", "Layout/kabuk ve ortak bileşenlerin ana şablonu", [sablon])
        sablon_id = [t["id"] for s in board["sprints"] if s["id"] == ids[0] for t in s["tasks"]][0]
        for g in tasarim:
            g["depends_on"] = [sablon_id]
        ids += _gorev_ekle(board, "Ekran tasarımları", "Her ekranın envantere dayalı tasarımı", tasarim)
        paket = next((t["id"] for _, t in B.all_tasks(board) if t["title"] == "Paket ve kütüphane seçimi"), None)
        guvenlik = next((t for _, t in B.all_tasks(board) if t["title"] == "Güvenlik ve gizlilik tasarımı"), None)
        if paket and guvenlik:
            guvenlik["depends_on"] = [paket]
        durum["sprintler_tasarim"] = ids
        durum_yaz(durum, kok)
        B.audit("engine", "envanter_tamamlandi", detay={"birim": len(birimler), "eksik": len(eksik_toplam), "tasarim_gorevi": len(tasarim) + 1})
        B.refresh(board)
        return True
    if asama == "tasarim":
        gorevler = [t for s in board["sprints"] if s["id"] in durum.get("sprintler_tasarim", []) for t in s["tasks"]]
        if not gorevler or any(t["status"] not in B.TERMINAL for t in gorevler):
            return False
        try:
            import faz_planla as FP
            faz, _ = FP.aktif_faz(kok)
            sid = FP.tetikle(board, org or {}, cfg, zorla=faz["id"], kok=kok) if faz else None
        except Exception:
            sid = None
        durum["asama"] = "plan"
        durum["plan_sprinti"] = sid
        durum_yaz(durum, kok)
        B.audit("engine", "envanter_plana_geciliyor", detay={"plan_sprinti": sid})
        B.refresh(board)
        return True
    if asama == "plan":
        try:
            import faz_planla as FP
            faz, _ = FP.aktif_faz(kok)
            if faz and FP.uygulandi_yolu(faz["id"], kok).exists():
                durum["asama"] = "tamam"
                durum_yaz(durum, kok)
                B.audit("engine", "envanter_asamasi_tamam", detay={"faz": faz["id"]})
        except Exception:
            pass
    return degisti
