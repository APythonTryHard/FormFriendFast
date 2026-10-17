// Focused simulated DOM + IndexedDB implementation; fictional files, mocked fetch only.
// Run with fake-indexeddb available on NODE_PATH (temporary install is sufficient).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { IDBFactory } = require('fake-indexeddb');
const source = fs.readFileSync('static/app.js', 'utf8');
class Element {
  constructor() { this.hidden = true; this.value = ''; this.children = []; this.dataset = {}; this.style = {}; this.listeners = {}; this.classList = { toggle() {}, add() {}, remove() {} }; }
  addEventListener(type, handler) { this.listeners[type] = handler; }
  querySelector() { return new Element(); }
  setAttribute(key, value) { this[key] = value; }
  removeAttribute(key) { delete this[key]; }
  replaceChildren() { this.children = []; }
  append(...children) { this.children.push(...children); }
  scrollIntoView() {}
}
function boot(indexedDB = new IDBFactory(), preferences = new Map(), extra = {}) {
  const elements = new Map();
  const document = { querySelector(s) { if (!elements.has(s)) elements.set(s, new Element()); return elements.get(s); }, querySelectorAll() { return []; }, createElement() { return new Element(); } };
  document.querySelector('#language-select').options = ['en', 'es', 'ar', 'fr'].map(value => ({ value }));
  const calls = [];
  const context = vm.createContext({ document, indexedDB, AbortController, FormData, Blob, File, structuredClone, console,
    localStorage: { getItem(k) { return preferences.get(k) || null; }, setItem(k, v) { preferences.set(k, v); } },
    URL: { createObjectURL() { return 'blob:fictional'; }, revokeObjectURL() {} }, window: { addEventListener() {} },
    fetch(url, options) { return new Promise(resolve => calls.push({ url, options, resolve })); }, ...extra });
  vm.runInContext(source, context);
  return { context, calls, el: s => document.querySelector(s), run: code => vm.runInContext(code, context), change(value) { document.querySelector('#language-select').value = value; document.querySelector('#language-select').listeners.change(); } };
}
const flush = async () => { for (let i = 0; i < 25; i++) await new Promise(resolve => setImmediate(resolve)); };
const fields = [{ id: 0, label: 'Fictional name', guidance: 'Enter name', box: [1, 2, 3, 4] }, { id: 1, label: 'Fictional city', guidance: 'Enter city', box: [5, 6, 7, 8] }];
const reply = (call, result) => call.resolve({ ok: true, json: async () => result });
async function main() {
  const idb = new IDBFactory(), prefs = new Map([['formfriend-language', 'unsupported']]);
  let page = boot(idb, prefs);
  await flush();
  assert.equal(page.el('#language-select').value, 'en', 'Invalid saved language falls back to English');
  page.context.file = new File(['fictional'], 'fictional.png', { type: 'image/png' });
  page.run('analyze(file)');
  reply(page.calls[0], { fields });
  await flush();
  page.run('selectField(1); explainSelectedField()');
  reply(page.calls[1], { lines: ['Fictional line one', 'Fictional line two', 'Fictional line three'] });
  await flush();
  page = boot(idb, prefs);
  await flush();
  assert.equal(page.el('#result-state').hidden, false, 'Reload restores saved successful form');
  assert.equal(page.calls.length, 0, 'Cached reload must not call provider');
  assert.match(page.el('#explain-label').textContent, /Fictional city/);
  assert.equal(page.el('#explanation').hidden, false);
  assert.equal(page.el('#form-preview').src, 'blob:fictional');
  page.run('explainSelectedField()');
  assert.equal(page.calls.length, 0, 'Cached explanation avoids provider');
  page.change('es');
  assert.equal(page.calls.length, 1);
  reply(page.calls[0], { fields: [{ ...fields[0], label: 'Nombre ficticio' }] });
  await flush();
  page.change('en');
  assert.equal(page.calls.length, 1, 'Switch back uses successful language cache');
  assert.match(page.el('#explain-label').textContent, /Fictional city/);
  page.change('fr');
  assert.equal(page.calls.length, 2);
  await flush();
  let restarted = boot(idb, prefs);
  await flush();
  assert.equal(restarted.calls.length, 1, 'Reload restarts uncached pending analysis');
  assert.equal(restarted.calls[0].options.body.get('language'), 'fr');
  restarted.run('clear()');
  reply(restarted.calls[0], { fields });
  await flush();
  page = boot(idb, prefs); await flush();
  assert.equal(page.calls.length, 0);
  assert.equal(page.el('#result-state').hidden, true, 'Reset clears document despite late response');
  assert.equal(page.el('#language-select').value, 'fr', 'Reset keeps language');
  console.log('PASS: cached reload, image, selection, explanations, language cache, pending restart, reset and stale response');
  // A fresh upload while database opening must win over the stored document.
  page.context.file = new File(['old fictional'], 'old.png', { type: 'image/png' });
  page.run('analyze(file)'); reply(page.calls[0], { fields }); await flush();
  const replacing = boot(idb, prefs);
  replacing.context.file = new File(['new fictional'], 'new.png', { type: 'image/png' });
  replacing.run('analyze(file)');
  reply(replacing.calls[0], { fields: [{ ...fields[0], label: 'Replacement' }] }); await flush();
  page = boot(idb, prefs); await flush();
  assert.equal(page.calls.length, 0);
  assert.equal(page.el('#filename').textContent, 'new.png');
  assert.match(page.el('#explain-label').textContent, /Replacement/);
  page.change('en');
  assert.equal(page.calls.length, 1, 'New upload discards previous language caches');
  page.run('clear()'); await flush();
  const resetting = boot(idb, prefs); resetting.run('clear()'); await flush();
  const after = boot(idb, prefs); await flush();
  assert.equal(after.el('#result-state').hidden, true);
  console.log('PASS: new upload replaces cache, opening restore/upload/reset races, queued clear');
  const broken = boot(undefined, new Map(), { indexedDB: { open() { throw new Error('unavailable'); } }, localStorage: { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } } });
  await flush();
  broken.context.file = new File(['fictional'], 'fictional.png', { type: 'image/png' });
  broken.run('analyze(file)'); reply(broken.calls[0], { fields }); await flush();
  assert.equal(broken.el('#result-state').hidden, false);
  assert.equal(broken.el('#storage-notice').hidden, false);
  broken.change('es'); assert.equal(broken.calls.length, 2);
  console.log('PASS: unavailable browser storage reports truthfully without blocking analysis');
  const cloneFailure = boot(new IDBFactory(), new Map(), { structuredClone() { throw new Error('DataCloneError'); } });
  await flush();
  cloneFailure.context.file = new File(['fictional'], 'fictional.png', { type: 'image/png' });
  cloneFailure.run('analyze(file)');
  assert.equal(cloneFailure.calls.length, 1, 'Snapshot errors must not block inference');
  reply(cloneFailure.calls[0], { fields }); await flush();
  assert.equal(cloneFailure.el('#result-state').hidden, false);
  assert.equal(cloneFailure.el('#storage-notice').hidden, false);
  console.log('PASS: storage snapshot failures do not block analysis');
}
if (require.main === module) main().catch(err => { console.error(err); process.exitCode = 1; });
module.exports = { main, boot, flush, fields, reply };
