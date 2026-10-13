#!/usr/bin/env python3
"""Kapalı döngü onarım (issue #247): hata olunca kural yazmak yerine araçlı ajan çözer, motor aynı kapıyla doğrular.

İlke: kapılar yalnız SENSÖRdür (neyin kırıldığının kanıtı). Çözümü araçlı ajan bulur (dosyayı okur, düzenler, komut çalıştırır),
motor ajanın her turundan sonra AYNI kapıyı yeniden koşturur; geçerse biter, geçmezse yeni kanıtla bir tur daha.
Bu modül döngüyü, istemi ve kapı koşturucularını taşır; model çağrısı motordan enjekte edilir (test edilebilir).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Ajanın araçları: okuma serbest; yazma (Edit) yalnız workspace/ altı (Claude'un yerel izin kuralı, dışarısı reddedilir);
# komut çalıştırma (Bash) serbest AMA tehlikeli komutlar yasak ("!" öneki = --disallowedTools; yasak izne baskındır).
# Ek güvenlik: tur sonrası kapsam denetimi (workspace dışı değişiklik geri alınır) ve çerçeve dosyası bütünlük denetimi (aşağıda).
YASAK = [
    "!Bash(sudo:*)", "!Bash(su:*)", "!Bash(chmod:*)", "!Bash(chown:*)", "!Bash(dd:*)", "!Bash(mkfs:*)", "!Bash(shutdown:*)", "!Bash(reboot:*)",
    "!Bash(pkill:*)", "!Bash(killall:*)", "!Bash(launchctl:*)", "!Bash(osascript:*)", "!Bash(brew:*)",
    "!Bash(ssh:*)", "!Bash(scp:*)", "!Bash(rsync:*)",
    "!Bash(git push:*)", "!Bash(git reset:*)", "!Bash(git checkout:*)", "!Bash(git clean:*)", "!Bash(git rebase:*)", "!Bash(git config:*)",
    "!Bash(git remote:*)", "!Bash(git branch:*)", "!Bash(git stash:*)", "!Bash(git restore:*)",
    "!Bash(rm -rf /:*)", "!Bash(rm -rf ~:*)", "!Bash(rm -rf ..:*)", "!Bash(rm -rf .:*)",
    "!Bash(npm publish:*)", "!Bash(pnpm publish:*)", "!Bash(npm login:*)",
]
ARACLAR = ["Read", "Glob", "Grep", "Edit(workspace/**)", "Bash"] + YASAK
ETIKET_RX = re.compile(r"\[(RENDER|BUILD|UAT|HİJYEN|KAYNAK)\]")
TUR_VARSAYILAN = int(os.getenv("STUDIO_ONARIM_TUR", "3"))

SISTEM = """Sen deneyimli bir yazılım mühendisisin. Bu projede çalışan bir hatayı GİDERECEKSİN.
Otomatik bir boru hattında çalışıyorsun: karşında cevap verebilecek bir insan yok, soru sorma; makul varsayımla ilerle.
Elindeki araçlarla ilgili dosyaları OKU, nedeni KENDİN bul, dosyaları DOĞRUDAN DÜZENLE (Edit), komutları kendin çalıştırıp doğrula.
Kurallar:
- Dosyayı baştan yazma: yalnız gereken değişikliği yap; mevcut ayarları, import'ları ve çalışan kodu koru.
- Yalnız `workspace/` altında değişiklik yap (komut çalıştırırken de). Çerçeve dosyalarına (studio_*.py, scripts/, basla.sh, org_chart.json, studio.version) ve `workspace/studio.db`'ye dokunma; `workspace/.control`/`.trace` içine yazma.
- Uzun süren süreçleri (dev sunucu) başlatma/öldürme: motor ortamı senin için yönetir. Komutların zaman aşımına dikkat et.
- Sorunun belirtisini değil kök nedenini düzelt; tek tek yama yerine ortak nedeni ara.
- Bitirince 5-10 satır özet yaz: neyi buldun, neyi değiştirdin, nasıl doğruladın."""


def etiket(task: dict) -> str | None:
    m = ETIKET_RX.search(task.get("title") or "")
    return m.group(1) if m else None


def uygun_mu(task: dict) -> bool:
    """Onarım döngüsü: talebe bağlı (kapıdan ya da müşteriden gelen) geliştirme görevleri."""
    return bool(task.get("talep_id")) and task.get("phase") == "develop" and (task.get("role") or "").lower() != "human"


def uygulama_dizini(root: Path) -> Path:
    try:
        import studio_config as SC
        import uygulama_dizini as UD
        cfg = SC.load_config(root / "workspace" / "studio.config.json")
    except Exception:
        cfg = None
    try:
        import uygulama_dizini as UD
        return root / UD.dizin(cfg)
    except Exception:
        return root / "workspace" / "src" / "web"


def testleri_kos(root: Path, timeout_s: int = 240):
    """Uygulamanın kendi test betiğini (package.json `test`) koşar: (ok, kanıt). Betik/bağımlılık yoksa atlanır (ok)."""
    import json
    d = uygulama_dizini(root)
    pj = d / "package.json"
    if not pj.is_file() or not (d / "node_modules").is_dir():
        return True, ""
    try:
        betikler = (json.loads(pj.read_text(encoding="utf-8")).get("scripts") or {})
    except (ValueError, OSError):
        return True, ""
    if "test" not in betikler:
        return True, ""
    pm = "pnpm" if (d / "pnpm-lock.yaml").exists() and shutil.which("pnpm") else "npm"
    try:
        r = subprocess.run([pm, "run", "test"], cwd=d, capture_output=True, text=True, timeout=timeout_s,
                           env={**os.environ, "CI": "1"})
    except (subprocess.TimeoutExpired, OSError) as e:
        return False, f"test komutu koşamadı/zaman aşımı: {e}"
    if r.returncode == 0:
        return True, ""
    return False, (f"`{pm} run test` başarısız (çıkış {r.returncode}):\n" + ((r.stdout or "") + (r.stderr or ""))[-3000:])


_UAT_OK_RX = re.compile(r"GEÇTİ|PASS|ÇALIŞTIRILMADI|OK\b", re.I)
_UAT_KOT_RX = re.compile(r"KALDI|BUG|BAŞARISIZ|FAIL|REDDED|KIRMIZI", re.I)


def uat_bulgulari(talep_id: str | None, root: Path = ROOT, limit: int = 2500) -> str:
    """Talebin önceki UAT raporundaki başarısız satırları (varsa): onarım ajanına girdi olur."""
    if not talep_id:
        return ""
    p = root / "workspace" / "docs" / f"uat_kabul_raporu_{talep_id}.md"
    if not p.is_file():
        return ""
    satirlar = [l.rstrip() for l in p.read_text(encoding="utf-8", errors="replace").splitlines()
                if _UAT_KOT_RX.search(l) and not (_UAT_OK_RX.search(l) and not re.search(r"KALDI|BUG|BAŞARISIZ|FAIL", l, re.I))]
    return "\n".join(satirlar)[:limit]


def istem(task: dict, kapi: str | None, kanit: str, tur: int, azami: int) -> tuple[str, str]:
    kapi_metin = {
        "RENDER": "Başarı ölçütü: sayfalar tarayıcıda hatasız çizilmeli. Doğrulama komutu: `node scripts/render_kapisi.mjs` (canlı sistem açıkken; "
                  "yapılandırma değişiklikleri için motor dev sunucuyu senin turundan sonra yeniden başlatır).",
        "BUILD": "Başarı ölçütü: çözülemeyen import kalmamalı (göreli ve Nuxt alias'ları).",
        "UAT": "Başarı ölçütü: smoke kontrolleri ve canlı UAT betiği (`node scripts/uat_live_audit.mjs`) geçmeli.",
        "HİJYEN": "Başarı ölçütü: çalışma alanına sızan artefakt kalmamalı.",
        "KAYNAK": "Başarı ölçütü: gerçek kaynak dosyalarda çalışan bir değişiklik olmalı ve import'lar çözülmeli.",
    }.get(kapi or "", "Başarı ölçütü: görev açıklamasındaki sorun giderilmiş olmalı; çözümünü kendin doğrula.")
    user = (f"GÖREV: {task.get('title')}\n\nAÇIKLAMA (sorun ve kanıt):\n{task.get('description', '')}\n\n{kapi_metin}\n"
            f"\nTUR: {tur}/{azami}")
    if kanit:
        user += f"\n\nSON DOĞRULAMA ÇIKTISI (hâlâ başarısız):\n```\n{kanit.strip()[-3500:]}\n```"
    uat = uat_bulgulari(task.get("talep_id"))
    if uat:
        user += f"\n\nÖNCEKİ UAT RAPORUNUN BAŞARISIZ BULGULARI (kapı geçse bile bunlar giderilmeli):\n```\n{uat}\n```"
    user += "\n\nDosyaları kendin oku, nedeni bul, düzelt ve doğrula."
    return SISTEM, user


def dongu(kapi_kostur, ajan_cagir, kontrol_noktasi=None, azami_tur: int = TUR_VARSAYILAN, log=print, acik_bulgu: str = "") -> dict:
    """kapi_kostur(tur) -> (ok, kanit); ajan_cagir(tur, kanit); kontrol_noktasi(tur) (git kontrol noktası, isteğe bağlı).
    acik_bulgu: talebin önceki UAT reddinden kalan açık bulgular; doluysa kapı geçse bile ajan en az 1 tur çağrılır (#269)."""
    ok, kanit = kapi_kostur(0)
    if ok and acik_bulgu:
        log("   [onarım] kapı geçiyor ama önceki UAT reddinin açık bulgusu var; ajan çağrılıyor.")
        ok, kanit = False, "Önceki UAT reddinden açık bulgular (kapı bunları ölçmüyor):\n" + acik_bulgu
    if ok:
        log("   [onarım] kapı zaten geçiyor; ajan çağrılmadı.")
        return {"durum": "zaten_gecti", "tur": 0, "kanit": kanit}
    for tur in range(1, azami_tur + 1):
        log(f"   [onarım] tur {tur}/{azami_tur}: ajan çağrılıyor (kapı başarısız).")
        if kontrol_noktasi:
            kontrol_noktasi(tur)
        ajan_cagir(tur, kanit)
        ok, kanit = kapi_kostur(tur)
        if ok:
            log(f"   [onarım] ✓ tur {tur}: kapı geçti.")
            return {"durum": "cozuldu", "tur": tur, "kanit": kanit}
        log(f"   [onarım] tur {tur}: kapı hâlâ başarısız.")
    return {"durum": "cozulemedi", "tur": azami_tur, "kanit": kanit}


# ---------------------------------------------------------------- kapı koşturucular (sensörler)
def _script(ad: str, root: Path) -> Path:
    alt = root / "workspace" / "scripts" / ad
    return alt if alt.exists() else root / "scripts" / ad


def ortam_hazirla(root: Path, yeniden: bool = False, bekle_sn: int = 150) -> bool:
    """Canlı sistemi (yerel ortam) hazırlar. Başlatacak betik yoksa False."""
    import yerel_ortam_yonet as YO
    d = YO.durum(root)
    if not d["betik_var"]:
        return False
    if yeniden or d["durum"] == "durdu":
        YO.durdur(root)
        time.sleep(1)
        YO.baslat(root)
    bit = time.time() + bekle_sn
    while time.time() < bit:
        if YO.durum(root)["durum"] == "calisiyor":
            time.sleep(2)
            return True
        time.sleep(3)
    return False


def kapi(etiket_: str | None, root: Path = ROOT):
    """Etikete göre kapı koşturucu döndürür: f(tur) -> (ok, kanit). Etiketsizde None (tek tur)."""
    import kalite_kapilari as K

    def src_dosyalari():
        out = []
        for p in (root / "workspace" / "src").rglob("*") if (root / "workspace" / "src").is_dir() else []:
            if p.is_file() and p.suffix in K.SRC_FILE_EXTS and not any(x in p.parts for x in ("node_modules", ".nuxt", ".output", "dist", ".git")):
                out.append(str(p.relative_to(root)))
        return out

    if etiket_ in ("BUILD", "KAYNAK"):
        def f(tur):
            eski = K.ROOT
            try:
                K.ROOT = root
                h = K.import_cozumleme_hatalari(src_dosyalari())
                ws = root / "workspace"
                betikler = [str(x.relative_to(root)) for pat in ("*.sh", "scripts/*.sh", "scripts/*.mjs") for x in ws.glob(pat)]
                h += K.betik_sozdizimi_hatalari(betikler)
            finally:
                K.ROOT = eski
            ok_t, kanit_t = testleri_kos(root)
            kanit = "\n".join(h[:25] + ([kanit_t] if kanit_t else []))
            return (not h and ok_t, kanit)
        return f
    if etiket_ == "HİJYEN":
        def f(tur):
            eski = (K.ROOT, K.WORKSPACE)
            try:
                K.ROOT, K.WORKSPACE = root, root / "workspace"
                _, bulgu = K.calisma_alani_hijyeni(None)
            finally:
                K.ROOT, K.WORKSPACE = eski
            return (not bulgu, "\n".join(bulgu[:25]))
        return f
    if etiket_ in ("RENDER", "UAT"):
        node = shutil.which("node")

        def f(tur):
            if not ortam_hazirla(root, yeniden=tur > 0):
                return (True, "canlı ortam başlatılamadı/tanımsız: doğrulama atlandı")
            kanit = []
            if etiket_ == "RENDER":
                betik = _script("render_kapisi.mjs", root)
                if node and betik.exists():
                    r = subprocess.run([node, str(betik)], cwd=root, capture_output=True, text=True, timeout=300, env={**os.environ, "STUDIO_KOK": str(root)})
                    cikti = (r.stdout or "").strip()
                    if r.returncode == 1 or (r.returncode == 3 and "ORTAM HATALI" in cikti):
                        return (False, cikti[-4000:])
                    return (True, cikti[-400:])
                return (True, "render betiği/node yok: doğrulama atlandı")
            eski = (K.ROOT, K.WORKSPACE)
            try:
                K.ROOT, K.WORKSPACE = root, root / "workspace"
                _, hata, liste = K.smoke_checklist()
            finally:
                K.ROOT, K.WORKSPACE = eski
            if hata:
                kanit.append("smoke: " + "; ".join(liste[:6]))
            betik = _script("uat_live_audit.mjs", root)
            if node and betik.exists():
                r = subprocess.run([node, str(betik)], cwd=root, capture_output=True, text=True, timeout=120, env={**os.environ, "STUDIO_KOK": str(root)})
                if r.returncode != 0:
                    kanit.append((r.stdout or "").strip()[-1500:])
            return (not kanit, "\n".join(kanit))
        return f
    return None


# ---------------------------------------------------------------- güvenlik: bütünlük ve kapsam denetimi
def _cerceve_dosyalari(root: Path) -> list[Path]:
    import json
    try:
        liste = json.loads((root / "studio.version").read_text(encoding="utf-8")).get("tracked_files") or []
    except (OSError, ValueError):
        liste = []
    return [root / f for f in liste if isinstance(f, str)] + [root / "studio.version"]


def butunluk_anlik(root: Path = ROOT) -> dict[str, str]:
    """Çerçeve dosyalarının özeti (tur öncesi). Ajan komutla bunları değiştirirse tur sonrası fark edilir."""
    import hashlib
    out = {}
    for p in _cerceve_dosyalari(root):
        try:
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError:
            continue
    return out


def butunluk_denetle(root: Path, once: dict[str, str]) -> list[str]:
    """Tur öncesine göre değişen/silinen çerçeve dosyaları."""
    simdi = butunluk_anlik(root)
    return sorted(k for k, v in once.items() if simdi.get(k) != v)


def kapsam_denetle(root: Path, once_snapshot: set[str]) -> list[str]:
    """Tur sırasında workspace/ DIŞINDA değişen dosyaları geri alır (izlenenler `git checkout`, izlenmeyenler silinir); geri alınanları döndürür."""
    import kalite_kapilari as K
    eski = K.ROOT
    try:
        K.ROOT = root
        degisen = K.changed_files_since(once_snapshot)
    finally:
        K.ROOT = eski
    geri = []
    for f in degisen:
        rel = f.replace("\\", "/").rstrip("/")
        if rel.startswith("workspace/") or not rel:
            continue
        p = root / rel
        try:
            izli = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=root, capture_output=True).returncode == 0
            if izli:
                subprocess.run(["git", "checkout", "--", rel], cwd=root, capture_output=True)
            elif p.is_file():
                p.unlink()
            geri.append(rel)
        except OSError:
            continue
    return geri
