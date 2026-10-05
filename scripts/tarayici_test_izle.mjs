#!/usr/bin/env node
/**
 * Digital Software Studio — Canlı Tarayıcı Ziyaretçi Test İzleyicisi (projeden bağımsız).
 *
 * Gerçek bir Chrome penceresi açar ve rotaları insan gözünün izleyebileceği hızda gezer; konsol hatalarını sayar.
 * Portlar: studio.config.json -> live.ports[0]. Rotalar: workspace/uat_checklist.json -> "rotalar" (varsayılan ["/"]).
 *   {"rotalar": ["/", "/login"], "tiklamalar": [{"rota": "/", "secici": "button:has-text('Sign in')"}]}
 * Projeye özel senaryo için workspace/scripts/tarayici_test_izle.mjs yazın (basla.sh --test-izle önce onu çalıştırır).
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const C = { g: '\x1b[32m', r: '\x1b[31m', y: '\x1b[33m', c: '\x1b[36m', b: '\x1b[1m', x: '\x1b[0m' };
const oku = (rel, v) => { try { return JSON.parse(fs.readFileSync(path.join(ROOT, rel), 'utf8')); } catch { return v; } };

const cfg = oku('workspace/studio.config.json', {});
const port = ((cfg.live || {}).ports || [3000])[0];
const liste = oku('workspace/uat_checklist.json', {});
const rotalar = liste.rotalar && liste.rotalar.length ? liste.rotalar : ['/'];
const tiklamalar = liste.tiklamalar || [];

let playwright;
for (const kaynak of [
  path.join(ROOT, 'workspace/src/web/node_modules/playwright/index.mjs'),
  'playwright',
]) {
  try { playwright = await import(kaynak.startsWith('/') ? 'file://' + kaynak : kaynak); break; } catch { /* sonraki */ }
}
if (!playwright) { console.error(`${C.r}✗ Playwright bulunamadı (uygulama dizininde kurun).${C.x}`); process.exit(1); }

const { chromium } = playwright;
let tabanUrl = null;
for (const h of ['localhost', '127.0.0.1', '[::1]']) {
  try { const r = await fetch(`http://${h}:${port}/`); if (r.status < 500) { tabanUrl = `http://${h}:${port}`; break; } } catch { /* sonraki */ }
}
if (!tabanUrl) {
  console.log(`${C.y}⚠️  Sistem canlı değil (port ${port} kapalı).${C.x}\n   Önce yerel ortamı başlatın: ${C.g}./workspace/yerel_ortam.sh${C.x} (ya da panel → 🖥 Yerel Ortam)`);
  process.exit(1);
}

console.log(`${C.c}${C.b}🎬 Canlı ziyaretçi testi — ${tabanUrl} (${rotalar.length} rota)${C.x}`);
const browser = await chromium.launch({ headless: false, slowMo: 600, args: ['--window-size=1366,860'] });
const page = await (await browser.newContext({ viewport: { width: 1366, height: 860 } })).newPage();
const hatalar = [];
page.on('console', (m) => { if (m.type() === 'error') hatalar.push(m.text()); });
page.on('pageerror', (e) => hatalar.push(e.message));

try {
  for (const rota of rotalar) {
    console.log(`  👉 ${rota}`);
    await page.goto(tabanUrl + rota, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1200);
    for (const t of tiklamalar.filter((x) => x.rota === rota)) {
      const el = await page.$(t.secici);
      console.log(`     ${el ? '🖱️ ' : '⚠️  bulunamadı: '}${t.secici}`);
      if (el) { await el.click(); await page.waitForTimeout(900); }
    }
  }
  const tamam = hatalar.length === 0;
  console.log(`\n${tamam ? C.g : C.y}${C.b}${tamam ? '🎉 Gezi tamamlandı, konsol hatası yok.' : `⚠️  Gezi tamamlandı, ${hatalar.length} konsol hatası:`}${C.x}`);
  hatalar.slice(0, 8).forEach((h) => console.log('   -', h.slice(0, 160)));
  await page.waitForTimeout(2500);
} catch (e) {
  console.error(`\n${C.r}✗ Test sırasında hata: ${e.message}${C.x}`);
  process.exitCode = 1;
} finally {
  await browser.close();
}
