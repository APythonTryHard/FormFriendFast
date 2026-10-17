// Language confirmation before each new upload; simulated DOM, mocked fetch only.
const assert = require('node:assert/strict');
const { IDBFactory } = require('fake-indexeddb');
const { boot, flush, fields, reply } = require('./test_persistence_frontend.cjs');
const names = { en: 'English', es: 'Español', ar: 'العربية', fr: 'Français' };
const image = name => new File(['fictional image'], name, { type: 'image/png' });
const converted = (call, pages = '1') => call.resolve({ ok: true, headers: { get: name => name === 'X-Page-Count' ? pages : null }, blob: async () => new Blob(['JPEG'], { type: 'image/jpeg' }) });
function named(page) { for (const option of page.el('#language-select').options) option.textContent = names[option.value]; return page; }
(async () => {
  const idb = new IDBFactory(), prefs = new Map([['formfriend-language', 'fr']]);
  let page = named(boot(idb, prefs)); await flush();

  // Upload stops at the step; nothing is sent.
  page.el('#image-input').files = [image('fictional-form.png')];
  page.el('#image-input').listeners.change(); await flush();
  assert.equal(page.calls.length, 0, 'No convert/analyze request before Continue');
  assert.equal(page.el('#language-step').hidden, false);
  assert.equal(page.el('#empty-state').hidden, true);
  assert.equal(page.el('#loading-state').hidden, true);
  assert.equal(page.el('#language-step-file').textContent, 'fictional-form.png');
  assert.equal(page.el('#upload-language').value, 'fr', 'Preselects the last-used language');
  assert.equal(page.el('#upload-language').children.length, 4, 'Options cloned from #language-select');
  assert.equal(page.el('#language-continue').textContent, 'Continue in Français');
  page.el('#upload-language').value = 'es';
  page.el('#upload-language').listeners.change();
  assert.equal(page.el('#language-continue').textContent, 'Continue in Español');
  assert.equal(page.calls.length, 0, 'Changing the step select does not submit');
  assert.equal(prefs.get('formfriend-language'), 'fr', 'Preference unchanged until Continue');

  // Cancel: no request, back to the empty upload state.
  page.el('#language-cancel').listeners.click(); await flush();
  assert.equal(page.calls.length, 0, 'Cancel makes no request');
  assert.equal(page.el('#language-step').hidden, true);
  assert.equal(page.el('#empty-state').hidden, false);
  assert.equal(page.el('#reset-button').hidden, true);
  page.el('#language-continue').listeners.click(); await flush();
  assert.equal(page.calls.length, 0, 'Cancelled file cannot be submitted later');

  // Continue: language saved and sent; exactly one convert then one analyze.
  page.el('#image-input').files = [image('fictional-form.png')];
  page.el('#image-input').listeners.change();
  page.el('#upload-language').value = 'es';
  page.el('#upload-language').listeners.change();
  page.el('#language-continue').listeners.click();
  assert.equal(page.el('#language-step').hidden, true);
  assert.equal(page.el('#language-select').value, 'es');
  assert.equal(prefs.get('formfriend-language'), 'es', 'Chosen language is saved');
  assert.equal(page.calls.length, 1);
  assert.equal(page.calls[0].url, '/api/convert', 'Conversion runs only after Continue');
  converted(page.calls[0]); await flush();
  assert.equal(page.calls.length, 2, 'No duplicate analysis from the language change');
  assert.equal(page.calls[1].url, '/api/analyze');
  assert.equal(page.calls[1].options.body.get('language'), 'es');
  reply(page.calls[1], { fields }); await flush();
  assert.equal(page.el('#result-state').hidden, false);
  await page.run('storageQueue');

  // Top-picker change after load re-analyzes directly, without the step.
  page.change('fr');
  assert.equal(page.el('#language-step').hidden, true);
  assert.equal(page.calls[2].url, '/api/analyze');
  assert.equal(page.calls[2].options.body.get('language'), 'fr');
  reply(page.calls[2], { fields }); await flush();
  await page.run('storageQueue');

  // Reload restore skips the step.
  page = named(boot(idb, prefs)); await flush();
  assert.equal(page.el('#language-step').hidden, true, 'Restore skips the language step');
  assert.equal(page.el('#result-state').hidden, false);
  assert.equal(page.calls.length, 0);

  // Start over returns to the normal empty state.
  page.el('#reset-button').listeners.click(); await flush();
  assert.equal(page.el('#empty-state').hidden, false);
  assert.equal(page.el('#language-step').hidden, true);

  // PDF page switching skips the step.
  page.el('#image-input').files = [new File(['PDF'], 'packet.pdf', { type: 'application/pdf' })];
  page.el('#image-input').listeners.change();
  assert.equal(page.calls.length, 0);
  page.el('#language-continue').listeners.click();
  converted(page.calls[0], '2'); await flush();
  reply(page.calls[1], { fields }); await flush();
  page.el('#page-select').value = '1'; page.el('#page-select').listeners.change();
  assert.equal(page.el('#language-step').hidden, true, 'Page switch skips the language step');
  assert.equal(page.calls[2].url, '/api/convert');
  converted(page.calls[2], '2'); await flush();
  assert.equal(page.calls[3].url, '/api/analyze');
  assert.equal(page.el('#language-step').hidden, true);

  // Oversize files show the existing error immediately, without the step.
  page.el('#reset-button').listeners.click();
  page.el('#image-input').files = [new File([new Uint8Array(8 * 1024 * 1024 + 1)], 'huge.png', { type: 'image/png' })];
  page.el('#image-input').listeners.change();
  assert.equal(page.el('#language-step').hidden, true);
  assert.match(page.el('#error').textContent, /maximum 8 MB/);
  assert.equal(page.calls.length, 4);
  console.log('PASS: language step before any request, cancel, saved/sent language, no duplicate analysis, restore/page switch/picker change skip, oversize error');
})().catch(err => { console.error(err); process.exitCode = 1; });
