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
    eski = durum_oku(kok).get("asama")
    p.write_text(json.dumps(durum, ensure_ascii=False, indent=1), encoding="utf-8")
    if durum.get("asama") != eski and eski is not None:         # aşama geçişi: geri dönüş noktası (#275)
        try:
            import kontrol_noktasi as KN
            KN.olustur(f"envanter-{eski}-bitti", "", kok)
        except Exception:
            pass


def gerekli(cfg: dict | None, kok: Path = ROOT) -> bool:
    """Pano ilk kez kurulurken: envanter aşaması başlamalı mı? (kaynak tanımlı, daha önce tamamlanmamış)"""
    return acik_mi(cfg, kok) and durum_oku(kok).get("asama") is None


def ertele(cfg: dict | None, kok: Path = ROOT) -> bool:
    """Tasarım aşaması rolleri (ux_lead, ui_designer, design_auditor, tech_scout, security_lead) tasarım aşamasında hiç çalışmaz: envanter aşaması açık projelerde
    yalnız pano görevi olarak (envanterden sonra) çalışırlar; aşama tamamlansa da brief'ten kaba belge üretmek için yeniden çalıştırılmazlar (#287)."""
    return acik_mi(cfg, kok)


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
Veri yapısı: ekranın kullandığı model/alanlar ve tipleri. Bileşenler: kullanılan bileşenler/widget'lar; her widget için veri kaynağı (kendi API/servis çağrısı, üst bileşenden props ya da ortak store) ve sayfadaki yerleşimi (grid konumu/boyutu, biliniyorsa). Tablolar: kolonlar, sıralama/filtre/sayfalama.
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
                                         f"Şema ve kurallar _sema.md'de.{referans_notu(cfg)} Çıktı yalnız JSON. Girdi: {DIZIN}/_sema.md"),
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


def referans_notu(cfg: dict) -> str:
    """Görev açıklamalarına: kaynak koda ek olarak referans (eski) sistemde doğrulama talimatı."""
    try:
        import referans_sistem as RS
        t = RS.tanim(cfg)
    except ImportError:
        return ""
    if not t["url"]:
        return ""
    return (f" REFERANS SİSTEM (eski sistem, SALT-OKUMA): {t['url']} — yalnız kaynak koddan karar verme; erişebiliyorsan ekranı/modalı/tabloyu referans sistemde de doğrula, "
            "çelişki ya da doğrulanamayan kısım için 'referansta doğrulanamadı' ya da 'referansta farklı' notu düş (giriş gerektiren sayfalarda uydurma).")


def _envanter_gorevleri(birimler: list[dict], cfg: dict) -> list[dict]:
    kaynak = kaynak_yolu(cfg)
    gorevler = []
    for m, us in _gruplar(birimler, parca(cfg)):
        liste = "; ".join(f"{u['id']} = {u['ad']} ({u['tur']}, rota {u['rota']}, kaynak {u['kaynak']})" for u in us)
        gorevler.append({"title": f"Envanter: {m} ({', '.join(u['id'] for u in us)[:60]})", "role": ANALIST, "phase": "develop",
                         "description": (f"Kaynak proje ({kaynak}) kodunu oku; şu birimlerin HER BİRİ için AYRI dosya yaz ({EKRAN_DIZIN}/<id>.md): {liste}. "
                                         f"Her dosyada şu başlıkların HEPSİ dolu olmalı: {', '.join(BASLIKLAR)}. Şema/kurallar: {DIZIN}/_sema.md. "
                                         f"Bilmediğine 'bilinmiyor' yaz, uydurma.{referans_notu(cfg)} Girdi: {DIZIN}/_sema.md"),
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


_ISARET = re.compile(r"={3,}[ \t]*FILE:[ \t]*([^\n=]+?)[ \t]*={3,}[ \t\r]*$", re.MULTILINE)


def cikti_kurtar(kok: Path = ROOT) -> list[str]:
    """Çıktıda '=== FILE: x ===' işareti okunamadığı için ekranlar/_CIKTI.md'ye dökülmüş birim dosyalarını geri yazar (#301). Yalnız eksik olanları yazar."""
    p = kok / EKRAN_DIZIN / "_CIKTI.md"
    if not p.exists():
        return []
    m = p.read_text(encoding="utf-8", errors="ignore")
    isaretler = list(_ISARET.finditer(m))
    yazilan = []
    for i, x in enumerate(isaretler):
        ad = x.group(1).strip().lstrip("/")
        hedef = (kok / EKRAN_DIZIN / ad).resolve()
        if "/" in ad or not ad.endswith(".md") or (kok / EKRAN_DIZIN).resolve() not in hedef.parents or hedef.exists():
            continue
        govde = m[x.end(): isaretler[i + 1].start() if i + 1 < len(isaretler) else len(m)].strip("\r\n")
        if len(govde.strip()) > 200:
            hedef.write_text(govde + "\n", encoding="utf-8")
            yazilan.append(ad[:-3])
    return yazilan


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
                              "ortak bileşenler (tablo, kart, modal, çekmece, boş/yükleme/hata/yetkisiz durumları), karanlık mod, çoklu dil. Envanterde tekrar eden kalıpları "
                              "ORTAK BİLEŞEN/WİDGET KATALOĞUNA çıkar (ad, kullanıldığı birimler, veri kaynağı, grid davranışı). Brief'teki stil ve mimari kurallara (bileşen/widget, veri çekme, grid layout) uy. "
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
                         "description": (f"Şu birimlerin her biri için ekran tasarımı: yerleşim, tablolar, butonlar/aksiyonlar, modal/çekmeceler, durumlar. Ana şablona ({SABLON}) ve brief'teki mimari kurallara uy; ortak bileşen/widget kataloğundaki parçaları kullan, yeni ortak parça gerekiyorsa katalog ekine yaz. "
                                         f"Envanterdeki hiçbir widget/aksiyon/modalı düşürme; iyileştirmeleri belirt. Girdi: {SABLON}, {dosyalar}"),
                         "outputs": [f"{TASARIM_DIZIN}/ekranlar/{slug(m)}.md"], "depends_on": []})
    for i, g in enumerate([g for g in gorevler if "/ekranlar/" in g["outputs"][0]], 1):   # çıktı adı çakışmasını önle
        g["outputs"] = [f"{TASARIM_DIZIN}/ekranlar/{i:02d}-{g['outputs'][0].rsplit('/', 1)[1]}"]
    return sablon, gorevler


ONIZLEME_DIZIN = f"{TASARIM_DIZIN}/onizleme"
HTML_TALIMAT = ("Çıktı TEK dosyalık STATİK HTML önizleme olsun: satır içi CSS, betik (<script>) YOK, harici kaynak (CDN, font, görsel URL) YOK. "
                "Ekran/birim başına ayrı bölüm; sticky başlık (ekran adı + filtre barı + aksiyonlar), grid layout ile widget/tablo/modal-çekmece yerleşimi, "
                "boş/yükleme/hata/yetkisiz durumları görsel olarak gösterilsin. Sayı, isim, kişi verisi UYDURMA: veri alanlarında 'veri yok' iskeleti kullan. "
                "Tasarım dokümanındaki hiçbir widget/aksiyon/modalı düşürme.")


def html_acik(cfg: dict | None) -> bool:
    return bool(((cfg or {}).get("envanter") or {}).get("html_onizleme", True))


def onizleme_eksikleri(yol: Path) -> list[str]:
    """Statik HTML önizleme geçerli mi? (var, HTML, betik/harici kaynak yok, boş değil)"""
    if not yol.exists():
        return ["dosya yok"]
    m = yol.read_text(encoding="utf-8", errors="ignore")
    ml = m.lower()
    eksik = []
    if "<html" not in ml and "<!doctype" not in ml:
        eksik.append("HTML değil")
    if len(m.strip()) < 400:
        eksik.append("içerik çok kısa")
    if "<script" in ml:
        eksik.append("<script> kullanılmış")
    # Harici KAYNAK: src=, <link href=>, url(), @import. Düz bağlantılar (<a href>) kaynak değildir, serbesttir (#299).
    if (re.search(r"src\s*=\s*[\"']https?://", ml) or re.search(r"<link[^>]+href\s*=\s*[\"']https?://", ml)
            or re.search(r"url\(\s*[\"']?https?://", ml) or "@import" in ml):
        eksik.append("harici kaynak kullanılmış")
    return eksik


def _onizleme_ekle(board: dict, cfg: dict, durum: dict, kok: Path = ROOT) -> bool:
    """Ana şablon ve her ekran tasarımı için HTML önizleme görevleri ekler (yalnız bir kez). Eklediyse True."""
    if "sprintler_onizleme" in durum or not html_acik(cfg):
        return False
    tum = [t for _, t in B.all_tasks(board)]
    sablon = next((t for t in tum if SABLON in (t.get("outputs") or [])), None)
    tasarimlar = [t for t in tum if any(o.startswith(f"{TASARIM_DIZIN}/ekranlar/") for o in (t.get("outputs") or []))]
    if sablon is None or not tasarimlar:
        return False

    def bagimlilik(t):
        return [t["id"]] if t["status"] not in B.TERMINAL else []

    gorevler = [{"title": "Önizleme: ana şablon", "role": TASARIMCI, "phase": "develop",
                 "description": (f"Ana şablonun ({SABLON}) ve tasarım sistemi (workspace/docs/tasarim_sistemi.md) görsel önizlemesi: layout, ortak bileşenler, durumlar. {HTML_TALIMAT} "
                                 f"Girdi: {SABLON}, workspace/docs/tasarim_sistemi.md"),
                 "outputs": [f"{ONIZLEME_DIZIN}/_ana_sablon.html"], "depends_on": bagimlilik(sablon)}]
    for t in tasarimlar:
        md = t["outputs"][0]
        ad = md.rsplit("/", 1)[1].rsplit(".", 1)[0]
        gorevler.append({"title": f"Önizleme: {ad}", "role": TASARIMCI, "phase": "develop",
                         "description": (f"{md} tasarımının görsel önizlemesi; ana şablona ({SABLON}) uy. {HTML_TALIMAT} Girdi: {md}, {SABLON}"),
                         "outputs": [f"{ONIZLEME_DIZIN}/{ad}.html"], "depends_on": bagimlilik(t)})
    ids = _gorev_ekle(board, "Tasarım önizlemeleri", "Ana şablon ve her ekran tasarımı için statik HTML önizleme", gorevler)
    durum["sprintler_onizleme"] = ids
    durum_yaz(durum, kok)
    B.audit("engine", "envanter_onizleme_eklendi", detay={"gorev": len(gorevler)})
    B.refresh(board)
    return True


def modul_fazlari_acik(cfg: dict | None) -> bool:
    return bool(((cfg or {}).get("envanter") or {}).get("modul_fazlari", True))


def faz_min_birim(cfg: dict | None) -> int:
    return max(1, int(((cfg or {}).get("envanter") or {}).get("faz_min_birim", 3)))


def _baslik(m: str) -> str:
    return " ".join(w.capitalize() for w in re.split(r"[-_\s]+", m) if w) or m


def faz_grupla(birimler: list[dict], cfg: dict | None = None, brief: str = "") -> list[dict]:
    """Envanterden modül tabanlı faz listesi (#303): ilk faz ortak altyapı/kabuk; sonra modül başına faz (brief'te geçen modüller önce);
    faz_min_birim altındaki küçük modüller 'Küçük modüller' fazlarında toplanır (≤6 birim)."""
    moduller: dict[str, list[dict]] = {}
    for b in birimler:
        moduller.setdefault(b["modul"], []).append(b)
    metin = (brief or "").lower()

    def sira(m):
        i = min([x for x in (metin.find(m.lower()), metin.find(m.lower().replace("-", " "))) if x >= 0] or [10 ** 9])
        return (i, list(moduller).index(m))
    sirali = sorted(moduller, key=sira)
    esik = faz_min_birim(cfg)
    buyuk = [m for m in sirali if len(moduller[m]) >= esik]
    kucuk = [m for m in sirali if len(moduller[m]) < esik]
    fazlar = [{"ad": "Ortak altyapı ve kabuk", "moduller": [], "birimler": [],
               "aciklama": ("Nuxt iskeleti, tasarım token'ları, ana şablon (layout/kabuk), ortak bileşen/widget kataloğu, yerel ortam (yerel_ortam.sh), mock katmanı ve CI. "
                            "Ekran birimi içermez: modül fazları kendi ekranlarını bu temelin üstüne yapar.")}]
    for m in buyuk:
        ids = [b["id"] for b in moduller[m]]
        fazlar.append({"ad": f"Modül: {_baslik(m)}", "moduller": [m], "birimler": ids,
                       "aciklama": f"{m} modülünün tüm ekran, modal ve çekmeceleri ({len(ids)} birim): {', '.join(ids)}."})
    parca, mevcut, say = [], [], 0
    for m in kucuk:
        n = len(moduller[m])
        if mevcut and say + n > 6:
            parca.append(mevcut)
            mevcut, say = [], 0
        mevcut.append(m)
        say += n
    if mevcut:
        parca.append(mevcut)
    for i, grup in enumerate(parca, 1):
        ids = [b["id"] for m in grup for b in moduller[m]]
        fazlar.append({"ad": f"Küçük modüller{f' ({i})' if len(parca) > 1 else ''}: {', '.join(grup)}", "moduller": grup, "birimler": ids,
                       "aciklama": f"Küçük modüller ({', '.join(grup)}), {len(ids)} birim: {', '.join(ids)}."})
    return fazlar


def modul_fazlarini_kur(cfg: dict, kok: Path = ROOT, brief: str = "") -> list[str]:
    """Varsayılan genel fazların yerine modül fazlarını kurar (ilki AKTIF); her faza kapsam dosyası yazar. Faz id'lerini döndürür."""
    import karar_verici_triage as KVT
    birimler, errs = rota_oku(cfg, kok)
    if errs or not birimler:
        return []
    if not brief:
        try:
            brief = (kok / "proje_kapsami.md").read_text(encoding="utf-8") if (kok / "proje_kapsami.md").exists() else (kok / "workspace/docs/proje_kapsami.md").read_text(encoding="utf-8")
        except OSError:
            brief = ""
    gruplar = faz_grupla(birimler, cfg, brief)
    onceki, liste, ids = None, [], []
    kapsam_dizin = kok / "workspace/docs/faz_planlari"
    kapsam_dizin.mkdir(parents=True, exist_ok=True)
    tasarim_ortak = [SABLON, "workspace/docs/tasarim_sistemi.md", f"{INDEKS}"]
    for n, g in enumerate(gruplar, 1):
        fid = f"FAZ-{n}"
        liste.append({"id": fid, "ad": g["ad"], "aciklama": g["aciklama"], "durum": "AKTIF" if n == 1 else "PLANLANDI", "hedef_tarih": "",
                      "kilitli": n != 1, "onkosul_faz": onceki})
        girdiler = [x for x in tasarim_ortak if (kok / x).exists()]
        for m in g["moduller"]:
            sl = slug(m)
            girdiler += [f"{TASARIM_DIZIN}/ekranlar/*{sl}*.md", f"{ONIZLEME_DIZIN}/*{sl}*.html"]
        girdiler += [f"{EKRAN_DIZIN}/{b}.md" for b in g["birimler"]][:30]
        (kapsam_dizin / f"{fid}_kapsam.json").write_text(json.dumps({"faz": fid, "modul": ", ".join(g["moduller"]) or "ortak altyapı", "birimler": g["birimler"],
                                                                      "girdiler": girdiler}, ensure_ascii=False, indent=1), encoding="utf-8")
        onceki = fid
        ids.append(fid)
    KVT.save_fazlar({"fazlar": liste})
    try:                                                         # save_fazlar INSERT OR REPLACE yapar: eski (genel) faz satırlarını sil
        conn = KVT.db_conn()
        if conn:
            conn.execute("DELETE FROM fazlar WHERE id NOT IN (%s)" % ",".join("?" * len(ids)), ids)
            conn.commit()
    except Exception:                                            # noqa: BLE001
        pass
    B.audit("engine", "modul_fazlari_kuruldu", detay={"faz": len(ids)})
    return ids


ONAY = "workspace/docs/onaylar/tasarim_onayi.md"


def onay_acik(cfg: dict | None) -> bool:
    return html_acik(cfg) and bool(((cfg or {}).get("envanter") or {}).get("tasarim_onayi", True))


def _onay_ekle(board: dict, durum: dict, kok: Path = ROOT) -> bool:
    """Önizlemeler doğrulanınca insan 'Tasarım onayı' kapısı eklenir (bir kez). Ret notunda geçen önizleme yeniden yapılır (insan_onayi)."""
    if durum.get("onay_gorevi"):
        return False
    onz = [t for s in board["sprints"] if s["id"] in durum.get("sprintler_onizleme", []) for t in s["tasks"]]
    if not onz:
        return False
    kapi = {"title": "Tasarım onayı", "role": "human", "phase": "test",
            "description": ("İNSAN KAPISI: tasarım önizlemelerini incele (panel → Onaylar). Onay → faz planlama ve kodlama başlar. Ret (gerekçeli) → notta düzeltilmesi gereken "
                            "dosya adını/görev kimliğini yaz (örn. '07-teams-health.html: filtre barı bozuk'); yalnız o önizleme yeniden yapılır, notta eşleşme yoksa hepsi. "
                            f"İncele: {ONIZLEME_DIZIN}/"),
            "outputs": [ONAY], "depends_on": [t["id"] for t in onz]}
    ids = _gorev_ekle(board, "Tasarım onayı", "Önizlemeler insan tarafından onaylanır; onaylanmadan plan/kodlama başlamaz", [kapi])
    gid = next(t["id"] for s in board["sprints"] if s["id"] == ids[0] for t in s["tasks"])
    durum["onay_gorevi"], durum["sprint_onay"] = gid, ids[0]
    durum_yaz(durum, kok)
    B.audit("engine", "tasarim_onayi_eklendi", detay={"gorev": gid})
    B.refresh(board)
    return True


def _onizleme_bekliyor(board: dict, durum: dict) -> bool:
    gorevler = [t for s in board["sprints"] if s["id"] in durum.get("sprintler_onizleme", []) for t in s["tasks"]]
    return bool(gorevler) and any(t["status"] not in B.TERMINAL for t in gorevler)


def _onizleme_dogrula(board: dict, durum: dict, kok: Path = ROOT) -> bool:
    """Önizleme görevleri bitince çıktıları doğrular; geçersizi yeniden açar (≤TEKRAR_SINIRI). Panoyu değiştirdiyse True."""
    gorevler = [t for s in board["sprints"] if s["id"] in durum.get("sprintler_onizleme", []) for t in s["tasks"]]
    if not gorevler or any(t["status"] not in B.TERMINAL for t in gorevler):
        return False
    tekrar = durum.setdefault("tekrar", {})
    yeniden = 0
    gecersiz = []
    for t in gorevler:
        e = onizleme_eksikleri(kok / t["outputs"][0])
        if not e:
            continue
        k = f"onz:{t['id']}"
        if tekrar.get(k, 0) >= TEKRAR_SINIRI:
            gecersiz.append(t["outputs"][0])
            continue
        tekrar[k] = tekrar.get(k, 0) + 1
        t["description"] = re.sub(r"\n\nGEÇERSİZ ÖNİZLEME:.*$", "", t["description"], flags=re.S) + "\n\nGEÇERSİZ ÖNİZLEME: " + "; ".join(e) + " — düzeltip dosyayı yeniden yaz."
        B.mark(board, t["id"], B.TODO, "önizleme geçersiz: " + e[0])
        yeniden += 1
    if yeniden:
        durum_yaz(durum, kok)
        B.refresh(board)
        return True
    durum["onizleme_dogrulandi"] = True
    durum["onizleme_gecersiz"] = gecersiz
    durum_yaz(durum, kok)
    B.audit("engine", "envanter_onizleme_dogrulandi", detay={"gecersiz": len(gecersiz)})
    return True


def kontrol(board: dict, org: dict | None = None, cfg: dict | None = None, kok: Path = ROOT) -> bool:
    """Her koşucu turunda: aşamaları ilerletir. Panoyu değiştirdiyse True."""
    durum = durum_oku(kok)
    asama = durum.get("asama")
    if asama is None:
        return False
    degisti = False
    if asama in ("plan", "tamam") and "sprintler_onizleme" not in durum and "sprintler_tasarim" in durum:      # tasarımı önizlemesiz bitmiş projeye telafi
        degisti = _onizleme_ekle(board, cfg or {}, durum, kok) or degisti
    if durum.get("onizleme_dogrulandi") and _onizleme_bekliyor(board, durum):          # revizyon: yeniden yapılan önizleme tekrar doğrulanır
        durum["onizleme_dogrulandi"] = False
        durum_yaz(durum, kok)
        degisti = True
    if durum.get("sprintler_onizleme") and not durum.get("onizleme_dogrulandi"):
        degisti = _onizleme_dogrula(board, durum, kok) or degisti
    if asama == "tamam":
        return degisti
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
        kurtarilan = cikti_kurtar(kok)
        if kurtarilan:
            B.audit("engine", "envanter_cikti_kurtarildi", detay={"birimler": kurtarilan})
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
        if eksik_toplam:                                                    # envanteri çıkmayan birim için tasarım/önizleme açılmaz; kapsam denetimi bulur (#301)
            (kok / DIZIN / "_eksikler.md").write_text("# Envanteri çıkarılamayan birimler\n\n" + "\n".join(f"- `{i}`: {', '.join(e[:2])}" for i, e in sorted(eksik_toplam.items())) + "\n", encoding="utf-8")
        sablon, tasarim = _tasarim_gorevleri([b for b in birimler if b["id"] not in eksik_toplam], cfg)
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
        _onizleme_ekle(board, cfg or {}, durum, kok)
        B.audit("engine", "envanter_tamamlandi", detay={"birim": len(birimler), "eksik": len(eksik_toplam), "tasarim_gorevi": len(tasarim) + 1})
        B.refresh(board)
        return True
    if asama == "tasarim":
        gorevler = [t for s in board["sprints"] if s["id"] in durum.get("sprintler_tasarim", []) for t in s["tasks"]]
        if not gorevler or any(t["status"] not in B.TERMINAL for t in gorevler):
            return degisti
        if durum.get("sprintler_onizleme") and not durum.get("onizleme_dogrulandi"):         # plan, önizlemeler doğrulanınca başlar
            return degisti
        if durum.get("onizleme_dogrulandi") and onay_acik(cfg):                                # plan, insan tasarım onayından sonra başlar
            if _onay_ekle(board, durum, kok):
                degisti = True
            gid = durum.get("onay_gorevi")
            _, kapi = _task_sprint(board, gid) if gid else (None, None)
            if kapi is not None and kapi["status"] != B.DONE:
                return degisti
        try:
            import faz_planla as FP
            if modul_fazlari_acik(cfg) and not durum.get("fazlar_kuruldu"):
                durum["fazlar_kuruldu"] = modul_fazlarini_kur(cfg, kok)
                durum_yaz(durum, kok)
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


def faz_yeniden_kur(board: dict, org: dict | None, cfg: dict, kok: Path = ROOT) -> tuple[bool, str]:
    """Mevcut projede genel fazı/planı geri alıp modül fazlarını kurar; ilk fazın planlamasını başlatır (#303). Koşucu DURMUŞ olmalı. Envanter/tasarım/önizleme korunur."""
    import faz_planla as FP
    import karar_verici_triage as KVT
    for f in KVT.load_fazlar().get("fazlar", []):
        if FP.plan_yolu(f["id"], kok).exists() or FP.uygulandi_yolu(f["id"], kok).exists() or FP._planlama_gorevleri(board, f["id"])[0] is not None:
            ok, msg = FP.plani_geri_al(board, f["id"], kok)
            if not ok:
                return False, msg
    ids = modul_fazlarini_kur(cfg, kok)
    if not ids:
        return False, "modül fazları kurulamadı (rota listesi yok/geçersiz)"
    durum = durum_oku(kok)
    durum.update(fazlar_kuruldu=ids, asama="plan")
    sid = FP.tetikle(board, org or {}, cfg, zorla=ids[0], kok=kok)
    durum["plan_sprinti"] = sid
    durum_yaz(durum, kok)
    B.refresh(board)
    B.save(board)
    return True, f"{len(ids)} faz kuruldu; {ids[0]} planlaması {sid} olarak eklendi"


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Envanter aşaması yardımcıları")
    ap.add_argument("--faz-yeniden-kur", action="store_true", help="genel fazı/planı geri al, envanterden modül fazlarını kur (koşucu durmuş olmalı)")
    ap.add_argument("--faz-onizle", action="store_true", help="modül fazlarını yazmadan listele")
    a = ap.parse_args(argv)
    import studio_config as C
    cfg = C.load_config(ROOT / "workspace/studio.config.json") or {}
    if a.faz_onizle:
        birimler, errs = rota_oku(cfg, ROOT)
        if errs:
            print("rota listesi okunamadı:", errs[:3])
            return 1
        brief = ""
        for yol in (ROOT / "workspace/docs/proje_kapsami.md", ROOT / "proje_kapsami.md"):
            if yol.exists():
                brief = yol.read_text(encoding="utf-8")
                break
        for i, g in enumerate(faz_grupla(birimler, cfg, brief), 1):
            print(f"FAZ-{i}: {g['ad']} — {len(g['birimler'])} birim")
        return 0
    if a.faz_yeniden_kur:
        try:
            import servis_kapat as SK
            if SK.kosucu_pid():
                print("[HATA] koşucu çalışıyor; önce ./basla.sh --durdur (pano bellekte ezilmesin)")
                return 1
        except ImportError:
            pass
        org_yol = ROOT / "workspace/docs/org_chart.json"
        org = json.loads((org_yol if org_yol.exists() else ROOT / "org_chart.json").read_text(encoding="utf-8"))
        ok, msg = faz_yeniden_kur(B.load(), org, cfg, ROOT)
        print(("✓ " if ok else "[HATA] ") + msg)
        return 0 if ok else 1
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
