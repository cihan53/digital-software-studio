#!/usr/bin/env node
/**
 * API yanıt şeması çıkarımı (issue #136) — DEĞER SAKLAMAZ, yalnızca alan adı ve tip.
 * İstisna: anahtar adı sözlük/durum benzeri (status, type, severity, level, role ...) olan kısa string
 * alanlarda en çok 12 farklı kısa değer `enum` olarak tutulur (mock'un gerçekçi kalması için).
 *
 * Kütüphane: infer(value) → şema, merge(a, b) → birleşik şema, normPath(path) → kimlikleri :id yapar.
 * CLI (test/deneme): echo '{"a":1}' | node scripts/kesif_sema.mjs
 */
const ENUM_KEY = /(status|state|type|kind|severity|level|role|category|priority|interval|mode|result|granularity|unit|direction)$/i;
const SAFE_ENUM = /^[A-Za-z0-9_. -]{1,32}$/;

export function normPath(p) {
  return p.replace(/[0-9a-f]{24}/gi, ':id').replace(/[0-9a-f]{8}-[0-9a-f-]{27}/gi, ':id').replace(/\/\d+(?=\/|$)/g, '/:id');
}

function strFormat(s) {
  if (/^\d{4}-\d\d-\d\d([T ]\d\d:\d\d(:\d\d(\.\d+)?)?(Z|[+-]\d\d:?\d\d)?)?$/.test(s)) return 'date-time';
  if (/^[0-9a-f]{8}-[0-9a-f-]{27}$/i.test(s) || /^[0-9a-f]{24}$/i.test(s)) return 'id';
  if (/^[^@\s]+@[^@\s]+\.[a-z]{2,}$/i.test(s)) return 'email';
  if (/^https?:\/\//.test(s)) return 'url';
  return 'string';
}

export function infer(v, key = '') {
  if (v === null) return 'null';
  if (typeof v === 'boolean') return 'boolean';
  if (typeof v === 'number') return Number.isInteger(v) ? 'integer' : 'number';
  if (typeof v === 'string') {
    const f = strFormat(v);
    if (f === 'string' && ENUM_KEY.test(key) && SAFE_ENUM.test(v)) return { type: 'string', enum: [v] };
    return f;
  }
  if (Array.isArray(v)) {
    let item = null;
    for (const x of v.slice(0, 20)) item = item === null ? infer(x, key) : merge(item, infer(x, key));
    return { array: item === null ? 'unknown' : item };
  }
  if (typeof v === 'object') {
    const o = {};
    for (const [k, x] of Object.entries(v)) o[k] = infer(x, k);
    return { object: o };
  }
  return 'unknown';
}

const typeOf = (s) => (typeof s === 'string' ? s : s.array !== undefined ? 'array' : s.object !== undefined ? 'object' : s.type);

export function merge(a, b) {
  if (a === undefined) return b;
  if (b === undefined) return a;
  const ta = typeOf(a), tb = typeOf(b);
  if (ta === 'object' && tb === 'object') {
    const o = {};
    const keys = new Set([...Object.keys(a.object), ...Object.keys(b.object)]);
    for (const k of keys) {
      const inA = k in a.object, inB = k in b.object;
      const m = merge(a.object[k], b.object[k]);
      o[inA && inB ? k : k.replace(/\??$/, '?')] = m;
    }
    return { object: o };
  }
  if (ta === 'array' && tb === 'array') return { array: merge(a.array, b.array) };
  if (ta === 'string' && tb === 'string' && typeof a === 'object' && typeof b === 'object') {
    const e = [...new Set([...(a.enum || []), ...(b.enum || [])])];
    return e.length > 12 ? 'string' : { type: 'string', enum: e };
  }
  if (ta === tb) return a;
  const an = typeof a === 'string' ? a : ta, bn = typeof b === 'string' ? b : tb;   // farklı tipler: birleşim
  return [...new Set([...an.split('|'), ...bn.split('|')])].sort().join('|');
}

if (process.argv[1] && process.argv[1].endsWith('kesif_sema.mjs') && !process.stdin.isTTY) {
  let d = '';
  process.stdin.on('data', (c) => (d += c));
  process.stdin.on('end', () => console.log(JSON.stringify(infer(JSON.parse(d)))));
}
