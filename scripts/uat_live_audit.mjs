#!/usr/bin/env node
/**
 * Digital Software Studio — Genel UAT & Canlı Sistem Denetimi (projeden bağımsız).
 *
 * Varsayılan denetim: studio.config.json -> live.ports içindeki her porta GET / (500 altı yanıt = canlı).
 * Projeye özel denetimler: workspace/uat_checklist.json
 *   {"kontroller": [{"ad": "Giriş sayfası", "url": "http://localhost:3000/login", "durum": 200, "icerir": "Sign in"}]}
 * Daha ileri projeye özel senaryolar için workspace/scripts/uat_live_audit.mjs yazın (aynı adlı betik bunun yerine geçer).
 * Çıkış kodu: tümü geçtiyse 0, aksi halde 1.
 */
import fs from 'fs';
import http from 'http';
import path from 'path';
import { fileURLToPath } from 'url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const C = { g: '\x1b[32m', r: '\x1b[31m', c: '\x1b[36m', x: '\x1b[0m' };

function oku(rel, varsayilan) {
  try { return JSON.parse(fs.readFileSync(path.join(ROOT, rel), 'utf8')); } catch { return varsayilan; }
}

function istek(url) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const req = http.request({ hostname: u.hostname, port: u.port, path: u.pathname + u.search, method: 'GET', timeout: 5000 }, (res) => {
      let veri = '';
      res.on('data', (d) => (veri += d));
      res.on('end', () => resolve({ durum: res.statusCode, govde: veri }));
    });
    req.on('error', reject);
    req.on('timeout', () => { req.destroy(); reject(new Error('zaman aşımı (5000ms)')); });
    req.end();
  });
}

async function dene(url) {            // localhost hem IPv4 hem IPv6 olabilir
  let hata;
  for (const h of [url, url.replace('localhost', '127.0.0.1'), url.replace('localhost', '[::1]')]) {
    try { return await istek(h); } catch (e) { hata = e; }
  }
  throw hata;
}

const cfg = oku('workspace/studio.config.json', {});
const portlar = ((cfg.live || {}).ports || [3000]);
const ek = (oku('workspace/uat_checklist.json', {}).kontroller || []);
const kontroller = [
  ...portlar.map((p) => ({ ad: `Port ${p} canlı`, url: `http://localhost:${p}/`, altinda: 500 })),
  ...ek,
];

console.log(`${C.c}══ Canlı UAT denetimi (${kontroller.length} kontrol) ══${C.x}`);
let gecen = 0, kalan = 0;
for (const k of kontroller) {
  process.stdout.write(`  [TEST] ${k.ad} ... `);
  try {
    const r = await dene(k.url);
    if (k.durum && r.durum !== k.durum) throw new Error(`durum ${r.durum}, beklenen ${k.durum}`);
    if (k.altinda && r.durum >= k.altinda) throw new Error(`durum ${r.durum} (beklenen <${k.altinda})`);
    if (k.icerir && !r.govde.includes(k.icerir)) throw new Error(`yanıt "${k.icerir}" içermiyor`);
    console.log(`${C.g}✓ GEÇTİ${C.x}`);
    gecen++;
  } catch (e) {
    console.log(`${C.r}✗ BAŞARISIZ${C.x}\n         ${C.r}Hata: ${e.message}${C.x}`);
    kalan++;
  }
}
console.log(`\n  Sonuç: ${gecen} geçti, ${kalan} başarısız`);
process.exit(kalan ? 1 : 0);
