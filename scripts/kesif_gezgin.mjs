#!/usr/bin/env node
/**
 * Melez keşif gezgini (issue #132) — LLM'siz, bağımlılıksız (Node 22 + sistemde Chrome, CDP).
 *
 * Keşif sözleşmesini (workspace/studio.config.json → discovery) KODLA zorlar:
 * her ziyaret/tıklama scripts/kesif_denetle.py --sunucu ile denetlenir; yazma eylemi,
 * yasak etiket/path ve izinsiz host asla tıklanmaz/ziyaret edilmez.
 *
 * Kullanım:
 *   node scripts/kesif_gezgin.mjs --login          # görünür Chrome açar; kullanıcı BİR KEZ giriş yapar
 *   node scripts/kesif_gezgin.mjs                  # envanteri gez (devam edilebilir)
 *   node scripts/kesif_gezgin.mjs --only '^/admin' --headed --fresh
 *   node scripts/kesif_gezgin.mjs --fresh --gorsel   # her birim için ekran görüntüsü: <output_dir>/_gorsel/<slug>.png (yerel, git dışı)
 * Ortam: CHROME_PATH (varsayılan macOS Chrome). Profil: workspace/.kesif_profil (repoya girmez).
 * Çıktı: <analysis.output_dir>/_ham/<slug>.json, discovery.log (JSONL), _ham/_durum.json
 * Çıkış kodu: 0 tamam, 2 oturum yok, 3 sözleşme geçersiz, 4 sapma/ihlal.
 */
import { spawn } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync, existsSync, appendFileSync, readdirSync } from 'node:fs';
import { createInterface } from 'node:readline';
import { infer, merge, normPath } from './kesif_sema.mjs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
const flag = (n) => args.includes(n);
const opt = (n, d = null) => { const i = args.indexOf(n); return i >= 0 ? args[i + 1] : d; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------- config (Python tek kaynak: studio_config) ----------
function loadConfig() {
  const py = spawn('python3', ['-c',
    'import sys,json;sys.path.insert(0,"scripts");import studio_config as C;c=C.load_config();' +
    'print(json.dumps({"cfg":c,"errs":C.validate_discovery(c) if c else ["workspace/studio.config.json yok"]},ensure_ascii=False))'],
    { cwd: ROOT });
  return new Promise((res, rej) => {
    let o = ''; py.stdout.on('data', (d) => (o += d)); py.stderr.on('data', (d) => process.stderr.write(d));
    py.on('close', () => { try { res(JSON.parse(o)); } catch (e) { rej(e); } });
  });
}

// ---------- izin sunucusu ----------
function izinSunucusu() {
  const p = spawn('python3', ['scripts/kesif_denetle.py', '--sunucu'], { cwd: ROOT });
  const rl = createInterface({ input: p.stdout });
  const bekleyen = [];
  rl.on('line', (ln) => { const r = bekleyen.shift(); if (r) r(JSON.parse(ln)); });
  return {
    sor: (url, sinif, eylem = '') => new Promise((r) => { bekleyen.push(r); p.stdin.write(JSON.stringify({ url, sinif, eylem }) + '\n'); }),
    kapat: () => p.stdin.end(),
  };
}

// ---------- minimal CDP istemcisi ----------
class CDP {
  constructor(ws) { this.ws = ws; this.id = 0; this.p = new Map(); this.h = []; ws.addEventListener('message', (m) => this.#msg(JSON.parse(m.data))); }
  #msg(m) {
    if (m.id && this.p.has(m.id)) { const { res, rej } = this.p.get(m.id); this.p.delete(m.id); m.error ? rej(new Error(m.error.message)) : res(m.result); }
    else this.h.forEach((f) => f(m));
  }
  send(method, params = {}, sessionId) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    return new Promise((res, rej) => this.p.set(id, { res, rej }));
  }
  on(f) { this.h.push(f); }
}

async function chromeBaslat(profil, headless) {
  const chrome = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  const port = 9300 + Math.floor(Math.random() * 500);
  mkdirSync(profil, { recursive: true });
  const a = [`--remote-debugging-port=${port}`, `--user-data-dir=${profil}`, '--no-first-run', '--no-default-browser-check',
    '--window-size=1440,900', ...(headless ? ['--headless=new'] : []), 'about:blank'];
  const proc = spawn(chrome, a, { stdio: 'ignore' });
  for (let i = 0; i < 60; i++) {
    try {
      const j = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json();
      const ws = new WebSocket(j.webSocketDebuggerUrl);
      await new Promise((r, e) => { ws.onopen = r; ws.onerror = e; });
      return { proc, cdp: new CDP(ws) };
    } catch { await sleep(250); }
  }
  proc.kill(); throw new Error('Chrome başlatılamadı (CHROME_PATH?)');
}

async function sayfaAc(cdp, url) {
  const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
  const s = (m, p) => cdp.send(m, p, sessionId);
  await s('Page.enable'); await s('Runtime.enable'); await s('Network.enable');
  await s('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
  return { s, sessionId, targetId, url };
}

class OturumYok extends Error {}
const slug = (s) => s.replace(/[^A-Za-z0-9]+/g, '-').replace(/^-|-$/g, '').toLowerCase() || 'kok';
const rx = (pat) => new RegExp('^' + pat.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/:[A-Za-z0-9_]+/g, '[^/]+') + '/?$');

async function main() {
  const { cfg, errs } = await loadConfig();
  if (errs.length) { console.error('[sözleşme] ' + errs.join('\n[sözleşme] ')); process.exit(3); }
  const d = cfg.discovery, lim = d.limits;
  const origin = cfg.source.live_url || `https://${d.allow.hosts[0]}`;
  const profil = process.env.STUDIO_KESIF_PROFIL || path.join(ROOT, 'workspace', '.kesif_profil');
  const outDir = path.resolve(ROOT, cfg.analysis.output_dir);
  const ham = path.join(outDir, '_ham'); mkdirSync(ham, { recursive: true });
  const logYol = path.resolve(ROOT, d.log);
  const durumYol = path.join(ham, '_durum.json');
  const semaYol = path.join(outDir, '_api_semalari.json');
  const semaAcik = flag('--sema');
  const gorselAcik = flag('--gorsel');
  const gorselDir = path.join(outDir, '_gorsel');
  const semalar = semaAcik && existsSync(semaYol) ? JSON.parse(readFileSync(semaYol, 'utf8')) : {};

  // ---- giriş modu ----
  if (flag('--login')) {
    const { proc, cdp } = await chromeBaslat(profil, false);
    const pg = await sayfaAc(cdp);
    await pg.s('Page.navigate', { url: origin });
    console.log(`Chrome açıldı. ${origin} adresinde giriş yapın, sonra buraya dönüp Enter'a basın.`);
    await new Promise((r) => createInterface({ input: process.stdin }).once('line', r));
    await cdp.send('Browser.close').catch(() => {});
    proc.kill(); return;
  }

  // ---- oturum kontrolü (yetenek_kontrol kullanır): profille hedefi aç, giriş sayfasına düşüyor mu? ----
  if (flag('--oturum-kontrol')) {
    const { proc, cdp } = await chromeBaslat(profil, true);
    const pg = await sayfaAc(cdp);
    let kod = 0;
    try {
      await pg.s('Page.navigate', { url: origin + '/' });
      await sleep(6000);
      const r = await pg.s('Runtime.evaluate', { expression: 'location.pathname', returnByValue: true });
      const yol = r.result.value || '';
      kod = yol.startsWith(d.login_path) ? 2 : 0;
      console.log(kod === 0 ? `oturum var (${yol})` : `oturum yok (${yol})`);
    } catch (e) { console.error(e.message); kod = 1; }
    await cdp.send('Browser.close').catch(() => {}); proc.kill();
    process.exit(kod);
  }

  // ---- envanter ----
  const envYol = path.resolve(ROOT, d.inventory);
  if (!existsSync(envYol)) { console.error(`envanter yok: ${envYol}`); process.exit(3); }
  let rotalar = readFileSync(envYol, 'utf8').split('\n').map((l) => l.split('\t')[0].trim()).filter((l) => l.startsWith('/') && !l.includes('*'));
  const envRx = rotalar.map(rx);            // tüm envanter: gezgin YALNIZCA bunlarla eşleşen yolları ziyaret eder
  const envanterde = (u) => { try { const p = new URL(u).pathname; return envRx.some((x) => x.test(p)); } catch { return false; } };
  const okuPost = (d.read_post_paths || []).map((x) => new RegExp(x));
  const yazmaVar = () => istekler.some((x) => x.method !== 'GET' && !okuPost.some((rg) => rg.test(new URL(x.url).pathname)));
  const atla = (d.skip_routes || []).map((x) => new RegExp(x));
  rotalar = rotalar.filter((r) => !atla.some((x) => x.test(r)));
  if (opt('--only')) rotalar = rotalar.filter((r) => new RegExp(opt('--only')).test(r));
  const durum = flag('--fresh') || !existsSync(durumYol) ? { bitti: {} } : JSON.parse(readFileSync(durumYol, 'utf8'));
  const kaydet = () => { writeFileSync(durumYol, JSON.stringify(durum, null, 1)); if (semaAcik) writeFileSync(semaYol, JSON.stringify(Object.fromEntries(Object.entries(semalar).sort()), null, 1)); };

  const izin = izinSunucusu();
  const { proc, cdp } = await chromeBaslat(profil, !flag('--headed'));
  const kapat = () => { try { proc.kill(); } catch { /* yok */ } };
  process.on('SIGINT', () => { kapat(); process.exit(130); });
  process.on('SIGTERM', () => { kapat(); process.exit(143); });
  const pg = await sayfaAc(cdp);
  const cikarici = readFileSync(path.join(ROOT, 'scripts/kesif_cikarici.js'), 'utf8');
  const ev = async (expr) => {
    const r = await pg.s('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || 'evaluate hatası');
    return r.result.value;
  };

  // ağ izleme (yalnızca XHR/Fetch)
  let inflight = 0, sonAg = Date.now(), istekler = [];
  const istekMeta = new Map(), semaBekleyen = [];
  let suankiBirim = '';
  const hostIzinli = new Set(d.allow.hosts.map((h) => h.toLowerCase()));
  async function semaYakala(requestId, meta) {
    try {
      const r = await pg.s('Network.getResponseBody', { requestId });
      const j = JSON.parse(r.base64Encoded ? Buffer.from(r.body, 'base64').toString('utf8') : r.body);
      const anahtar = `GET ${normPath(new URL(meta.url).pathname)}`;
      const kayit = semalar[anahtar] || { durum: meta.status, ornek: 0, birimler: [], sema: undefined };
      kayit.sema = merge(kayit.sema, infer(j));
      kayit.ornek++;
      if (suankiBirim && !kayit.birimler.includes(suankiBirim)) kayit.birimler.push(suankiBirim);
      semalar[anahtar] = kayit;
    } catch { /* gövde yok / JSON değil */ }
  }
  cdp.on((m) => {
    if (m.sessionId !== pg.sessionId) return;
    if (semaAcik && m.method === 'Network.responseReceived') {
      const x = istekMeta.get(m.params.requestId);
      if (x) { x.status = m.params.response.status; x.mime = m.params.response.mimeType; }
    }
    if (semaAcik && m.method === 'Network.loadingFinished') {
      const x = istekMeta.get(m.params.requestId);
      if (x && x.method === 'GET' && ['XHR', 'Fetch'].includes(x.type) && /json/i.test(x.mime || '') && hostIzinli.has(new URL(x.url).host.toLowerCase())) semaBekleyen.push(semaYakala(m.params.requestId, x));
    }
    if (m.method === 'Network.requestWillBeSent') {
      istekMeta.set(m.params.requestId, { method: m.params.request.method, url: m.params.request.url, type: m.params.type });
      inflight++; sonAg = Date.now();
      if (['XHR', 'Fetch'].includes(m.params.type)) istekler.push({ method: m.params.request.method, url: m.params.request.url });
    }
    if (['Network.loadingFinished', 'Network.loadingFailed'].includes(m.method)) { inflight = Math.max(0, inflight - 1); sonAg = Date.now(); }
  });

  const gozlenen = new Set();           // keşfedilen iç bağlantılar (:param örneklemesi)
  const t0 = Date.now();
  let ihlal = 0, birim = 0;
  const logla = (o) => { mkdirSync(path.dirname(logYol), { recursive: true }); appendFileSync(logYol, JSON.stringify(o) + '\n'); };
  const modalAcik = new RegExp('^(' + d.open_labels.join('|') + ')\\b', 'i');

  async function git(url) {
    if (!envanterde(url)) throw new Error(`envanter dışı ziyaret engellendi: ${url}`);
    const kap = new Promise((r) => { const f = (m) => { if (m.sessionId === pg.sessionId && m.method === 'Page.loadEventFired') r(); }; cdp.on(f); setTimeout(r, 20000); });
    istekler = []; await pg.s('Page.navigate', { url }); await kap;
    const bas = Date.now();
    while (Date.now() - bas < 12000 && (inflight > 0 || Date.now() - sonAg < 1500)) await sleep(250);
    await sleep(800);
  }

  async function birimGez(rota, url) {
    const ok = await izin.sor(url, 'read', 'navigate');
    if (!ok.ok) { console.log(`  ✗ ATLANDI (${ok.neden}) ${rota}`); return { durum: 'engellendi', neden: ok.neden }; }
    const bas = Date.now(); let eylem = 1;
    suankiBirim = rota;
    await git(url);
    await Promise.allSettled(semaBekleyen.splice(0));
    const yol = await ev('location.pathname');
    if (yol.startsWith(d.login_path) && !rota.startsWith(d.login_path)) throw new OturumYok();
    await ev(`window.__ks_cfg = ${JSON.stringify(d.selectors || {})}; ${cikarici}`);
    const ex = await ev('window.__ks.extract()');
    if (gorselAcik) {                              // referans ekran görüntüsü (yerel; kişisel veri içerebilir, git'e girmez)
      try {
        const sh = await pg.s('Page.captureScreenshot', { format: 'png', clip: { x: 0, y: 0, width: 1440, height: 900, scale: 0.6 } });
        mkdirSync(gorselDir, { recursive: true });
        writeFileSync(path.join(gorselDir, slug(rota) + '.png'), Buffer.from(sh.data, 'base64'));
      } catch { /* görüntü alınamadı: keşif sürer */ }
    }
    ex.lk.forEach((h) => { if (h.startsWith('/')) gozlenen.add(h.split('?')[0].split('#')[0]); });
    const yonlendirme = ex.path.split('?')[0] !== rota && !rx(rota).test(ex.path.split('?')[0]) ? ex.path : null;
    const ulr = origin + ex.path;
    logla({ birim: rota, url: ulr, soru_id: 'Q1', eylem_sinifi: 'read', eylem: 'navigate', sonuc: 'ok', derinlik: 0, yeni_bulgu: 1 });
    const postlar = istekler.filter((r) => r.method !== 'GET').map((r) => `${r.method} ${new URL(r.url).pathname}`);
    const modals = [];
    const adaylar = ex.btn.filter((b) => modalAcik.test(b));
    for (const b of adaylar) {
      if (eylem >= lim.max_actions_per_unit - 1) { modals.push({ label: b, atlandi: 'eylem limiti' }); continue; }
      const iz = await izin.sor(ulr, 'reversible', b);
      if (!iz.ok) { modals.push({ label: b, atlandi: iz.neden }); continue; }
      istekler = []; eylem++;
      let r;
      try { r = await ev(`window.__ks.probe(${JSON.stringify(b)})`); } catch (e) { r = { label: b, hata: String(e.message) }; }
      const yazma = istekler.filter((x) => x.method !== 'GET' && !okuPost.some((rg) => rg.test(new URL(x.url).pathname)));
      if (yazma.length) { r.mutating_istek = yazma.map((x) => `${x.method} ${new URL(x.url).pathname}`); ihlal++; }
      modals.push(r);
      logla({ birim: rota, url: ulr, soru_id: 'Q2', eylem_sinifi: yazma.length ? 'mutating' : 'reversible', eylem: 'open:' + b, sonuc: r.acildi ? 'ok' : (r.sayfaya_gitti ? 'navigates' : 'no-dialog'), derinlik: 1, yeni_bulgu: r.acildi ? 1 : 0 });
      if (r.sayfaya_gitti || yazma.length) { await git(ulr); await ev(`window.__ks_cfg = ${JSON.stringify(d.selectors || {})}; ${cikarici}`); }
      if (yazma.length) break;       // yazma isteği: bu birimde tıklamayı bırak
    }
    logla({ birim: rota, url: ulr, soru_id: 'Q3', eylem_sinifi: 'read', eylem: 'observe-states', sonuc: 'ok', derinlik: 0, yeni_bulgu: 0 });
    return { durum: 'tamam', rota, url: ulr, yonlendirme, ...ex, modals, post_istekleri: postlar, sure_ms: Date.now() - bas };
  }

  async function isle(rota, url, tahmin = false) {
    if (durum.bitti[rota] || birim >= lim.max_units) return;
    if ((Date.now() - t0) / 60000 > lim.max_minutes) { console.log('süre limiti'); return 'dur'; }
    birim++; process.stdout.write(`[${birim}] ${rota} … `);
    let r;
    try { r = await birimGez(rota, url); if (tahmin && r.durum === 'tamam') r.tahmin = true; } catch (e) { if (e instanceof OturumYok) throw e; r = { durum: 'hata', hata: String(e.message) }; }
    writeFileSync(path.join(ham, slug(rota) + '.json'), JSON.stringify({ birim: rota, ...r }, null, 1));
    durum.bitti[rota] = r.durum; kaydet();
    console.log(`${r.durum}${r.yonlendirme ? ' → ' + r.yonlendirme : ''}${r.modals?.length ? ` (${r.modals.filter((m) => m.acildi).length}/${r.modals.length} modal)` : ''}`);
  }

  // Önceki koşulardan gözlenen bağlantıları geri yükle (devam edilen koşuda :param örneklemesi için)
  for (const f of readdirSync(ham)) {
    if (!f.endsWith('.json') || f.startsWith('_')) continue;
    try { for (const h of JSON.parse(readFileSync(path.join(ham, f), 'utf8')).lk || []) if (h.startsWith('/')) gozlenen.add(h.split('?')[0].split('#')[0]); } catch { /* bozuk dosya */ }
  }

  // Satır/kart tıklamasıyla detay örneği: hedef rotanın en yakın somutlanabilir ataşından listeyi açar.
  async function satirOrnekle(rota) {
    const seg = rota.split('/').filter(Boolean);
    for (let k = seg.length - 1; k >= 1; k--) {
      const parcalar = [];
      let tamam = true;
      for (let j = 0; j < k && tamam; j++) {
        if (!seg[j].startsWith(':')) { parcalar.push(seg[j]); continue; }
        const onek = rx('/' + seg.slice(0, j + 1).join('/'));
        const sub = [...gozlenen].find((h) => onek.test(h));
        if (sub) parcalar.push(sub.split('/').filter(Boolean)[j]); else tamam = false;
      }
      if (!tamam) continue;
      const ata = '/' + parcalar.join('/');
      if (!envanterde(origin + ata)) continue;
      const url = origin + ata;
      for (let i = 0; i < 3; i++) {
        const iz = await izin.sor(url, 'reversible', 'row-click');
        if (!iz.ok) return null;
        await git(url);
        await ev(`window.__ks_cfg = ${JSON.stringify(d.selectors || {})}; ${cikarici}`);
        istekler = [];
        const once = await ev(`window.__ks.rowSample(${i})`);
        let yeni = null;
        if (once !== null) {
          await sleep(600);
          const bas = Date.now();
          while (Date.now() - bas < 10000 && (inflight > 0 || Date.now() - sonAg < 1200)) await sleep(250);
          const simdi = await ev('location.pathname').catch(() => once);
          yeni = simdi !== once ? simdi : null;
        }
        logla({ birim: '~ornekleme', url, soru_id: 'Q1', eylem_sinifi: yazmaVar() ? 'mutating' : 'reversible', eylem: 'row-click:' + rota, sonuc: yeni ? 'navigates' : 'no-nav', derinlik: 1, yeni_bulgu: yeni ? 1 : 0 });
        if (yazmaVar()) { ihlal++; return null; }
        if (yeni) {
          gozlenen.add(yeni);
          if (rx(rota).test(yeni)) return yeni;
        } else if (i === 0) break;        // aday satır yok
      }
    }
    return null;
  }

  // Kimlik türetme: aynı kaynak (ilk segment) altında gözlenen bir kimliği ':param' yerine koyar.
  // Yalnızca GET gezinmesidir; tahmin edilen birim ham kayıtta `tahmin: true` taşır ve doğrulama için işaretlenir.
  function tahminle(rota) {
    const seg = rota.split('/').filter(Boolean);
    const kimlik = /^([0-9a-f]{24}|[0-9a-f]{8}-[0-9a-f-]{27}|\d+)$/i;
    const havuz = [];
    for (const h of gozlenen) {
      const p = h.split('/').filter(Boolean);
      if (p[0] === seg[0]) for (const x of p) if (kimlik.test(x) && !havuz.includes(x)) havuz.push(x);
    }
    if (!havuz.length) return null;
    let n = 0;
    return '/' + seg.map((x) => (x.startsWith(':') ? havuz[Math.min(n++, havuz.length - 1)] : x)).join('/');
  }

  const statik = rotalar.filter((r) => !r.includes(':'));
  const paramli = rotalar.filter((r) => r.includes(':'));
  let kod = 0;
  try {
    for (const r of statik) if ((await isle(r, origin + r)) === 'dur') break;
    for (let tur = 0; tur < 3; tur++) {                     // :param rotaları gözlenen bağlantılardan, olmazsa satır tıklamasıyla örneklenir
      for (const r of paramli) {
        if (durum.bitti[r] && durum.bitti[r] !== 'ornek-yok') continue;
        let orn = [...gozlenen].find((h) => rx(r).test(h));
        if (!orn && tur > 0) orn = await satirOrnekle(r);
        if (!orn) continue;
        delete durum.bitti[r];
        if ((await isle(r, origin + orn)) === 'dur') break;
      }
    }
    for (const r of paramli) {                              // son çare: kimlik türetme (tahmin)
      if (durum.bitti[r] && durum.bitti[r] !== 'ornek-yok') continue;
      const t = tahminle(r);
      if (!t) continue;
      const iz = await izin.sor(origin + t, 'read', 'navigate');
      if (!iz.ok) continue;
      delete durum.bitti[r];
      await isle(r, origin + t, true);
    }
    for (const r of paramli) if (!durum.bitti[r]) { durum.bitti[r] = 'ornek-yok'; writeFileSync(path.join(ham, slug(r) + '.json'), JSON.stringify({ birim: r, durum: 'ornek-yok' })); }
    console.log(`\nBitti: ${birim} birim, ihlal=${ihlal}. Sonraki: python3 scripts/kesif_yaz.py && python3 scripts/kesif_denetle.py`);
    kod = ihlal ? 4 : 0;
  } catch (e) {
    if (e instanceof OturumYok) { console.error('Oturum yok: önce `node scripts/kesif_gezgin.mjs --login`'); kod = 2; }
    else { console.error(e); kod = 1; }
  } finally {
    kaydet();
    izin.kapat(); await cdp.send('Browser.close').catch(() => {}); proc.kill();
  }
  process.exit(kod);
}

main().catch((e) => { console.error(e); process.exit(1); });
