#!/usr/bin/env python3
"""
Digital Software Studio — Web Arayüzü (sıfır bağımlılık, saf stdlib)

    python studio_web.py [--port 8090] [--host 127.0.0.1]
    ./basla.sh --web

Ekranlar:
    /          Karşılama (Stüdyo Paneli | Müşteri Odası)
    /panel     Yönetim paneli: canlı pano, kontroller, audit + işlem logları
    /musteri   Müşteri sohbet odası: diyalogla talep netleştirme → onay

Teknik: http.server + ThreadingHTTPServer. Web varlıkları web/ altında,
durum tek doğruluk kaynağı studio.db'dir. Kontrol komutları mevcut
workspace/.control/ bayrak mekanizmasına yazılır — motora dokunmaz.

Ortam değişkenleri:
    STUDIO_WEB_HOST  (varsayılan 127.0.0.1 — IoT/LAN erişimi için 0.0.0.0)
    STUDIO_WEB_PORT  (varsayılan 8090)
"""

import argparse
import json
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import studio_board as B

WEB_DIR = ROOT / "web"
TRACE = ROOT / "workspace" / ".trace"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def read_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def runner_alive() -> bool:
    lock = ROOT / "workspace" / ".lock"
    try:
        import os
        os.kill(int(lock.read_text(encoding="utf-8").strip()), 0)
        return True
    except (OSError, ValueError):
        return False


def durum_ozeti() -> dict:
    ctrl = B.control_state()
    kosucu = runner_alive()
    cur = read_json(TRACE / "current.json", {})
    # current.json ölen/yarım kalan bir çağrıdan kalma bayat meta taşıyabilir;
    # koşucu yoksa 'şu an yapılan' gibi gösterilmesin.
    if cur.get("role") and not kosucu:
        yas = time.time() - (cur.get("started_at") or 0)
        if yas > 600:
            cur = {}
    if cur.get("role"):
        out_f = TRACE / "current.out"
        try:
            cur["son_aktivite"] = out_f.stat().st_mtime
        except OSError:
            pass
    out = {
        "zaman": time.strftime("%H:%M:%S"),
        "kosucu": kosucu,
        "duraklatildi": ctrl["paused"],
        "durduruluyor": ctrl["stopping"],
        "aktif": cur,
        "kota": B.ledger_read(),
        "kota_sinir": dict(zip(("gorev", "butce"), B.ledger_limits())),
        "canli": B.live_status(),
        "pano": None,
        "asama": "sprint",
        "studio_guncelleme": None,
        "motor_oneri": None,
        "motor_override": [],
        "onay_bekliyor": None,
    }
    try:
        ob = B.value_of("onay_bekliyor")
        if ob:
            out["onay_bekliyor"] = json.loads(ob)
    except Exception:
        pass
    try:
        out["motor_oneri"] = B.motor_oneri_oku()
        out["motor_override"] = B.motor_list()
    except Exception:
        pass
    try:
        out["studio_guncelleme"] = B.framework_update_info()
    except Exception:
        pass
    try:
        board = B.load()
        p = B.progress(board)
        out["pano"] = p
        out["kayma_gun"] = B.slip_days(board)
        _, run = B.find_running(board)
        _, nxt = B.next_ready(board)
        out["kosan_gorev"] = run and {"id": run["id"], "title": run.get("title", "")}
        out["sira"] = nxt and {"id": nxt["id"], "title": nxt.get("title", "")}
    except Exception:
        # Pano yoksa tasarım aşamasındadır
        out["asama"] = "tasarim"
        state = read_json(ROOT / "workspace" / ".state.json", {})
        org_f = ROOT / "workspace" / "docs" / "org_chart.json"
        if not org_f.exists():
            org_f = ROOT / "org_chart.json"
        org = read_json(org_f, {"hierarchy": []})
        design = [a for a in org["hierarchy"] if a.get("stage", "design") == "design"]
        done = set(state.get("completed_steps", []))
        out["tasarim"] = {
            "toplam": len(design),
            "biten": len(done & {a["id"] for a in design}),
        }
    return out


def canli() -> dict:
    meta = read_json(TRACE / "current.json", {})
    txt = ""
    son_aktivite = None
    f = TRACE / "current.out"
    if f.exists():
        try:
            # current.out her canlı satırda güncellenir; mtime'ı çağrının
            # son aktivite damgasıdır (sessizlik = model düşünüyor/takıldı).
            son_aktivite = f.stat().st_mtime
            txt = f.read_text(encoding="utf-8", errors="replace")[-12000:]
        except Exception:
            pass
    return {"meta": meta, "out": txt, "son_aktivite": son_aktivite}


def cagri_listesi() -> list:
    f = TRACE / "index.jsonl"
    out = []
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out[::-1]


def cagri_detay(seq: int) -> dict | None:
    f = TRACE / f"{int(seq):04d}.json"
    if not f.exists():
        return None
    rec = read_json(f, None)
    if not rec:
        return None
    for k in ("system_prompt", "user_prompt", "response"):
        v = rec.get(k) or ""
        if len(v) > 120_000:
            rec[k] = v[:120_000] + f"\n\n... [{len(v):,} karakter, kırpıldı]"
    return rec


def _io():
    """scripts/insan_onayi.py (onay mantığı CLI ile ortak)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import insan_onayi as IO
    return IO


_INCELE_RX = re.compile(r"İncele:\s*([^\n]+)")
_BILINMIYOR_RX = re.compile(r"(?mi)^\s*bilinmiyor\s*$")


def _incele_yollari(aciklama: str) -> list[str]:
    """Kapı açıklamasındaki `İncele: yol1, yol2` satırı (dosya ya da dizin; dizin .md/.html dosyalarına açılır)."""
    out: list[str] = []
    kok = ROOT.resolve()
    for m in _INCELE_RX.finditer(aciklama or ""):
        for y in m.group(1).split(","):
            y = y.strip().strip("`").rstrip(".")
            if not y:
                continue
            p = (ROOT / y).resolve()
            try:
                p.relative_to((ROOT / "workspace").resolve())
            except ValueError:
                continue
            if p.is_dir():
                out += [str(f.resolve().relative_to(kok)) for f in sorted(p.rglob("*")) if f.suffix in (".md", ".html") and f.is_file() and not f.name.startswith("_")][:60]
            elif p.is_file() or "*" in y:
                if "*" in y:
                    out += [str(f.resolve().relative_to(kok)) for f in sorted(ROOT.glob(y)) if f.is_file()][:60]
                else:
                    out.append(y)
    return out


def _dosya_meta(yol: str) -> dict:
    p = ROOT / yol
    m = {"yol": yol, "tur": p.suffix.lstrip("."), "var": p.is_file(), "kb": 0, "bilinmiyor": 0, "varsayim": 0, "okunamadi": False}
    if p.is_file():
        m["kb"] = round(p.stat().st_size / 1024, 1)
        if p.suffix == ".md":
            metin = p.read_text(encoding="utf-8", errors="replace")
            m["bilinmiyor"] = len(_BILINMIYOR_RX.findall(metin))
            satirlar = [ln.strip() for ln in metin.splitlines() if ln.strip().startswith(">") and "Varsayım" in ln]
            m["varsayim"] = len(satirlar)
            # Doküman girdilerin okunamadığını beyan ediyorsa: tahminle yazılmıştır, onaydan önce uyarı gösterilir
            m["okunamadi"] = any(re.search(r"okunamad[ıi]|okuma izni|okuyamad[ıi]m|erişemedim", ln, re.I) for ln in satirlar)
    return m


def _aciklama_temiz(a: str) -> str:
    """Panelde gösterilecek açıklama: İncele: satırı ve komut satırı ipuçları çıkarılır."""
    a = _INCELE_RX.sub("", a or "")
    a = re.sub(r"`python3 scripts/[^`]*`", "", a)
    a = re.sub(r"\(ya da\s*\)|\(\s*\)", "", a)
    a = re.sub(r"^\s*İNSAN KAPISI\.?\s*", "", a)
    return re.sub(r"\s{2,}", " ", a).strip()


def onaylar() -> dict:
    """İnsan onay kapıları: bekleyenler önce. Her kapı için: ne incelenecek, onaylanırsa/reddedilirse ne olacak."""
    IO = _io()
    try:
        board = B.load()
    except FileNotFoundError:
        return {"ok": False, "mesaj": "Pano henüz yok.", "onaylar": []}
    B.refresh(board)
    tum = {t["id"]: t for _, t in B.all_tasks(board)}
    bagli: dict[str, list] = {}
    for _, t in B.all_tasks(board):
        for d in t.get("depends_on", []):
            bagli.setdefault(d, []).append(t)
    out = []
    for sp, t in B.all_tasks(board):
        if not B.is_human(t):
            continue
        deps = [tum[d] for d in t.get("depends_on", []) if d in tum]
        yollar: list[str] = []
        for y in [o for d in deps for o in d.get("outputs", []) if o.endswith((".md", ".html", ".json", ".txt"))] + _incele_yollari(t.get("description", "")):
            if y not in yollar:
                yollar.append(y)
        dosyalar = [_dosya_meta(y) for y in yollar]
        gorseller = []                                   # ekran dokümanına karşılık gelen referans ekran görüntüleri (_gorsel/<ad>.png)
        for y in yollar:
            pp = Path(y)
            if pp.suffix == ".md" and "ekranlar" in pp.parts:
                png = Path(*pp.parts[:pp.parts.index("ekranlar") + 1]) / "_gorsel" / (pp.stem + ".png")
                if (ROOT / png).is_file():
                    gorseller.append({"yol": str(png), "ad": pp.stem})
        yol = IO.kayit_yolu(t)
        kayit = yol.read_text(encoding="utf-8", errors="replace")[-900:] if yol.exists() else ""
        etki, gor, kuyruk = [], {t["id"]}, [t["id"]]          # onaylanınca zincirleme başlayacak görevler (dolaylı bağımlılar dahil)
        while kuyruk:
            for x in bagli.get(kuyruk.pop(0), []):
                if x["id"] not in gor and not B.is_human(x):
                    gor.add(x["id"])
                    kuyruk.append(x["id"])
                    etki.append({"id": x["id"], "baslik": x["title"], "rol": x["role"], "ciktilar": x.get("outputs", []), "durum": x["status"]})
        out.append({"id": t["id"], "sprint": sp["id"], "baslik": t["title"], "aciklama": _aciklama_temiz(t.get("description", "")),
                    "durum": t["status"], "bagimliliklar": [{"id": d["id"], "baslik": d["title"], "rol": d["role"], "durum": d["status"]} for d in deps],
                    "dosyalar": dosyalar, "gorseller": gorseller, "incele": yollar, "kayit": kayit, "not": t.get("note", ""),
                    "onaylanirsa": etki,
                    "reddedilirse": [{"id": d["id"], "baslik": d["title"], "rol": d["role"]} for d in deps]})
    sira = {"READY": 0, "TODO": 1, "DONE": 2}
    out.sort(key=lambda x: (sira.get(x["durum"], 1), x["sprint"], x["id"]))
    return {"ok": True, "onaylar": out, "bekleyen": sum(1 for x in out if x["durum"] == "READY")}


def onay_dosya(yol: str) -> dict:
    """Panelde gösterilecek doküman: yalnız workspace/ altında .md/.html/.json/.txt (yol kaçışı engellenir)."""
    p = (ROOT / yol).resolve()
    try:
        p.relative_to((ROOT / "workspace").resolve())
    except ValueError:
        return {"ok": False, "mesaj": "yalnız workspace/ altındaki dosyalar görüntülenir"}
    if p.suffix not in (".md", ".html", ".json", ".txt") or not p.is_file():
        return {"ok": False, "mesaj": "dosya yok veya desteklenmeyen tür"}
    return {"ok": True, "yol": yol, "tur": p.suffix.lstrip("."), "icerik": p.read_text(encoding="utf-8", errors="replace")[:400_000]}


_GORSEL_TURLERI = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}   # svg bilinçli yok (betik taşıyabilir)
_DOK_TURLERI = {".md", ".html", ".json", ".txt"} | set(_GORSEL_TURLERI)
_DOK_ATLA = {"_ham", "node_modules", ".git"}


def html_ham(yol: str):
    """Yeni sekmede açılacak HTML doküman: yalnız workspace/ altında .html. (bayt, hata) döndürür."""
    p = (ROOT / yol).resolve()
    try:
        p.relative_to((ROOT / "workspace").resolve())
    except ValueError:
        return None, "yalnız workspace/ altı"
    if p.suffix.lower() != ".html" or not p.is_file():
        return None, "html doküman yok"
    return p.read_bytes(), ""


# Yeni sekmede açılan üretilmiş HTML: betik çalışabilir ama panel origin'ine/API'sine erişemez (opak origin), form/üst gezinme yok.
HTML_CSP = "sandbox allow-scripts allow-popups; default-src 'self' data: blob: 'unsafe-inline' 'unsafe-eval'; connect-src 'none'; form-action 'none'"


def gorsel_oku(yol: str):
    """Görsel: yalnız workspace/ altında png/jpg/gif/webp. (bayt, mime, hata) döndürür."""
    p = (ROOT / yol).resolve()
    try:
        p.relative_to((ROOT / "workspace").resolve())
    except ValueError:
        return None, "", "yalnız workspace/ altı"
    if p.suffix.lower() not in _GORSEL_TURLERI or not p.is_file():
        return None, "", "görsel yok"
    return p.read_bytes(), _GORSEL_TURLERI[p.suffix.lower()], ""


def dokumanlar(taban: str = "workspace/docs") -> dict:
    """Panel 'Dokümanlar' sekmesi: workspace/docs altındaki üretilmiş doküman ve görsellerin düz listesi (salt-okuma)."""
    kok = (ROOT / "workspace").resolve()
    dizin = (ROOT / taban).resolve()
    try:
        dizin.relative_to(kok)
    except ValueError:
        return {"ok": False, "mesaj": "yalnız workspace/ altı", "dosyalar": []}
    out = []
    if dizin.is_dir():
        for f in sorted(dizin.rglob("*")):
            if len(out) >= 4000:
                break
            if not f.is_file() or f.suffix.lower() not in _DOK_TURLERI or any(x in _DOK_ATLA for x in f.relative_to(dizin).parts):
                continue
            out.append({"yol": f.relative_to(ROOT.resolve()).as_posix(), "tur": f.suffix.lower().lstrip("."), "kb": round(f.stat().st_size / 1024, 1),
                        "zaman": int(f.stat().st_mtime)})
    return {"ok": True, "taban": taban, "dosyalar": out}


def _yo():
    sys.path.insert(0, str(ROOT / "scripts"))
    import yerel_ortam_yonet as YO
    return YO


def _profil(v) -> str:
    return v if v in ("yerel_ortam", "onizleme") else "yerel_ortam"


def ortam_ozet(profil: str = "yerel_ortam") -> dict:
    YO = _yo()
    profil = _profil(profil)
    return {"ok": True, **YO.durum(ROOT, profil=profil), "log": YO.log_oku(ROOT, profil=profil)}


def ortam_islem(body: dict) -> dict:
    YO = _yo()
    islem = (body.get("islem") or "").strip()
    profil = _profil(body.get("profil"))
    f = {"baslat": YO.baslat, "durdur": YO.durdur, "yeniden": YO.yeniden}.get(islem)
    return f(ROOT, profil=profil) if f else {"ok": False, "mesaj": "bilinmeyen işlem"}


def _bg():
    sys.path.insert(0, str(ROOT / "scripts"))
    import brief_gorusme as BG
    return BG


def brief_islem(body: dict) -> dict:
    """Brief görüşmesi: islem = soru | cevap | bitir | sifirla."""
    BG = _bg()
    islem = body.get("islem")
    if islem == "soru":
        return {"ok": True, **BG.soru_uret()}
    if islem == "cevap":
        return BG.cevapla(str(body.get("cevap") or ""))
    if islem == "bitir":
        return BG.bitir()
    if islem == "sifirla":
        return BG.sifirla()
    return {"ok": False, "mesaj": "bilinmeyen işlem"}


def onay_ver(body: dict) -> dict:
    IO = _io()
    karar = body.get("karar")
    board = B.load()
    B.refresh(board)
    ok, msg = IO.karar_ver(board, (body.get("id") or "").strip(), karar, (body.get("not") or "").strip(),
                           (body.get("kim") or "").strip() or None)
    if ok:
        B.request("reload", kaynak="web")
    return {"ok": ok, "mesaj": msg}


def kontrol(body: dict) -> dict:
    aks = body.get("aksiyon", "")
    if aks == "duraklat":
        B.request("pause", kaynak="web")
        return {"ok": True, "mesaj": "Duraklatıldı — çalışan çağrı bitince yeni görev alınmaz."}
    if aks == "surdur":
        B.clear("pause")
        B.audit("web", "kontrol_surdur")
        return {"ok": True, "mesaj": "Sürdürüldü."}
    if aks == "durdur":
        B.request("stop", kaynak="web")
        return {"ok": True, "mesaj": "Durdurma istendi — mevcut çağrı bitince koşucu çıkar."}
    if aks == "acil_durdur":
        ok, msg = B.hard_stop()
        return {"ok": ok, "mesaj": msg}
    if aks in ("atla", "gec"):
        tid = (body.get("gorev") or "").strip()
        board = B.load()
        if not tid:
            _, run = B.find_running(board)
            _, nxt = B.next_ready(board)
            tid = (run or nxt or {}).get("id") if (run or nxt) else None
        if not tid:
            return {"ok": False, "mesaj": "Hedef görev bulunamadı."}

        # Sprint id verildiyse (örn. "S33") toplu işlem uygula
        spr = next((s for s in board.get("sprints", [])
                    if s.get("id") == tid), None)
        if spr is not None:
            acik = [t for t in spr.get("tasks", [])
                    if t.get("status") not in B.TERMINAL]
            if not acik:
                return {"ok": False, "mesaj": f"{tid} zaten tamamen kapalı."}
            if aks == "atla":
                sys.path.insert(0, str(ROOT / "scripts"))
                import musteri_talepleri as MT
                for t in acik:
                    if t["status"] == B.RUNNING:
                        B.request("skip", t["id"], kaynak="web")
                    else:
                        t["status"] = B.SKIPPED
                        t["note"] = "kullanıcı sprinti atladı"
                        if t.get("talep_id"):
                            MT.talep_beklemeye_al(t["talep_id"], t["id"])
                B.refresh(board)
                B.save(board)
                if body.get("force"):
                    B.request("force", kaynak="web")
                B.audit("web", "sprint_atla",
                        detay={"sprint": tid, "adet": len(acik)})
                ek = " (çağrı anında kesiliyor)" if body.get("force") else ""
                return {"ok": True,
                        "mesaj": f"{tid}: {len(acik)} görev atlandı{ek}."}
            # gec: sprintin ilk açık görevini hedefle
            tid = acik[0]["id"]

        flag = "skip" if aks == "atla" else "goto"
        B.request(flag, tid, kaynak="web")
        if body.get("force"):
            B.request("force", kaynak="web")
            return {"ok": True, "mesaj": f"{tid}: çağrı hemen kesilip {aks} uygulanacak."}
        return {"ok": True, "mesaj": f"{tid}: mevcut çağrı bitince {aks} uygulanacak."}
    if aks == "tekrar":
        board = B.load()
        tid = (body.get("gorev") or "").strip()
        hedefler = [t for _, t in B.all_tasks(board)
                    if t["status"] in (B.FAILED, B.BLOCKED, B.SKIPPED)
                    and (not tid or t["id"] == tid)]
        if not hedefler:
            return {"ok": False, "mesaj": "Başarısız/bloke/atlanmış görev yok."}
        for t in hedefler:
            t["status"] = B.TODO
            t["note"] = ""
        B.refresh(board)
        B.save(board)
        B.request("reload", kaynak="web")
        B.audit("web", "gorev_tekrar", detay={"adet": len(hedefler)})
        return {"ok": True, "mesaj": f"{len(hedefler)} görev tekrar sıraya alındı."}
    if aks == "motor":
        hedef = (body.get("hedef") or "").strip()
        ok, msg = B.set_motor(hedef, body.get("backend") or None,
                              body.get("model") or None,
                              body.get("effort") or None)
        if ok:
            B.request("reload", kaynak="web")
        return {"ok": ok, "mesaj": msg}
    if aks == "motor_temizle":
        hedef = (body.get("hedef") or "").strip()
        ok, msg = B.clear_motor(hedef)
        if ok:
            B.request("reload", kaynak="web")
        return {"ok": ok, "mesaj": msg}
    if aks == "talep_iptal":
        tid = (body.get("talep_id") or "").strip()
        try:
            import musteri_talepleri as MT
            t = MT.talep_iptal(tid, sebep=(body.get("sebep") or ""))
        except Exception as e:
            return {"ok": False, "mesaj": f"Talep modülü: {e}"}
        if t:
            B.request("reload", kaynak="web")
            pano = t.get("_pano") or {}
            ek = (f" · {len(pano['silinen'])} pano görevi kaldırıldı"
                  if pano.get("silinen") else "")
            ek += (f" · {len(pano['kosan'])} koşan görev atlanıyor"
                   if pano.get("kosan") else "")
            return {"ok": True, "mesaj": f"{tid} iptal edildi.{ek}"}
        return {"ok": False, "mesaj": f"{tid} bulunamadı veya zaten kapalı."}
    if aks == "talep_onayla":
        # DEGERLENDIRMEDE/FAZ_BEKLIYOR/IPTAL talebi aktif faz kapsamında
        # PLANLANDI'ya çeker; bir sonraki pano senkronunda sprint görevi
        # olarak eklenir. IPTAL → yeniden devreye alma anlamı taşır.
        tid = (body.get("talep_id") or "").strip()
        try:
            import musteri_talepleri as MT
            t = MT.getir(tid)
            if not t:
                return {"ok": False, "mesaj": f"{tid} bulunamadı."}
            eski = t.get("durum")
            if eski not in ("DEGERLENDIRMEDE", "FAZ_BEKLIYOR",
                            "BEKLEMEDE", "IPTAL"):
                return {"ok": False,
                        "mesaj": f"{tid} zaten {eski} durumda."}
            try:
                sys.path.insert(0, str(ROOT / "scripts"))
                import karar_verici_triage as KVT
                faz = KVT.aktif_faz_getir().get("id", "FAZ-1")
            except Exception:
                faz = "FAZ-1"
            MT.guncelle(
                tid, durum="PLANLANDI",
                studio_notu=("Panelden yeniden devreye alındı" if eski == "IPTAL"
                             else "Panelden sprint onayı verildi")
                + f" ({faz}).")
            B.request("reload", kaynak="web")
            B.audit("web", "talep_onay", talep_id=tid,
                    detay={"faz": faz, "onceki_durum": eski})
            ek = "yeniden devreye alındı" if eski == "IPTAL" else "sprint onayı alındı"
            return {"ok": True,
                    "mesaj": f"{tid} {ek} ({faz}); sonraki boş turda panoya eklenecek."}
        except Exception as e:
            return {"ok": False, "mesaj": f"Talep modülü: {e}"}
    if aks == "talep_cozum":
        # ONAY_BEKLIYOR talebi için müşteri kararı:
        #   sonuc=onayla → COZULDU (GitHub issue otomatik kapanır)
        #   sonuc=reddet → BEKLEMEDE (kuyruğa geri döner, yeniden sprinte girer)
        tid = (body.get("talep_id") or "").strip()
        sonuc = (body.get("sonuc") or "").strip()
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            import musteri_talepleri as MT
            t = MT.getir(tid)
            if not t:
                return {"ok": False, "mesaj": f"{tid} bulunamadı."}
            if t.get("durum") != "ONAY_BEKLIYOR":
                return {"ok": False,
                        "mesaj": f"{tid} onay beklemiyor ({t.get('durum')})."}
            if sonuc == "onayla":
                MT.guncelle(tid, durum="COZULDU",
                            studio_notu="Müşteri onayı ile kapatıldı.")
                B.request("reload", kaynak="web")
                B.audit("web", "talep_cozum_onay", talep_id=tid)
                return {"ok": True, "mesaj": f"{tid} çözüldü olarak kapatıldı."}
            if sonuc == "reddet":
                MT.guncelle(tid, durum="BEKLEMEDE",
                            studio_notu="Müşteri: sorun devam ediyor — talep kuyruğa geri alındı.")
                B.request("reload", kaynak="web")
                B.audit("web", "talep_cozum_red", talep_id=tid)
                return {"ok": True, "mesaj": f"{tid} tekrar kuyruğa alındı."}
            return {"ok": False, "mesaj": "sonuc 'onayla' veya 'reddet' olmalı."}
        except Exception as e:
            return {"ok": False, "mesaj": f"Talep modülü: {e}"}
    if aks == "faz_ilerlet":
        # Aktif fazı TAMAMLANDI yapıp sıradaki fazı AKTIF'e çeker; o faza
        # ait FAZ_BEKLIYOR talepler PLANLANDI olur. CLI'deki
        # `karar_verici_triage --faz-ilerlet` ile aynı iş.
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            import karar_verici_triage as KVT
            ok = KVT.faz_ilerlet()
        except Exception as e:
            return {"ok": False, "mesaj": f"Triage modülü: {e}"}
        if ok:
            B.request("reload", kaynak="web")
            B.audit("web", "faz_ilerlet")
            return {"ok": True,
                    "mesaj": "Faz ilerletildi; yeni faza ait bekleyen talepler planlandı."}
        return {"ok": False,
                "mesaj": "İlerletilecek faz yok (aktif faz son faz olabilir)."}
    if aks == "talep_faz":
        # Talebi başka bir faza taşır. Aktif faza taşınan talep PLANLANDI
        # olur; gelecek/kilitli faza taşınan FAZ_BEKLIYOR'da bekler.
        # Kapalı taleplere (COZULDU/IPTAL) dokunulmaz.
        tid = (body.get("talep_id") or "").strip()
        yeni_faz = (body.get("faz") or "").strip()
        try:
            sys.path.insert(0, str(ROOT / "scripts"))
            import karar_verici_triage as KVT
            import musteri_talepleri as MT
            t = MT.getir(tid)
            if not t:
                return {"ok": False, "mesaj": f"{tid} bulunamadı."}
            if t.get("durum") in ("COZULDU", "IPTAL"):
                return {"ok": False,
                        "mesaj": f"{tid} zaten kapalı ({t.get('durum')})."}
            fazlar = {f.get("id") for f in KVT.load_fazlar().get("fazlar", [])}
            if yeni_faz not in fazlar:
                return {"ok": False, "mesaj": f"Geçersiz faz: {yeni_faz or '-'}"}
            aktif = KVT.aktif_faz_getir().get("id", "FAZ-1")
            data = MT.load_data()
            for x in data.get("talepler", []):
                if x.get("id") == t["id"]:
                    x["faz_id"] = yeni_faz
                    if x.get("durum") in ("DEGERLENDIRMEDE", "FAZ_BEKLIYOR",
                                          "BEKLEMEDE", "PLANLANDI"):
                        x["durum"] = ("PLANLANDI" if yeni_faz == aktif
                                      else "FAZ_BEKLIYOR")
                    x.setdefault("gecmis", []).append({
                        "zaman": time.strftime("%Y-%m-%d %H:%M"),
                        "eylem": f"Panelden {yeni_faz} fazına taşındı",
                        "durum": x["durum"],
                    })
            MT.save_data(data)
            B.request("reload", kaynak="web")
            B.audit("web", "talep_faz", talep_id=tid, detay={"faz": yeni_faz})
            return {"ok": True,
                    "mesaj": f"{tid} → {yeni_faz} "
                             f"({'aktif faz' if yeni_faz == aktif else 'faz bekliyor'})."}
        except Exception as e:
            return {"ok": False, "mesaj": f"Talep modülü: {e}"}
    if aks == "onayla":
        g = body.get("gorev_kota")
        b = body.get("butce")
        d = B.ledger_approve(gorev=int(g) if g else None,
                             butce=float(b) if b else None)
        B.clear("onay_bekliyor")
        return {"ok": True,
                "mesaj": f"Ek kota tanındı: {d['gorev']} görev, ${d['maliyet']:.2f} harcandı."}
    return {"ok": False, "mesaj": f"Bilinmeyen aksiyon: {aks}"}


class Handler(BaseHTTPRequestHandler):
    server_version = "StudioWeb/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[web] %s - %s\n" % (self.address_string(), fmt % args))

    # ------------------------------------------------ yardımcılar
    def _send(self, code: int, body: bytes, ctype: str, ek_basliklar: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (ek_basliklar or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   MIME[".json"])

    def _html(self, name: str):
        f = WEB_DIR / name
        if not f.exists():
            self._send(404, b"sayfa bulunamadi", "text/plain; charset=utf-8")
            return
        self._send(200, f.read_bytes(), MIME[".html"])

    def _body(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > 2_000_000:
                return {}
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    # ------------------------------------------------ GET
    def do_GET(self):
        u = urlparse(self.path)
        path = u.path
        q = parse_qs(u.query)

        if path in ("/", "/index.html"):
            return self._html("index.html")
        if path == "/panel":
            return self._html("panel.html")
        if path == "/musteri":
            return self._html("musteri.html")
        if path.startswith("/web/"):
            return self._static(path[5:])

        if path == "/api/ozet":
            return self._json(durum_ozeti())
        if path == "/api/pano":
            try:
                return self._json({"ok": True, "pano": B.load()})
            except FileNotFoundError:
                return self._json({"ok": False, "mesaj": "Pano henüz yok."})
        if path == "/api/brief-gorusme":
            return self._json(_bg().ozet())
        if path == "/api/ortam":
            return self._json(ortam_ozet(q.get("profil", ["yerel_ortam"])[0]))
        if path == "/api/onaylar":
            return self._json(onaylar())
        if path == "/api/gorsel":
            veri, mime, hata = gorsel_oku(q.get("yol", [""])[0])
            if veri is None:
                return self._json({"ok": False, "mesaj": hata}, 404)
            return self._send(200, veri, mime)
        if path == "/api/dokuman-html":
            veri, hata = html_ham(q.get("yol", [""])[0])
            if veri is None:
                return self._json({"ok": False, "mesaj": hata}, 404)
            return self._send(200, veri, "text/html; charset=utf-8",
                              {"Content-Security-Policy": HTML_CSP, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})
        if path == "/api/dokumanlar":
            return self._json(dokumanlar())
        if path == "/api/onay-dosya":
            return self._json(onay_dosya(q.get("yol", [""])[0]))
        if path == "/api/canli":
            return self._json(canli())
        if path == "/api/audit":
            limit = int(q.get("limit", ["200"])[0] or 200)
            return self._json({"ok": True, "log": B.audit_list(
                limit=min(limit, 1000),
                kaynak=(q.get("kaynak", [""])[0] or None),
                olay=(q.get("olay", [""])[0] or None))})
        if path == "/api/cagri":
            return self._json({"ok": True, "cagrilar": cagri_listesi()})
        if path.startswith("/api/cagri/"):
            try:
                seq = int(path.rsplit("/", 1)[1])
            except ValueError:
                return self._json({"ok": False, "mesaj": "geçersiz seq"}, 400)
            rec = cagri_detay(seq)
            if rec is None:
                return self._json({"ok": False, "mesaj": "kayıt yok"}, 404)
            return self._json({"ok": True, "cagri": rec})
        if path == "/api/talepler":
            try:
                import musteri_talepleri as MT
                return self._json({"ok": True,
                                   "talepler": MT.load_data().get("talepler", [])})
            except Exception as e:
                return self._json({"ok": False, "mesaj": str(e)}, 500)
        if path == "/api/fazlar":
            try:
                import karar_verici_triage as KVT
                return self._json({"ok": True, "fazlar": KVT.load_fazlar()})
            except Exception as e:
                return self._json({"ok": False, "mesaj": str(e)}, 500)
        if path == "/api/sohbet":
            try:
                import musteri_temsilcisi as MTC
                oid = q.get("oturum", [""])[0]
                return self._json({"ok": True,
                                   "mesajlar": MTC.mesajlar(oid),
                                   "talepler": MTC.musteri_talepleri(),
                                   "motor": MTC.aktif_motor()})
            except Exception as e:
                return self._json({"ok": False, "mesaj": str(e)}, 500)

        return self._json({"ok": False, "mesaj": "bulunamadı"}, 404)

    def _static(self, rel: str):
        # Path traversal koruması: yalnızca web/ altı servis edilir.
        hedef = (WEB_DIR / rel).resolve()
        if not hedef.is_file() or WEB_DIR.resolve() not in hedef.parents:
            return self._send(404, b"yok", "text/plain; charset=utf-8")
        self._send(200, hedef.read_bytes(),
                   MIME.get(hedef.suffix, "application/octet-stream"))

    # ------------------------------------------------ POST
    def _yazma_guvenligi(self):
        """Yazma isteği yalnız aynı kaynaktan ve JSON gövdeyle kabul edilir; ihlalde yanıtı gönderir ve True döndürür (çağıran işlemeyi bırakmalı); yoksa None."""
        origin = self.headers.get("Origin")
        if origin and urlparse(origin).netloc != self.headers.get("Host", ""):
            self._json({"ok": False, "mesaj": "farklı kaynaktan istek reddedildi"}, 403)
            return True
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            self._json({"ok": False, "mesaj": "Content-Type application/json olmalı"}, 400)
            return True
        return None

    def do_POST(self):
        u = urlparse(self.path)
        path = u.path
        body = self._body()

        if path == "/api/kontrol":
            try:
                return self._json(kontrol(body))
            except Exception as e:
                return self._json({"ok": False, "mesaj": str(e)}, 500)

        if path == "/api/onay":
            # Yazma işlemi: yalnız aynı kaynaktan (panel sayfası) ve JSON gövdeyle kabul edilir.
            hata = self._yazma_guvenligi()
            if hata:
                return hata
            try:
                return self._json(onay_ver(body))
            except Exception as e:
                return self._json({"ok": False, "mesaj": str(e)}, 500)

        if path == "/api/ortam":
            hata = self._yazma_guvenligi()
            if hata:
                return hata
            try:
                return self._json(ortam_islem(body))
            except Exception as e:
                return self._json({"ok": False, "mesaj": str(e)}, 500)

        if path == "/api/brief-gorusme":
            hata = self._yazma_guvenligi()
            if hata:
                return hata
            try:
                return self._json(brief_islem(body))
            except Exception as e:
                return self._json({"ok": False, "mesaj": str(e)}, 500)

        if path == "/api/oncelik":
            tid = (body.get("gorev_id") or "").strip()
            try:
                val = int(body.get("oncelik", 0))
            except (TypeError, ValueError):
                return self._json({"ok": False, "mesaj": "geçersiz öncelik"}, 400)
            if not tid:
                return self._json({"ok": False, "mesaj": "gorev_id gerekli"}, 400)
            if B.set_priority(tid, val):
                B.request("reload", kaynak="web")
                return self._json({"ok": True,
                                   "mesaj": f"{tid} öncelik önerisi {val} olarak kaydedildi; "
                                            "sırayı framework bağımlılıklara göre belirler."})
            return self._json({"ok": False, "mesaj": f"{tid} bulunamadı."})

        if path.startswith("/api/sohbet/"):
            try:
                import musteri_temsilcisi as MTC
            except Exception as e:
                return self._json({"ok": False, "mesaj": f"sohbet modülü: {e}"}, 500)
            sub = path.rsplit("/", 1)[1]
            try:
                if sub == "yeni":
                    return self._json({"ok": True,
                                       "oturum_id": MTC.oturum_ac(
                                           body.get("musteri_adi", ""))})
                if sub == "mesaj":
                    return self._json({"ok": True,
                                       **MTC.mesaj_gonder(body.get("oturum"),
                                                          body.get("icerik", ""))})
                if sub == "onay":
                    return self._json({"ok": True,
                                       **MTC.taslak_onayla(body.get("oturum"),
                                                           int(body.get("mesaj_id", 0)))})
                if sub == "red":
                    return self._json({"ok": True,
                                       **MTC.taslak_reddet(body.get("oturum"),
                                                           int(body.get("mesaj_id", 0)))})
                if sub == "motor":
                    if body.get("temizle"):
                        ok, msg = B.clear_motor(MTC.SOHBET_HEDEF)
                        return self._json({"ok": True, "mesaj": msg,
                                           "motor": MTC.aktif_motor()})
                    ok, msg = B.set_motor(MTC.SOHBET_HEDEF,
                                          body.get("backend") or None,
                                          body.get("model") or None,
                                          body.get("effort") or None)
                    return self._json({"ok": ok, "mesaj": msg,
                                       "motor": MTC.aktif_motor()})
            except Exception as e:
                return self._json({"ok": False, "mesaj": str(e)}, 400)

        return self._json({"ok": False, "mesaj": "bulunamadı"}, 404)


def main():
    ap = argparse.ArgumentParser(description="Studio web arayüzü")
    import os
    ap.add_argument("--host", default=os.getenv("STUDIO_WEB_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int,
                    default=int(os.getenv("STUDIO_WEB_PORT", "8090")))
    args = ap.parse_args()

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"  🌐 Studio Web  →  http://{args.host}:{args.port}/")
    print(f"     Panel   : http://{args.host}:{args.port}/panel")
    print(f"     Müşteri : http://{args.host}:{args.port}/musteri")
    if args.host == "0.0.0.0":
        print("     ⚠ Tüm ağ arayüzlerine açık (LAN/IoT). Kimlik doğrulaması yoktur.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
