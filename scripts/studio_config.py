#!/usr/bin/env python3
"""workspace/studio.config.json okuyucu + {{değişken}} çözücü (issue #130).

Framework dosyaları (org_chart prompt'ları, motor) projeye özel yol/ad/framework
içermez; proje değerleri bu dosyadan gelir. Dosya yoksa load_config() None
döner ve motor eski davranışla çalışır (geriye uyumlu).

Şema (tümü isteğe bağlı; eksikler DEFAULTS ile tamamlanır):
  source    : path, live_url, kind
  analysis  : unit, template[], max_words_l1, max_words_l2, l2_quota_pct,
              l2_quota_max, stop_after_no_new, output_dir
  discovery : goal, questions[], allow{hosts,paths}, deny{paths,actions},
              mode, limits{...}, inventory, log
"""
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("STUDIO_CONFIG") or ROOT / "workspace" / "studio.config.json")

DEFAULTS: dict = {
    "source": {"path": "", "live_url": "", "kind": ""},
    # Çalışan yerel sistemin portları (UAT/ziyaretçi görevleri canlı mı diye bakar). Proje farkı buraya yazılır.
    "live": {"ports": [3000, 3001]},
    "analysis": {
        "unit": "birim",
        "template": ["amaç", "roller", "filtreler", "widgetlar", "modal ve çekmeceler", "durumlar", "api uçları", "riskler"],
        "max_words_l1": 250,
        "max_words_l2": 600,
        "l2_quota_pct": 15,
        "l2_quota_max": 20,
        "stop_after_no_new": 5,
        "output_dir": "workspace/docs/analiz",
    },
    # Birim-envanteri tabanlı plan üretici (scripts/plan_birim.py). uretici="birim" ise `--replan` LLM planlayıcı yerine bunu kullanır.
    "planlama": {
        "uretici": "llm",                      # "llm" | "birim"
        "parca": 8,                            # tasarım/ekran görevi başına en çok birim
        "html_onizleme": True,                 # tasarımcıdan statik HTML önizleme iste (panelde görsel onay)
        "insan_kapisi": True,                  # modül başına tasarım onayı (role: human)
        "atla_modulleri": [],                  # planlanmayacak modüller (ör. kabukta yapılan hata sayfaları)
        "sprint_birim": 30,                    # otomatik sprint dağıtımında sprint başına yaklaşık birim
        "sprintler": [],                       # elle: [{"ad": "...", "moduller": ["a", "b"]}]; boşsa otomatik dengeli dağıtım
        "kurallar": [],                        # her modül görevine eklenen proje kuralları (metin listesi)
        "roller": {"tasarim": "ui_designer", "mock": "backend_engineer", "ekran": "web_engineer", "parite": "qa_lead"},
        "dizinler": {"tasarim": "workspace/docs/tasarim", "onay": "workspace/docs/onaylar",
                     "mock": "workspace/src/backend/mock", "ekran": "workspace/src/web/modules", "parite": "workspace/tests/parite"},
    },
    "discovery": {
        "goal": "",
        "questions": [],
        "allow": {"hosts": [], "paths": []},
        "deny": {"paths": ["logout|signout|delete|billing|payment"],
                 "actions": ["submit", "save", "delete", "send", "pay"],
                 # Tıklanması YASAK buton etiketleri (kelime sınırlı regex).
                 "labels": ["save", "submit", "delete", "remove", "confirm", "apply", "send",
                            "pay", "export", "download", "refresh", "sync", "merge", "run",
                            "start", "stop", "reset", "logout", "sign out", "ok", "yes",
                            "upload", "import", "invite", "activate", "deactivate"]},
        # Gezginin yoklayabileceği (aç-oku-kapat) buton etiketleri; dışındakilere tıklanmaz.
        # Sayfa içi seçiciler (boş bırakılırsa kütüphane-bağımsız varsayılanlar kullanılır).
        "selectors": {},
        "open_labels": ["new", "add", "create", "select", "filter", "columns", "details",
                        "view", "show", "settings", "configure", "manage", "edit", "custom"],
        "mode": "read_only",
        # Oturum yoksa uygulamanın yönlendirdiği giriş yolu; envanterde atlanacak rotalar (regex listesi).
        "login_path": "/login",
        # Veri OKUYAN ama POST kullanan uç yolları (regex). Tıklama sırasında bunlara giden POST yazma sayılmaz.
        # Yalnızca kullanıcı onayıyla doldurulur; varsayılan boş = her GET dışı istek ihlaldir.
        "read_post_paths": [],
        "skip_routes": [],
        "limits": {"max_units": 150, "max_actions_per_unit": 12,
                   "max_depth": 2, "max_minutes": 90, "max_sampling_actions": 300,
                   "max_off_inventory_pct": 10},
        "inventory": "workspace/docs/analiz/_envanter.txt",
        "log": "workspace/docs/analiz/_ziyaret_gunlugu.jsonl",
    },
}

_VAR = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Path | None = None) -> dict | None:
    """Config yoksa None; varsa DEFAULTS ile birleştirilmiş sözlük."""
    p = Path(path) if path else CONFIG_PATH
    if not p.exists():
        return None
    return _merge(DEFAULTS, json.loads(p.read_text(encoding="utf-8")))


def validate_config(cfg: dict) -> list[str]:
    """Şema hatalarını döndürür (boş liste = geçerli). Keşif alanları ayrıca
    validate_discovery() ile denetlenir; çünkü analiz-only projeler keşif
    sözleşmesi tanımlamak zorunda değildir."""
    errs = []
    a = cfg.get("analysis", {})
    if not a.get("template"):
        errs.append("analysis.template boş olamaz")
    for k in ("max_words_l1", "max_words_l2", "l2_quota_pct", "l2_quota_max", "stop_after_no_new"):
        if not isinstance(a.get(k), int) or a[k] < 0:
            errs.append(f"analysis.{k} pozitif tamsayı olmalı")
    if a.get("max_words_l2", 0) < a.get("max_words_l1", 0):
        errs.append("analysis.max_words_l2 >= max_words_l1 olmalı")
    return errs


def validate_discovery(cfg: dict) -> list[str]:
    """Keşif sözleşmesi zorunlu alanları. Hata varsa keşif BAŞLAMAZ."""
    d = (cfg or {}).get("discovery", {})
    errs = []
    if not str(d.get("goal", "")).strip():
        errs.append("discovery.goal boş: keşfin hedefi tek cümleyle yazılmalı")
    if not d.get("questions"):
        errs.append("discovery.questions boş: keşfin cevaplayacağı soru(lar) yazılmalı")
    if not (d.get("allow") or {}).get("hosts"):
        errs.append("discovery.allow.hosts boş: izinli host listesi zorunlu")
    if d.get("mode") not in ("read_only",):
        errs.append("discovery.mode yalnızca 'read_only' olabilir (mutating eylem açık onay gerektirir)")
    lim = d.get("limits", {})
    for k in ("max_units", "max_actions_per_unit", "max_depth", "max_minutes"):
        if not isinstance(lim.get(k), int) or lim[k] <= 0:
            errs.append(f"discovery.limits.{k} pozitif tamsayı olmalı")
    for rx in (d.get("allow") or {}).get("paths", []) + (d.get("deny") or {}).get("paths", []):
        try:
            re.compile(rx)
        except re.error as e:
            errs.append(f"geçersiz regex '{rx}': {e}")
    return errs


def get(cfg: dict | None, dotted: str, default=""):
    cur = cfg or {}
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def render(text: str, cfg: dict | None) -> str:
    """{{a.b}} değişkenlerini config'ten doldurur. Config yoksa veya anahtar
    bulunamazsa ifade AYNEN bırakılır (sessizce boş string üretmez)."""
    if not cfg:
        return text

    def sub(m):
        v = get(cfg, m.group(1), None)
        if v is None:
            return m.group(0)
        return ", ".join(map(str, v)) if isinstance(v, list) else str(v)
    return _VAR.sub(sub, text)


ANALYSIS_RULES = """

--- ANALİZ BÜTÇESİ KURALLARI (studio.config.json) ---
- Her {unit} için AYRI dosya: `{out}/<küme>/<birim>.md`. Tek dev doküman yazma; birleşik dosya yalnızca ≤1 sayfalık `_indeks.md`.
- Dosya başı: `# <birim adı>` ve `Seviye: L1` (derin analiz için `Seviye: L2`).
- Şablon alanları (her biri `## <alan>` başlığı): {template}.
- Kelime tavanı: L1 ≤ {w1}, L2 ≤ {w2}. Düzyazı yerine tablo/madde. Tavanı aşarsan kısalt, bölme.
- L2 yalnızca yüksek riskli birimler içindir; toplam L2 sayısı birimlerin %{pct}'ini (en fazla {qmax}) geçemez.
- Aynı şablonu paylaşan benzer birimleri TEK "kalıp" dokümanında topla; birim başına yalnızca fark tablosu yaz.
- Kanıtsız iddia YASAK: dolu her alan en az bir `[kaynak: dosya:satır | URL | endpoint]` işareti taşımalı. Kanıt yoksa alanın değeri yalnızca `bilinmiyor` olur. Tahmin, uydurma veya örnek veri yazma.
- Ardışık {stop} birimde şablona yeni bulgu eklenmiyorsa derinleştirmeyi durdur; kalanları L0/L1'de bırak.
"""

DISCOVERY_RULES = """

--- KEŞİF SÖZLEŞMESİ (studio.config.json → discovery) ---
HEDEF: {goal}
SORULAR (her adım bunlardan birine bağlanmalı): {questions}
İZİN: host={hosts}; path={apaths}. YASAK path: {dpaths}. YASAK eylem: {dactions}.
- Mod `read_only`: yalnızca okuma ve geri alınabilir etkileşim (modal/çekmece/sekme aç-kapat). Kaydet/sil/gönder/ödeme/ayar değiştirme YASAK. Oturum kapatma, başka host'a çıkış, kimlik bilgisi girme YASAK.
- Ziyaret kuyruğu ENVANTERDEN gelir. Envanterde karşılığı olmayan veya izin dışı bir bağlantıyı ZİYARET ETME; yalnızca `kapsam_dışı_gözlemler` listesine tek satır (url + neden) yaz.
- Sınırlar: birim başına ≤ {mapu} eylem, derinlik ≤ {depth}, toplam ≤ {mu} birim, ≤ {mm} dakika. Sınıra gelince birimi `skipped(limit)` işaretle ve devam et.
- Şablon alanları dolunca birimden ÇIK; ilginç görünen yan konulara gitme.
- Her adımı `{log}` dosyasına JSONL olarak ekle: {{"birim","url","soru_id","eylem_sinifi"(read|reversible|mutating),"eylem","sonuc","yeni_bulgu"}}.
- Ham kişisel veri (e-posta, isim, token, anahtar) kaydetme; alan adı ve türünü yaz, değerini değil.
"""


def rules_block(cfg: dict | None, *, analysis: bool = False, discovery: bool = False) -> str:
    """Rolün system prompt'una eklenecek kural metni (config yoksa boş)."""
    if not cfg:
        return ""
    out = ""
    if analysis:
        a = cfg["analysis"]
        out += ANALYSIS_RULES.format(
            unit=a["unit"], out=a["output_dir"], template=", ".join(a["template"]),
            w1=a["max_words_l1"], w2=a["max_words_l2"], pct=a["l2_quota_pct"],
            qmax=a["l2_quota_max"], stop=a["stop_after_no_new"])
    if discovery:
        d = cfg["discovery"]
        lim = d["limits"]
        out += DISCOVERY_RULES.format(
            goal=d["goal"], questions=" | ".join(f"Q{i+1}: {q}" for i, q in enumerate(d["questions"])),
            hosts=", ".join(d["allow"]["hosts"]), apaths=", ".join(d["allow"]["paths"]) or "(tümü)",
            dpaths=", ".join(d["deny"]["paths"]) or "-", dactions=", ".join(d["deny"]["actions"]) or "-",
            mapu=lim["max_actions_per_unit"], depth=lim["max_depth"], mu=lim["max_units"],
            mm=lim["max_minutes"], log=d["log"])
    return out
