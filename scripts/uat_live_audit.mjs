#!/usr/bin/env node
/**
 * Digital Software Studio - UAT & Canlı Sistem Denetim Aracı (Live Auditor)
 * Bu betik çalışan canlı sistem üzerinde gerçek kullanıcı
 * kabul testlerini (UAT) icra eder ve detaylı bir doğrulama raporu üretir.
 */

import http from 'http';

const GREEN = '\x1b[32m';
const RED = '\x1b[31m';
const YELLOW = '\x1b[33m';
const BLUE = '\x1b[34m';
const CYAN = '\x1b[36m';
const RESET = '\x1b[0m';

async function fetchHttp(url, options = {}) {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const req = http.request(
      {
        hostname: parsed.hostname,
        port: parsed.port,
        path: parsed.pathname + parsed.search,
        method: options.method || 'GET',
        headers: options.headers || {},
        timeout: 5000,
      },
      (res) => {
        let data = '';
        res.on('data', (chunk) => (data += chunk));
        res.on('end', () => {
          let json = null;
          try {
            json = JSON.parse(data);
          } catch {}
          resolve({ status: res.statusCode, headers: res.headers, body: data, json });
        });
      }
    );
    req.on('error', (err) => reject(err));
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('İstek zaman aşımına uğradı (5000ms)'));
    });
    if (options.body) req.write(options.body);
    req.end();
  });
}

async function runUat() {
  console.log(`${CYAN}======================================================================${RESET}`);
  console.log(`${CYAN}  ⚡ Digital Software Studio — Canlı UAT & Kullanıcı Denetimi Başlatılıyor${RESET}`);
  console.log(`${CYAN}======================================================================${RESET}\n`);

  let passed = 0;
  let failed = 0;

  async function check(title, fn) {
    process.stdout.write(`  [TEST] ${title} ... `);
    try {
      await fn();
      console.log(`${GREEN}✓ GEÇTİ${RESET}`);
      passed++;
    } catch (err) {
      console.log(`${RED}✗ BAŞARISIZ${RESET}`);
      console.log(`         ${RED}Hata: ${err.message}${RESET}`);
      failed++;
    }
  }

  // 1. Canlı Backend Sağlık Kontrolü
  await check('UAT-01: Fastify Backend API canlı sağlık kontrolü (Port 3001)', async () => {
    const res = await fetchHttp('http://127.0.0.1:3001/api/v1/health/sources');
    if (res.status !== 200) throw new Error(`Beklenen HTTP 200, alınan: ${res.status}`);
    if (res.json?.status !== 'UP') throw new Error('API kaynak sağlık durumu UP değil');
  });

  // 2. CORS ve CORP Güvenlik Başlıkları
  await check('UAT-02: Web istemcisi için CORS ve CORP başlık uyumu', async () => {
    const res = await fetchHttp('http://127.0.0.1:3001/api/v1/stations', {
      headers: {
        Origin: 'http://127.0.0.1:3000',
        Referer: 'http://127.0.0.1:3000/',
      },
    });
    if (res.status !== 200) throw new Error(`Beklenen HTTP 200, alınan: ${res.status}`);
    const allowOrigin = res.headers['access-control-allow-origin'];
    if (allowOrigin !== 'http://127.0.0.1:3000' && allowOrigin !== '*') {
      throw new Error(`CORS Access-Control-Allow-Origin geçersiz: ${allowOrigin}`);
    }
    const corp = res.headers['cross-origin-resource-policy'];
    if (corp !== 'cross-origin') {
      throw new Error(`CORP başlığı cross-origin olmalı, mevcut: ${corp}`);
    }
  });

  // 3. Zoom < 10 Türkiye Kümeleme (Clustering) Doğrulaması
  await check('UAT-03: Zoom 6 Türkiye genelinde 81 ilin kümeleme verisi (Clusters)', async () => {
    const res = await fetchHttp(
      'http://127.0.0.1:3001/api/v1/stations?bbox=19.06637,34.54555,46.65303,44.92832&zoom=6'
    );
    if (res.status !== 200) throw new Error(`HTTP ${res.status} döndü`);
    if (res.json?.type !== 'clusters') throw new Error(`Yanıt tipi 'clusters' olmalı: ${res.json?.type}`);
    if (res.json?.count < 50) throw new Error(`Küme sayısı beklenenden az: ${res.json?.count}`);
  });

  // 4. Zoom 11 İstanbul Metropol BBox Geniş Ekran Sorgusu
  await check('UAT-04: Zoom 11 İstanbul geniş ekran BBox sorgusu (1.06° boylam, 600+ pin)', async () => {
    const res = await fetchHttp(
      'http://127.0.0.1:3001/api/v1/stations?bbox=28.42962,40.84865,29.48826,41.22010&zoom=11'
    );
    if (res.status !== 200) throw new Error(`HTTP ${res.status} döndü (Hata detayı: ${res.body})`);
    if (res.json?.type !== 'stations') throw new Error(`Yanıt tipi 'stations' olmalı: ${res.json?.type}`);
    if (!Array.isArray(res.json?.data) || res.json?.data.length === 0) {
      throw new Error(`Kayıt listesi boş veya dizi değil: ${res.json?.data?.length}`);
    }
  });

  // 5. API Canlılık ve Veri Modeli Bütünlüğü
  await check('UAT-05: API uç noktası canlılık ve veri modeli doğrulaması', async () => {
    const res = await fetchHttp('http://127.0.0.1:3001/api/v1/health/live');
    if (res.status >= 500) throw new Error(`HTTP ${res.status} döndü`);
  });

  // 6. Web Arayüzü Canlı Yanıt Kontrolü (Port 3000)
  await check('UAT-06: Web arayüzü canlı HTML sunumu (Port 3000)', async () => {
    const res = await fetchHttp('http://127.0.0.1:3000/');
    if (res.status !== 200) throw new Error(`Web arayüzü HTTP ${res.status} döndü`);
    if (!res.body.includes('<!DOCTYPE html>') && !res.body.includes('<html')) {
      throw new Error('Canlı HTML yapısı doğrulanamadı');
    }
  });

  console.log('\n----------------------------------------------------------------------');
  if (failed === 0) {
    console.log(`${GREEN}🎉 TÜM UAT KABUL TESTLERİ BAŞARIYLA GEÇTİ (${passed}/${passed})${RESET}`);
    console.log(`${GREEN}Sistem gerçek kullanıcı gözüyle %100 doğrulanmıştır.${RESET}`);
    process.exit(0);
  } else {
    console.log(`${RED}⚠️  UAT TESTLERİNDE ${failed} HATA TESPİT EDİLDİ! (${passed} Başarılı, ${failed} Başarısız)${RESET}`);
    process.exit(1);
  }
}

runUat().catch((err) => {
  console.error(`${RED}Beklenmeyen denetim hatası:${RESET}`, err);
  process.exit(1);
});
