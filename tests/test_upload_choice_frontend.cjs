// Mobile upload choice (photo vs. file) with a minimal fake DOM; no network or provider requests.
// Run: node tests/test_upload_choice_frontend.cjs (fake-indexeddb on NODE_PATH for the app.js section).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/upload-choice.js', 'utf8');

class FakeElement {
  constructor(id, parent = null, attrs = {}) {
    Object.assign(this, { id, parent, listeners: {}, attributes: {}, dataset: {}, ...attrs });
  }
  addEventListener(type, handler) { (this.listeners[type] ||= []).push(handler); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  removeAttribute(name) { delete this.attributes[name]; }
  closest(selector) {
    for (let node = this; node; node = node.parent) if (node.matches?.(selector)) return node;
    return null;
  }
  focus() { this.world.focused = this; }
}

function makeWorld({ coarse, dialogSupport = true, navigator = undefined }) {
  const world = { opened: [], focused: null, coarse };
  const el = (id, parent, attrs) => { const node = new FakeElement(id, parent, attrs); node.world = world; return node; };
  const dropZone = el('drop-zone', null, { tagName: 'LABEL' });
  const fileInput = el('image-input', dropZone, { tagName: 'INPUT' });
  const photoInput = el('photo-input', null, { tagName: 'INPUT' });
  const sheet = el('upload-sheet', null, { tagName: 'DIALOG', open: false });
  const photoChoice = el('photo-choice', sheet, { dataset: { uploadChoice: 'photo' }, matches: s => s === '[data-upload-choice]' });
  const fileChoice = el('file-choice', sheet, { dataset: { uploadChoice: 'file' }, matches: s => s === '[data-upload-choice]' });
  const cancel = el('cancel', sheet, { matches: s => s === '[data-upload-cancel]' });
  if (dialogSupport) {
    sheet.showModal = () => { sheet.open = true; world.modalCount = (world.modalCount || 0) + 1; };
    sheet.close = () => { sheet.open = false; };
  }
  sheet.querySelector = () => photoChoice;
  const dispatch = (target, type, extra = {}) => {
    const event = { type, target, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, ...extra };
    for (let node = target; node; node = node.parent) for (const handler of node.listeners[type] || []) handler(event);
    return event;
  };
  // Browser model: a click on an input opens its picker unless cancelled;
  // an uncancelled click on the label forwards a click to its control.
  for (const input of [fileInput, photoInput]) {
    input.click = () => { if (!dispatch(input, 'click').defaultPrevented) world.opened.push(input.id); };
  }
  const tap = target => {
    const event = dispatch(target, 'click');
    if (target === dropZone && !event.defaultPrevented) fileInput.click();
    return event;
  };
  const key = (target, value) => dispatch(target, 'keydown', { key: value });
  const nodes = { '#drop-zone': dropZone, '#image-input': fileInput, '#photo-input': photoInput, '#upload-sheet': sheet };
  const changeListeners = [];
  const context = vm.createContext({
    document: { querySelector: selector => nodes[selector] || null },
    window: { navigator, matchMedia: query => ({ get matches() { return query.includes('coarse') ? world.coarse : false; }, addEventListener: (_type, fn) => changeListeners.push(fn) }) },
  });
  vm.runInContext(source, context);
  return { world, dropZone, fileInput, photoInput, sheet, photoChoice, fileChoice, cancel, tap, key, changeListeners };
}

// Desktop / fine pointer: native label behavior and keyboard access are preserved.
{
  const page = makeWorld({ coarse: false });
  const event = page.tap(page.dropZone);
  assert.equal(event.defaultPrevented, false, 'Desktop click must keep native label activation');
  assert.deepEqual(page.world.opened, ['image-input'], 'Desktop click opens the existing file picker directly');
  assert.equal(page.sheet.open, false, 'Desktop never shows the choice sheet');
  assert.equal(page.dropZone.attributes['aria-haspopup'], undefined);
  const enter = page.key(page.dropZone, 'Enter');
  assert.equal(enter.defaultPrevented, true);
  assert.deepEqual(page.world.opened, ['image-input', 'image-input'], 'Enter opens the file picker from the keyboard');
  page.key(page.dropZone, ' ');
  assert.equal(page.world.opened.length, 3, 'Space opens the file picker from the keyboard');
  page.key(page.dropZone, 'a');
  assert.equal(page.world.opened.length, 3, 'Other keys do nothing');
}

// Touch-first: a tap offers photo or file; each choice opens the matching input.
{
  const page = makeWorld({ coarse: true });
  assert.equal(page.dropZone.attributes['aria-haspopup'], 'dialog');
  const event = page.tap(page.dropZone);
  assert.equal(event.defaultPrevented, true, 'Mobile tap must not open a picker before a choice');
  assert.equal(page.sheet.open, true, 'Mobile tap opens the choice sheet');
  assert.deepEqual(page.world.opened, []);
  assert.equal(page.world.focused, page.photoChoice, 'Focus moves to the first choice');

  page.tap(page.photoChoice);
  assert.equal(page.sheet.open, false, 'Choosing closes the sheet');
  assert.deepEqual(page.world.opened, ['photo-input'], 'Photo choice opens the image-only input');

  page.tap(page.dropZone);
  page.tap(page.fileChoice);
  assert.equal(page.sheet.open, false);
  assert.deepEqual(page.world.opened, ['photo-input', 'image-input'],
    'File choice opens the existing input; its click bubbling through the label must not be cancelled');

  page.tap(page.dropZone);
  page.tap(page.sheet); // Backdrop clicks target the dialog element itself.
  assert.equal(page.sheet.open, false, 'Backdrop tap dismisses the sheet');
  page.tap(page.dropZone);
  page.tap(page.cancel);
  assert.equal(page.sheet.open, false, 'Cancel dismisses the sheet');
  assert.equal(page.world.opened.length, 2, 'Dismissal never opens a picker');

  const opensBefore = page.world.modalCount;
  page.key(page.dropZone, 'Enter');
  assert.equal(page.sheet.open, true, 'Keyboard activation opens the sheet on touch devices');
  page.key(page.dropZone, 'Enter');
  assert.equal(page.world.modalCount, opensBefore + 1, 'An already-open sheet is not reopened');
  page.sheet.close();

  page.world.coarse = false; // e.g. a mouse becomes the primary pointer
  page.changeListeners.forEach(fn => fn());
  assert.equal(page.dropZone.attributes['aria-haspopup'], undefined, 'Popup semantics follow the current pointer');
  page.tap(page.dropZone);
  assert.equal(page.sheet.open, false);
  assert.equal(page.world.opened.at(-1), 'image-input');
}

// Touch device without <dialog> support falls back to the existing file picker.
{
  const page = makeWorld({ coarse: true, dialogSupport: false });
  const event = page.tap(page.dropZone);
  assert.equal(event.defaultPrevented, false);
  assert.deepEqual(page.world.opened, ['image-input']);
}
// iPhone and iPad (including iPadOS reporting MacIntel): iOS already shows its
// own photo/camera/file menu, so the native full-type input opens directly.
for (const navigator of [
  { userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)', platform: 'iPhone', maxTouchPoints: 5 },
  { userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', platform: 'MacIntel', maxTouchPoints: 5 },
]) {
  const page = makeWorld({ coarse: true, navigator });
  assert.equal(page.dropZone.attributes['aria-haspopup'], undefined, 'iOS never advertises the custom sheet');
  const event = page.tap(page.dropZone);
  assert.equal(event.defaultPrevented, false, 'iOS keeps native label activation');
  assert.equal(page.sheet.open, false, 'iOS skips the redundant choice sheet');
  assert.deepEqual(page.world.opened, ['image-input'], 'iOS opens the full image/PDF input directly');
  page.key(page.dropZone, 'Enter');
  assert.deepEqual(page.world.opened, ['image-input', 'image-input'], 'Keyboard opens the native input on iOS');
}
// A real Mac (no touch points) and Android keep their previous behavior.
{
  const mac = makeWorld({ coarse: false, navigator: { userAgent: 'Macintosh', platform: 'MacIntel', maxTouchPoints: 0 } });
  mac.tap(mac.dropZone);
  assert.deepEqual(mac.world.opened, ['image-input']);
  const android = makeWorld({ coarse: true, navigator: { userAgent: 'Mozilla/5.0 (Linux; Android 15)', platform: 'Linux armv8l', maxTouchPoints: 5 } });
  android.tap(android.dropZone);
  assert.equal(android.sheet.open, true, 'Non-iOS touch devices still get the photo/file choice');
}
console.log('PASS: desktop native picker + keyboard, mobile photo/file choice sheet, backdrop/cancel dismissal, no swallowed file click, pointer change, no-dialog fallback');

// The photo input reuses the existing conversion -> analysis path in app.js.
(async () => {
  const { boot, flush, fields, reply } = require('./test_persistence_frontend.cjs');
  let page = boot(); await flush();
  page.el('#photo-input').files = [new File(['fictional HEIC photo'], 'IMG_0001.HEIC', { type: 'image/heic' })];
  page.el('#photo-input').value = 'C:\\fakepath\\IMG_0001.HEIC';
  page.el('#photo-input').listeners.change();
  assert.equal(page.el('#photo-input').value, '', 'Photo input is cleared so the same photo can be chosen again');
  assert.equal(page.calls.length, 0, 'Photos wait for the language step');
  page.el('#language-continue').listeners.click();
  assert.equal(page.calls[0]?.url, '/api/convert', 'Photos are normalized by the server before analysis');
  page.calls[0].resolve({ ok: true, blob: async () => new Blob(['normalized'], { type: 'image/jpeg' }) });
  await flush();
  assert.equal(page.calls[1].url, '/api/analyze');
  assert.equal(page.calls[1].options.body.get('image').type, 'image/jpeg');
  reply(page.calls[1], { fields }); await flush();
  assert.equal(page.el('#result-state').hidden, false);
  assert.equal(page.el('#filename').textContent, 'IMG_0001.HEIC');

  page = boot(); await flush();
  page.el('#photo-input').files = [];
  page.el('#photo-input').listeners.change();
  assert.equal(page.calls.length, 0, 'An empty selection does not upload');
  assert.equal(page.el('#empty-state').hidden, false);
  page.el('#photo-input').files = [new File([new Uint8Array(8 * 1024 * 1024 + 1)], 'huge.jpg', { type: 'image/jpeg' })];
  page.el('#photo-input').listeners.change();
  assert.equal(page.calls.length, 0, 'Oversized photos use the existing size validation');
  assert.equal(page.el('#language-step').hidden, true, 'Oversized photos skip the language step');
  assert.match(page.el('#error').textContent, /maximum 8 MB/);
  console.log('PASS: photo input reuses conversion/analysis, clears for reselection, empty selection and size validation');
})().catch(error => { console.error(error); process.exitCode = 1; });
