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

// ---------- tanı: çözülemeyen bileşenler ----------
function bilesenDosyalari() {
  const kok = path.join(ROOT, appDizin, 'app', 'components');
  const alt = path.join(ROOT, appDizin, 'components');
  const out = [];
  const gez = (d, taban) => {
    if (!fs.existsSync(d)) return;
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      if (e.isDirectory()) gez(path.join(d, e.name), taban);
      else if (/\.vue$/.test(e.name)) out.push({ ad: e.name.replace(/\.vue$/, ''), rel: path.relative(path.join(ROOT), path.join(d, e.name)), dir: path.relative(taban, d) });
    }
  };
  gez(kok, kok); gez(alt, alt);
  return out;
}
const pascal = (s) => s.split(/[\\/_-]/).filter(Boolean).map((x) => x[0].toUpperCase() + x.slice(1)).join('');
function tani(cozulemeyen) {
  const dosyalar = bilesenDosyalari();
  const satirlar = [];
  for (const ad of cozulemeyen) {
    const f = dosyalar.find((d) => d.ad === ad);
    if (f && f.dir) satirlar.push(`- ${ad} → ${f.rel}: Nuxt bunu \`${pascal(f.dir)}${ad}\` adıyla kaydeder (klasör ön eki); \`<${ad}>\` olarak kullanılamaz.`);
    else if (f) satirlar.push(`- ${ad} → ${f.rel}: dosya var ama bileşen çözülemiyor (dev sunucuyu yeniden başlatın ya da \`nuxt prepare\`).`);
    else satirlar.push(`- ${ad}: bu adla bir .vue dosyası bulunamadı (dosya eksik ya da ad uyuşmuyor).`);
  }
  const onekli = satirlar.some((x) => x.includes('klasör ön eki'));
  const yapilandirma = ['ts', 'js', 'mjs'].map((e) => path.join(appDizin, `nuxt.config.${e}`)).find((p) => fs.existsSync(path.join(ROOT, p)));
  return [...(onekli && yapilandirma ? [`Düzeltilecek dosya: ${yapilandirma}`] : []),
    `Çözülemeyen bileşenler (${cozulemeyen.length}): ${cozulemeyen.join(', ')}`, ...satirlar,
    ...(onekli ? ['Tek seferde çözüm: nuxt.config içinde `components: [{ path: \'~/components\', pathPrefix: false }]` (klasör adı ön ek olmaz); tek tek takma ad dosyası yazmayın.'] : [])];
}

// ---------- mock tohumundan test hesabı ----------
function tohumKimlik() {
  const app = path.join(ROOT, appDizin);
  const adaylar = [];
  const gez = (d) => {
    if (!fs.existsSync(d)) return;
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      if (['node_modules', '.nuxt', '.output', 'dist', '.git'].includes(e.name)) continue;
      const p = path.join(d, e.name);
      if (e.isDirectory()) gez(p);
      else if (/\.(ts|js|mjs|json)$/.test(e.name) && !/\.(test|spec)\./.test(e.name)) adaylar.push(p);
    }
  };
  gez(app);
  adaylar.sort((a, b) => (/mock|seed|fixture/i.test(b) ? 1 : 0) - (/mock|seed|fixture/i.test(a) ? 1 : 0));
  const rx = /(?:username|email|user|login)['"]?\s*[:=]\s*['"]([^'"\n]{1,80})['"][\s\S]{0,240}?password['"]?\s*[:=]\s*['"]([^'"\n]{1,80})['"]/;
  for (const f of adaylar) {
    let m; try { m = rx.exec(fs.readFileSync(f, 'utf8')); } catch { continue; }
    if (m) return { kullanici: m[1], parola: m[2], kaynak: path.relative(ROOT, f) };
  }
  return null;
}

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

async function otomatikGiris(uyari) {
  const k = tohumKimlik();
  if (!k) { uyari.push('`giris` tanımsız ve mock tohum dosyasında test hesabı bulunamadı: korumalı rotalar doğrulanamadı (workspace/uat_checklist.json → giris).'); return false; }
  await git('/login');
  let sel = null;
  for (let i = 0; i < 24 && !sel; i++) {                          // SPA (ssr:false): form istemcide çizilir; hazır olana dek bekle (#231)
    if (i) await sleep(500);
    sel = await degerlendir(`(()=>{const q=(s)=>document.querySelector(s);
    const u=q('input[name=username],input[name=email],input[type=email],input[autocomplete=username],input[type=text]');
    const p=q('input[type=password]'); if(!u||!p) return null;
    const t=(e)=>e.name?'input[name="'+e.name+'"]':(e.id?'#'+e.id:null);
    return {u:t(u),p:t(p),b:q('button[type=submit]')?'button[type=submit]':null};})()`);
  }
  if (!sel || !sel.u || !sel.p) { uyari.push('Otomatik giriş: /login sayfasında kullanıcı/parola alanı bulunamadı.'); return false; }
  await girisYap({ rota: '/login', doldur: { [sel.u]: k.kullanici, [sel.p]: k.parola }, tikla: sel.b });
  const son = await degerlendir('location.pathname');
  if (son.startsWith('/login')) { uyari.push(`Otomatik giriş başarısız (${k.kullanici}, kaynak: ${k.kaynak}).`); return false; }
  uyari.push(`Otomatik giriş yapıldı: ${k.kullanici} (kaynak: ${k.kaynak}).`);
  return true;
}

const rotalar = (liste.rotalar && liste.rotalar.length) ? liste.rotalar : sayfalardanRotalar();
const goruntuDizin = path.join(ROOT, 'workspace/docs/ekran_goruntuleri');
fs.mkdirSync(goruntuDizin, { recursive: true });

const sonuc = [];
let karsilama = false;                                            // çerçevenin karşılama sayfası: uygulama değil ORTAM bozuk (#229)
const cozulemeyen = new Set();
const sunucuHatalari = new Map();                                // hata iletisi -> etkilenen rota sayısı
let uyari = [];
try {
  if (liste.giris) await girisYap(liste.giris);
  else await otomatikGiris(uyari);

  for (const rota of rotalar) {
    await git(rota);
    const son = await degerlendir('location.pathname');
    const yonlendi = son !== rota && !(rota === '/' && son === '/');
    const bilgi = await degerlendir(`(()=>({metin:(document.body?.innerText||'').trim().length,
      cati:${JSON.stringify(CATI)}.map(q=>!!document.querySelector(q)),
      baslik:document.title}))()`);
    const sorunlar = [];
    const temiz = mesajlar.filter((m) => !YOKSAY.some((r) => r.test(m)));
    for (const m of temiz) for (const x of m.matchAll(/Failed to resolve component: ([A-Za-z0-9_]+)/g)) cozulemeyen.add(x[1]);
    for (const m of temiz) if (SORUN.test(m) || /^(error|exception|http)/.test(m)) sorunlar.push(temizMesaj(m));
    if (await degerlendir(`/Welcome to Nuxt|nuxt-welcome/i.test(document.body?.innerText||'')||!!document.querySelector('[class*=nuxt-welcome],#__nuxt .nuxt-welcome')`)) karsilama = true;
    if (temiz.some((m) => /^http 5\d\d/.test(m))) {                     // 5xx: Nuxt hata sayfasındaki neden (örn. "useX is not defined") bulguya eklenir (#235)
      const neden = await degerlendir(`(document.body?.innerText||'').replace(/\\s+/g,' ').trim().slice(0,220)`);
      if (neden && neden.length > 3) { sorunlar.push(`sunucu hatası: ${neden}`); sunucuHatalari.set(neden, (sunucuHatalari.get(neden) || 0) + 1); }
    }
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

if (karsilama) {
  console.log('\n  ⚠️  ORTAM HATALI: uygulama değil çerçevenin karşılama sayfası ("Welcome to Nuxt") servis ediliyor.');
  console.log('      Olası nedenler: dev sunucu yanlış argümanla başlatılmış (örn. `nuxt dev -- --port N`: `--port` proje dizini sanılır),');
  console.log('      sunucu yanlış dizinde çalışıyor ya da uygulama dizininde app.vue/pages bulunamıyor. yerel_ortam.sh başlatma komutunu düzeltin;');
  console.log('      sayfa içeriği doğrulanamadığı için render kapısı atlandı (talep açılmaz).');
  process.exit(3);
}
const kalan = sonuc.filter((r) => r.sorunlar.length);
const yon = sonuc.filter((r) => r.yonlendi && !r.sorunlar.length).length;
if (yon && !liste.giris) uyari.push(`${yon} rota yönlendirildi (büyük olasılıkla oturum gerekiyor).`);
const taniSatirlar = [
  ...(cozulemeyen.size ? tani([...cozulemeyen]) : []),
  ...[...sunucuHatalari].map(([m, n]) => `Sunucu hatası (${n} rota): ${m} — nedeni kaynak kodda bul (tanımsız ad/import, eksik dosya).`),
];
const md = [`# Render kapısı raporu`, '', `Taban: ${taban} · rota: ${sonuc.length} · başarısız: ${kalan.length}`, '',
  ...(taniSatirlar.length ? ['## Tanı', ...taniSatirlar, ''] : []),
  ...(uyari.length ? ['## Uyarılar', ...uyari.map((u) => `- ${u}`), ''] : []),
  '| Rota | Durum | Bulgular | Görüntü |', '|---|---|---|---|',
  ...sonuc.map((r) => `| \`${r.rota}\`${r.yonlendi ? ` → \`${r.son}\`` : ''} | ${r.sorunlar.length ? '✗' : '✓'} | ${r.sorunlar.map((x) => x.replace(/\|/g, '/')).join('<br>') || '-'} | ${r.png ? `![](${path.basename(r.png)})` : ''} |`), ''].join('\n');
fs.writeFileSync(path.join(ROOT, 'workspace/docs/render_raporu.md'), md);

for (const u of uyari) console.log(`  ⚠️  ${u}`);
if (taniSatirlar.length) { console.log('\n  TANI:'); taniSatirlar.forEach((t) => console.log('  ' + t)); }
console.log(`\n  Render kapısı: ${sonuc.length - kalan.length}/${sonuc.length} rota temiz — rapor: workspace/docs/render_raporu.md`);
process.exit(kalan.length ? 1 : 0);
