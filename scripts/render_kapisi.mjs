#!/usr/bin/env node
/**
 * Digital Software Studio — Render kapısı (projeden bağımsız, bağımlılıksız): sayfalar tarayıcıda GERÇEKTEN çiziliyor mu?
 *
 * HTTP durumu "sayfa çiziliyor" demek değildir (Vue bileşeni çözülemeyince 200 döner, header/sidebar yoktur).
 * Bu kapı headless Chrome'u CDP ile sürer, her rotada:
 *   - konsolda hata / "[Vue warn]" / çözülemeyen bileşen / yakalanmamış istisna,
 *   - 5xx yanıt, boş sayfa, beklenen çatının (header / nav / main) eksikliği
 * arar. Ekran görüntüsü workspace/docs/ekran_goruntuleri/, rapor workspace/docs/render_raporu.md.
 *
 * Ayar: workspace/uat_checklist.json (hepsi isteğe bağlı)
 *   {"rotalar": ["/", "/home"],                       // yoksa uygulama dizinindeki pages/ dosyalarından türetilir
 *    "giris": {"rota": "/login", "doldur": {"input[type=email]": "a@b.c", "input[type=password]": "x"}, "tikla": "button[type=submit]"},
 *    "cati": {"secici": ["header,[role=banner]", "nav,[role=navigation]", "main,[role=main]"], "haric": ["/login"]},
 *    "yoksay": ["regex"]}                              // yok sayılacak konsol iletileri
 * Çıkış: 0 geçti, 1 başarısız, 3 atlandı (Chrome/canlı sistem yok). CHROME_PATH ile Chrome yolu verilebilir.
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = process.env.STUDIO_KOK ? path.resolve(process.env.STUDIO_KOK) : path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const oku = (rel, v) => { try { return JSON.parse(fs.readFileSync(path.join(ROOT, rel), 'utf8')); } catch { return v; } };
const slug = (s) => s.replace(/[^A-Za-z0-9]+/g, '-').replace(/^-|-$/g, '').toLowerCase() || 'kok';

const cfg = oku('workspace/studio.config.json', {});
const liste = oku('workspace/uat_checklist.json', {});
const port = ((cfg.live || {}).ports || [3000])[0];
const appDizin = (((cfg.planlama || {}).dizinler || {}).uygulama) || 'workspace/src/web';
const CATI = (liste.cati && liste.cati.secici) || ['header,[role=banner]', 'nav,[role=navigation]', 'main,[role=main]'];
const HARIC = new Set((liste.cati && liste.cati.haric) || ['/login', '/remember', '/401', '/403', '/404']);
const YOKSAY = [/favicon/i, /DevTools/i, /\[vite\]/i, /Failed to load resource: the server responded with a status of 40\d/i, ...((liste.yoksay || []).map((r) => new RegExp(r)))];
const SORUN = /\[Vue warn\]|Failed to resolve component|Hydration|is missing template|Uncaught|TypeError|ReferenceError/i;

// Konsol iletisi: ilk satır, %c biçim işaretleri ve tekrarlar temizlenir
const temizMesaj = (m) => m.split('\n')[0].replace(/%c[^%\s]*%c\s*/g, '').replace(/%c/g, '').replace(/\s+/g, ' ').trim().slice(0, 200);

function atla(neden) { console.log(`⏭️  Render kapısı atlandı: ${neden}`); process.exit(3); }

// ---------- rota keşfi (Nuxt pages/) ----------
function sayfalardanRotalar() {
  for (const kok of [path.join(ROOT, appDizin, 'app', 'pages'), path.join(ROOT, appDizin, 'pages')]) {
    if (!fs.existsSync(kok)) continue;
    const out = [];
    const gez = (d, onek) => {
      for (const e of fs.readdirSync(d, { withFileTypes: true })) {
        if (e.isDirectory()) gez(path.join(d, e.name), `${onek}/${e.name}`);
        else if (/\.vue$/.test(e.name)) {
          const ad = e.name.replace(/\.vue$/, '');
          if (/[\[\]]/.test(ad) || /[\[\]]/.test(onek)) continue;      // dinamik rotalar atlanır
          out.push(ad === 'index' ? (onek || '/') : `${onek}/${ad}`);
        }
      }
    };
    gez(kok, '');
    return [...new Set(out)].sort();
  }
  return ['/'];
}

// ---------- canlı sistem ----------
let taban = null;
for (const h of ['localhost', '127.0.0.1', '[::1]']) {
  try { const r = await fetch(`http://${h}:${port}/`, { redirect: 'manual' }); if (r.status < 600) { taban = `http://${h}:${port}`; break; } } catch { /* sonraki */ }
}
if (!taban) atla(`canlı sistem yok (port ${port} kapalı)`);

// ---------- minimal CDP ----------
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

const CHROME = process.env.CHROME_PATH || [
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/usr/bin/google-chrome', '/usr/bin/chromium', '/usr/bin/chromium-browser',
].find((p) => fs.existsSync(p));
if (!CHROME) atla('Chrome bulunamadı (CHROME_PATH verin)');

const profil = fs.mkdtempSync(path.join(os.tmpdir(), 'studio-render-'));
const cdpPort = 9800 + Math.floor(Math.random() * 150);
const chrome = spawn(CHROME, [`--remote-debugging-port=${cdpPort}`, `--user-data-dir=${profil}`, '--headless=new', '--no-first-run',
  '--no-default-browser-check', '--window-size=1440,900', 'about:blank'], { stdio: 'ignore' });
let cdp = null;
for (let i = 0; i < 60 && !cdp; i++) {
  try {
    const j = await (await fetch(`http://127.0.0.1:${cdpPort}/json/version`)).json();
    const ws = new WebSocket(j.webSocketDebuggerUrl);
    await new Promise((r, e) => { ws.onopen = r; ws.onerror = e; });
    cdp = new CDP(ws);
  } catch { await sleep(250); }
}
if (!cdp) { chrome.kill(); atla('Chrome başlatılamadı'); }

const kapat = async () => { try { await cdp.send('Browser.close'); } catch { /* */ } chrome.kill(); try { fs.rmSync(profil, { recursive: true, force: true }); } catch { /* */ } };

const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
const s = (m, p) => cdp.send(m, p, sessionId);
await s('Page.enable'); await s('Runtime.enable'); await s('Network.enable'); await s('Log.enable');
await s('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

let mesajlar = [];
cdp.on((m) => {
  if (m.sessionId !== sessionId) return;
  if (m.method === 'Runtime.consoleAPICalled' && ['error', 'warning', 'assert'].includes(m.params.type)) {
    mesajlar.push(`${m.params.type}: ` + (m.params.args || []).map((a) => a.value ?? a.description ?? '').join(' '));
  } else if (m.method === 'Runtime.exceptionThrown') {
    const d = m.params.exceptionDetails; mesajlar.push('exception: ' + (d.exception?.description || d.text));
  } else if (m.method === 'Log.entryAdded' && ['error', 'warning'].includes(m.params.entry.level)) {
    mesajlar.push(`${m.params.entry.level}: ${m.params.entry.text} ${m.params.entry.url || ''}`);
  } else if (m.method === 'Network.responseReceived' && m.params.response.status >= 500 && m.params.response.url.startsWith(taban)) {
    mesajlar.push(`http ${m.params.response.status}: ${m.params.response.url}`);
  }
});

async function git(yol) {
  mesajlar = [];
  await s('Page.navigate', { url: taban + yol });
  await sleep(500);
  for (let i = 0; i < 40; i++) {                                           // yükleme + hydrate
    const r = await s('Runtime.evaluate', { expression: 'document.readyState', returnByValue: true });
    if (r.result.value === 'complete') break;
    await sleep(250);
  }
  await sleep(1800);
}
const degerlendir = async (ifade) => (await s('Runtime.evaluate', { expression: ifade, returnByValue: true, awaitPromise: true })).result.value;

async function girisYap(g) {
  await git(g.rota || '/login');
  for (const [sec, val] of Object.entries(g.doldur || {})) {
    await degerlendir(`(()=>{const e=document.querySelector(${JSON.stringify(sec)});if(!e)return;const d=Object.getOwnPropertyDescriptor(Object.getPrototypeOf(e),'value');d.set.call(e,${JSON.stringify(val)});e.dispatchEvent(new Event('input',{bubbles:true}));e.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  }
  if (g.tikla) await degerlendir(`document.querySelector(${JSON.stringify(g.tikla)})?.click()`);
  await sleep(2500);
}

const rotalar = (liste.rotalar && liste.rotalar.length) ? liste.rotalar : sayfalardanRotalar();
const goruntuDizin = path.join(ROOT, 'workspace/docs/ekran_goruntuleri');
fs.mkdirSync(goruntuDizin, { recursive: true });

const sonuc = [];
let uyari = [];
try {
  if (liste.giris) await girisYap(liste.giris);
  else uyari.push('`giris` tanımlı değil: giriş gerektiren rotalar login sayfasına yönlenir ve doğrulanamaz (workspace/uat_checklist.json → giris).');

  for (const rota of rotalar) {
    await git(rota);
    const son = await degerlendir('location.pathname');
    const yonlendi = son !== rota && !(rota === '/' && son === '/');
    const bilgi = await degerlendir(`(()=>({metin:(document.body?.innerText||'').trim().length,
      cati:${JSON.stringify(CATI)}.map(q=>!!document.querySelector(q)),
      baslik:document.title}))()`);
    const sorunlar = [];
    const temiz = mesajlar.filter((m) => !YOKSAY.some((r) => r.test(m)));
    for (const m of temiz) if (SORUN.test(m) || /^(error|exception|http)/.test(m)) sorunlar.push(temizMesaj(m));
    if (bilgi.metin < 5) sorunlar.push('sayfa boş (görünen metin yok)');
    const catiBeklenir = !HARIC.has(son) && !HARIC.has(rota);
    if (catiBeklenir) {
      bilgi.cati.forEach((var_, i) => { if (!var_) sorunlar.push(`çatı eksik: ${CATI[i]}`); });
    }
    let png = '';
    try {
      const { data } = await s('Page.captureScreenshot', { format: 'png' });
      png = path.join('workspace/docs/ekran_goruntuleri', `${slug(rota)}.png`);
      fs.writeFileSync(path.join(ROOT, png), Buffer.from(data, 'base64'));
    } catch { /* görüntü zorunlu değil */ }
    sonuc.push({ rota, son, yonlendi, sorunlar: [...new Set(sorunlar)].slice(0, 6), png });
    console.log(`  ${sorunlar.length ? '✗' : '✓'} ${rota}${yonlendi ? ` → ${son}` : ''}${sorunlar.length ? '  — ' + [...new Set(sorunlar)].slice(0, 2).join(' | ') : ''}`);
  }
} finally {
  await kapat();
}

const kalan = sonuc.filter((r) => r.sorunlar.length);
const yon = sonuc.filter((r) => r.yonlendi && !r.sorunlar.length).length;
if (yon && !liste.giris) uyari.push(`${yon} rota yönlendirildi (büyük olasılıkla oturum gerekiyor).`);
const md = [`# Render kapısı raporu`, '', `Taban: ${taban} · rota: ${sonuc.length} · başarısız: ${kalan.length}`, '',
  ...(uyari.length ? ['## Uyarılar', ...uyari.map((u) => `- ${u}`), ''] : []),
  '| Rota | Durum | Bulgular | Görüntü |', '|---|---|---|---|',
  ...sonuc.map((r) => `| \`${r.rota}\`${r.yonlendi ? ` → \`${r.son}\`` : ''} | ${r.sorunlar.length ? '✗' : '✓'} | ${r.sorunlar.map((x) => x.replace(/\|/g, '/')).join('<br>') || '-'} | ${r.png ? `![](${path.basename(r.png)})` : ''} |`), ''].join('\n');
fs.writeFileSync(path.join(ROOT, 'workspace/docs/render_raporu.md'), md);

for (const u of uyari) console.log(`  ⚠️  ${u}`);
console.log(`\n  Render kapısı: ${sonuc.length - kalan.length}/${sonuc.length} rota temiz — rapor: workspace/docs/render_raporu.md`);
process.exit(kalan.length ? 1 : 0);
