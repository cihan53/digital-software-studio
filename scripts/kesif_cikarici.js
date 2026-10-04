// Sayfa içi çıkarıcı (kesif_gezgin.mjs tarafından Runtime.evaluate ile enjekte edilir).
// Yalnızca OKUR; yazma yapmaz. window.__ks.extract() ve window.__ks.probe(etiket) tanımlar.
(() => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const txt = (e) => (e.innerText || e.getAttribute('aria-label') || e.title || '').trim().replace(/\s+/g, ' ').slice(0, 60);
  const uniq = (a) => [...new Set(a.filter(Boolean))];
  // Seçiciler studio.config.json → discovery.selectors ile gelir (window.__ks_cfg); varsayılanlar kütüphane-bağımsızdır.
  const SEL = Object.assign({
    content: 'main, [role=main], [class*="layout-content"]',
    dialog: '[role=dialog], [aria-modal=true], .modal.show, .ant-modal-wrap:not([style*="display: none"]) .ant-modal, .ant-drawer-open .ant-drawer-content',
    dialogClose: '[aria-label=Close], [aria-label=close], button.close, .ant-modal-close, .ant-drawer-close',
    dialogTitle: '[role=heading], .modal-title, .ant-modal-title, .ant-drawer-title, h1, h2, h3',
    widgetAttr: 'data-widget-id',
    widgetIgnore: '',   // proje gürültüsü: regex (örn. tema anahtarı widget id'leri)
    buttonIgnore: '',   // proje gürültüsü: regex (örn. tema düğmeleri)
  }, window.__ks_cfg || {});
  const rootEl = () => document.querySelector(SEL.content) || document.body;
  const NOISE_API = /\/assets\/|users\/me|widgets\/visibility|admin\/customization|admin\/features|user-settings|\/licence|\/version|users\/limitations/;
  const DIALOG = SEL.dialog;
  // Aday buton: GÖRÜNÜR ve herhangi bir dialog/modal İÇİNDE olmayan (dialog içi butonlar onay/gönder olabilir).
  const gorunur = (e) => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
  const dialogIci = (e) => !!e.closest('[role=dialog],[aria-modal=true],.modal,.ant-modal,.ant-drawer');
  const adayButonlar = (root) => [...root.querySelectorAll('button,[role=button],a.ant-btn')].filter((b) => gorunur(b) && !dialogIci(b));

  function desc(root) {
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = w.nextNode())) {
      const t = n.nodeValue.trim().replace(/\s+/g, ' ');
      const p = n.parentElement;
      if (t.length >= 40 && t.length <= 320 && p && !p.closest('button,th,td,a,label,nav,table,[role=tab]')) return t;
    }
    return '';
  }

  function extract() {
    const root = rootEl();
    const q = (s) => [...root.querySelectorAll(s)];
    const api = uniq(performance.getEntriesByType('resource')
      .filter((r) => ['xmlhttprequest', 'fetch'].includes(r.initiatorType))
      .map((r) => { try { return new URL(r.name).pathname.replace(/[0-9a-f]{24}/g, ':id').replace(/[0-9a-f]{8}-[0-9a-f-]{27}/g, ':id'); } catch (e) { return r.name; } })
      .filter((x) => !NOISE_API.test(x)));
    return {
      path: location.pathname + location.search,
      baslik: document.title,
      desc: desc(root),
      h: uniq(q('h1,h2,h3,h4,.ant-card-head-title').map(txt)).slice(0, 30),
      wid: uniq([...document.querySelectorAll('[' + SEL.widgetAttr + ']')].map((e) => e.getAttribute(SEL.widgetAttr)).filter((x) => !SEL.widgetIgnore || !new RegExp(SEL.widgetIgnore).test(x))),
      btn: uniq(adayButonlar(root).map(txt).filter((x) => !SEL.buttonIgnore || !new RegExp(SEL.buttonIgnore).test(x))).slice(0, 60),
      tabs: uniq([...document.querySelectorAll('[role=tab],.ant-tabs-tab')].map(txt)),
      th: uniq(q('th').map(txt)).slice(0, 40),
      inp: uniq(q('input,textarea').map((e) => e.placeholder || e.getAttribute('formcontrolname'))).slice(0, 25),
      sel: q('.ant-select').length,
      pick: q('.ant-picker').length,
      api,
      lk: uniq([...document.querySelectorAll('a[href]')].map((e) => e.getAttribute('href')).filter((h) => h && h.length > 1)).slice(0, 80),
      cv: q('canvas').length,
      tr: q('tbody tr').length,
      txt: root.innerText.replace(/\s+/g, ' ').slice(0, 400),
    };
  }

  // Etiketi verilen butona tıklar; modal/çekmece açılırsa içeriğini okur ve KAPATIR.
  // Etiket izni (yasak/izinli liste) çağıran tarafta (kesif_denetle) denetlenir.
  async function probe(label) {
    const root = rootEl();
    const btn = adayButonlar(root).find((b) => txt(b).toLowerCase() === label.toLowerCase());
    if (!btn) return { label, bulundu: false };
    const before = location.pathname;
    btn.click();
    await sleep(1200);
    if (location.pathname !== before) return { label, acildi: false, sayfaya_gitti: location.pathname };
    const gorunurDialog = () => [...document.querySelectorAll(DIALOG)].find(gorunur) || null;
    const dlg = gorunurDialog();
    if (!dlg) return { label, acildi: false };
    const r = {
      label, acildi: true,
      tur: dlg.closest('.ant-drawer') || /drawer/.test(dlg.className) ? 'drawer' : 'modal',
      baslik: txt(dlg.querySelector(SEL.dialogTitle) || dlg),
      alanlar: uniq([...dlg.querySelectorAll('label,.ant-form-item-label')].map(txt)).slice(0, 30),
      girdiler: uniq([...dlg.querySelectorAll('input,textarea')].map((e) => e.placeholder || e.getAttribute('formcontrolname') || e.type)).slice(0, 20),
      secimler: dlg.querySelectorAll('.ant-select').length,
      sekmeler: uniq([...dlg.querySelectorAll('[role=tab],.ant-steps-item-title')].map(txt)),
      butonlar: uniq([...dlg.querySelectorAll('button')].map(txt)),
      metin: dlg.innerText.replace(/\s+/g, ' ').slice(0, 240),
    };
    const x = (dlg.closest('.ant-modal-wrap,.ant-drawer,.modal') || dlg).querySelector(SEL.dialogClose);
    if (x) x.click(); else document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', keyCode: 27 }));
    await sleep(600);
    r.kapandi = !gorunurDialog();
    return r;
  }

  window.__ks = { extract, probe };
  return true;
})();
