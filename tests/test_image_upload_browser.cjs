// Real browser -> Flask conversion, with intercepted inference (no cloud calls).
// Usage: NODE_PATH=<tools>/node_modules node tests/test_image_upload_browser.cjs <fictional-fixture-directory>
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');
(async () => {
  const fixtures = process.argv[2];
  assert.ok(fixtures, 'Pass a directory containing fictional image fixtures');
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    const errors = [];
    const calls = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.route('**/api/analyze', async route => {
      const body = route.request().postDataBuffer();
      assert.ok(body.includes(Buffer.from('Content-Type: image/jpeg')), 'Inference receives standard JPEG regardless of filename');
      calls.push(route.request().url());
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ fields: [{ id: 0, label: 'Full name', guidance: 'Enter your name.', box: [88, 158, 825, 67] }] }) });
    });
    await page.goto('http://127.0.0.1:5001');
    for (const ext of ['png', 'jpg', 'webp', 'bmp', 'tiff', 'gif', 'avif', 'heic', 'ppm', 'tga', 'jp2', 'qoi']) {
      const chooser = page.waitForEvent('filechooser');
      await page.locator('#drop-zone').click();
      await (await chooser).setFiles(path.join(fixtures, `fictional.${ext}`));
      await page.locator('#language-continue').click();
      await page.locator('#result-state').waitFor({ state: 'visible' });
      await page.waitForFunction(() => { const img = document.querySelector('#form-preview'); return img.complete && img.naturalWidth > 0; });
      assert.deepEqual(await page.locator('#form-preview').evaluate(img => [img.naturalWidth, img.naturalHeight]), [400, 600]);
      assert.equal(await page.locator('.field-box').count(), 1);
      assert.equal(await page.locator('#filename').innerText(), `fictional.${ext}`);
      await page.locator('#reset-button').click();
      await page.locator('#empty-state').waitFor({ state: 'visible' });
    }
    const before = calls.length;
    await page.locator('#image-input').setInputFiles(path.join(fixtures, 'broken.heic'));
    await page.locator('#language-continue').click();
    await page.locator('#error').waitFor({ state: 'visible' });
    assert.match(await page.locator('#error').innerText(), /could not be converted/);
    assert.equal(calls.length, before, 'Bad images never reach inference');
    await page.locator('#image-input').setInputFiles(path.join(fixtures, 'fictional.heic'));
    await page.locator('#language-continue').click();
    await page.locator('#result-state').waitFor({ state: 'visible' });
    await page.evaluate(() => storageQueue);
    const cachedCalls = calls.length;
    await page.reload();
    await page.locator('#result-state').waitFor({ state: 'visible' });
    await page.waitForFunction(() => document.querySelector('#form-preview').naturalWidth > 0);
    assert.equal(calls.length, cachedCalls, 'Converted image restores from cache without inference');
    assert.equal(await page.locator('#filename').innerText(), 'fictional.heic');
    await page.locator('#reset-button').click();
    await page.evaluate(() => storageQueue);
    assert.deepEqual(errors, []);
    console.log('PASS: 12 real image formats through file chooser and Flask conversion, JPEG inference payloads, preview/overlays, bad-image error, cached HEIC reload, reset; inference mocked');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
