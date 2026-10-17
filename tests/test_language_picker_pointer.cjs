// Targeted pointer selection regression; real browser, no AI requests.
// Requires Playwright on NODE_PATH. Pass 'webkit' to test Safari's event behavior.
const assert = require('node:assert/strict');
const { chromium, webkit } = require('playwright');
(async () => {
  const engine = process.argv[2] === 'webkit' ? webkit : chromium;
  const browser = await engine.launch({ headless: true });
  try {
    const page = await browser.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/**', route => route.abort());
    await page.goto('http://127.0.0.1:5001');
    await page.evaluate(() => {
      window.pickerTrace = [];
      for (const type of ['pointerdown', 'mousedown', 'focusout', 'mouseup', 'click']) {
        document.querySelector('#language-picker').addEventListener(type, event => {
          window.pickerTrace.push({ type, target: event.target.className, related: event.relatedTarget?.className || null });
        }, true);
      }
    });
    const trigger = page.locator('#language-picker-button');
    await trigger.click();
    await page.locator('#language-picker-search').fill('Spanish');
    await page.locator('.language-option:visible').click();
    const value = await page.locator('#language-select').inputValue();
    if (value !== 'es') console.log('Picker event trace:', await page.evaluate(() => window.pickerTrace));
    assert.equal(value, 'es', 'Clicking Español must change the selected language');
    assert.match(await trigger.innerText(), /Español/);
    assert.equal(await page.evaluate(() => localStorage.getItem('formfriend-language')), 'es');
    await page.reload();
    assert.match(await trigger.innerText(), /Español/);
    assert.deepEqual(errors, []);
    console.log(`PASS ${engine.name()}: mouse click selects Spanish, updates button, saves choice and survives reload`);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
