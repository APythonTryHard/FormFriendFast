// Focused simulated-DOM check; no live provider requests.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
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
const elements = new Map();
const document = {
  querySelector(selector) { if (!elements.has(selector)) elements.set(selector, new Element()); return elements.get(selector); },
  querySelectorAll() { return []; },
  createElement() { return new Element(); },
};
const calls = [];
const preferences = new Map();
document.querySelector('#language-select').options = ['en', 'es', 'ar', 'fr'].map(value => ({ value }));
const context = vm.createContext({ document, AbortController, FormData, structuredClone, console,
  localStorage: { getItem(key) { return preferences.get(key) || null; }, setItem(key, value) { preferences.set(key, value); } },
  URL: { createObjectURL() { return 'blob:fictional'; }, revokeObjectURL() {} },
  window: { addEventListener() {} },
  fetch(url, options) { return new Promise(resolve => calls.push({ url, options, resolve })); },
});
vm.runInContext(fs.readFileSync('static/app.js', 'utf8'), context);
const run = code => vm.runInContext(code, context);
const flush = () => new Promise(resolve => setImmediate(resolve));
const reply = (call, json) => call.resolve({ ok: true, json: async () => json });
(async () => {
  document.querySelector('#language-select').value = 'es';
  context.file = new File(['fictional'], 'form.png', { type: 'image/png' });
  run('analyze(file)');
  assert.equal(calls[0].options.body.get('language'), 'es');
  document.querySelector('#language-select').value = 'ar';
  document.querySelector('#language-select').listeners.change();
  assert.equal(preferences.get('formfriend-language'), 'ar', 'Language preference must persist');
  assert.equal(calls.length, 2);
  assert.equal(calls[1].options.body.get('language'), 'ar');
  assert.equal(calls[0].options.signal.aborted, true);
  reply(calls[0], { fields: [{ id: 0, label: 'Stale', guidance: 'Old', box: [1, 2, 3, 4] }] });
  await flush();
  assert.equal(document.querySelector('#result-state').hidden, true);
  reply(calls[1], { fields: [{ id: 0, label: 'الاسم', guidance: 'اكتب اسمك', box: [1, 2, 3, 4] }] });
  await flush();
  assert.equal(document.querySelector('#result-state').hidden, false);
  assert.equal(document.querySelector('#fields-list').lang, 'ar');
  assert.equal(document.querySelector('#fields-list').dir, 'rtl');
  run('askSelectedField()');
  assert.equal(calls.length, 2, 'Empty question does not submit');
  document.querySelector('#ask-input').value = 'ما هذا؟';
  run('askSelectedField()');
  assert.equal(calls[2].url, '/api/ask');
  assert.equal(JSON.parse(calls[2].options.body).language, 'ar');
  assert.equal(document.querySelector('#ask-button').textContent, 'Asking…');
  run('askSelectedField()');
  assert.equal(calls.length, 3, 'Pending question blocks resubmission');
  document.querySelector('#language-select').value = 'fr';
  document.querySelector('#language-select').listeners.change();
  assert.equal(calls[2].options.signal.aborted, true);
  reply(calls[2], { lines: ['Old', 'Old', 'Old'] });
  await flush();
  assert.equal(document.querySelector('#answer').hidden, true);
  assert.equal(document.querySelector('#ask-button').textContent, 'Ask');
  run('clear()');
  assert.equal(calls[3].options.signal.aborted, true);
  reply(calls[3], { fields: [] });
  await flush();
  assert.equal(document.querySelector('#result-state').hidden, true);
  document.querySelector('#language-select').listeners.change();
  assert.equal(calls.length, 4, 'Reset must release the retained image');
  console.log('PASS: language payloads, RTL, reanalysis, stale-response guards, question cancellation, reset');
})().catch(error => { console.error(error); process.exitCode = 1; });
