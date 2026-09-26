#!/usr/bin/env python3
"""
Digital Software Studio — Web Arayüzü (sıfır bağımlılık, saf stdlib)

    python studio_web.py [--port 8080] [--host 127.0.0.1]
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
    STUDIO_WEB_PORT  (varsayılan 8080)
"""

import argparse
import json
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
    }
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
        org = read_json(ROOT / "org_chart.json", {"hierarchy": []})
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
    f = TRACE / "current.out"
    if f.exists():
        try:
            txt = f.read_text(encoding="utf-8", errors="replace")[-12000:]
        except Exception:
            pass
    return {"meta": meta, "out": txt}


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
    if aks in ("atla", "gec"):
        tid = (body.get("gorev") or "").strip()
        if not tid:
            board = B.load()
            _, run = B.find_running(board)
            _, nxt = B.next_ready(board)
            tid = (run or nxt or {}).get("id") if (run or nxt) else None
        if not tid:
            return {"ok": False, "mesaj": "Hedef görev bulunamadı."}
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
                    if t["status"] in (B.FAILED, B.BLOCKED)
                    and (not tid or t["id"] == tid)]
        if not hedefler:
            return {"ok": False, "mesaj": "Başarısız/bloke görev yok."}
        for t in hedefler:
            t["status"] = B.TODO
            t["note"] = ""
        B.refresh(board)
        B.save(board)
        B.request("reload", kaynak="web")
        B.audit("web", "gorev_tekrar", detay={"adet": len(hedefler)})
        return {"ok": True, "mesaj": f"{len(hedefler)} görev tekrar sıraya alındı."}
    if aks == "onayla":
        g = body.get("gorev_kota")
        b = body.get("butce")
        d = B.ledger_approve(gorev=int(g) if g else None,
                             butce=float(b) if b else None)
        return {"ok": True,
                "mesaj": f"Ek kota tanındı: {d['gorev']} görev, ${d['maliyet']:.2f} harcandı."}
    return {"ok": False, "mesaj": f"Bilinmeyen aksiyon: {aks}"}


class Handler(BaseHTTPRequestHandler):
    server_version = "StudioWeb/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("[web] %s - %s\n" % (self.address_string(), fmt % args))

    # ------------------------------------------------ yardımcılar
    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
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
                                   "talepler": MTC.musteri_talepleri()})
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
    def do_POST(self):
        u = urlparse(self.path)
        path = u.path
        body = self._body()

        if path == "/api/kontrol":
            try:
                return self._json(kontrol(body))
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
            except Exception as e:
                return self._json({"ok": False, "mesaj": str(e)}, 400)

        return self._json({"ok": False, "mesaj": "bulunamadı"}, 404)


def main():
    ap = argparse.ArgumentParser(description="Studio web arayüzü")
    import os
    ap.add_argument("--host", default=os.getenv("STUDIO_WEB_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int,
                    default=int(os.getenv("STUDIO_WEB_PORT", "8080")))
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
