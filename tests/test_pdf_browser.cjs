// Real PDF rendering and browser lifecycle; cloud inference is intercepted.
// Run with Playwright on NODE_PATH and fictional fixtures directory as argv[2].
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium } = require('playwright');
(async () => {
  const directory = process.argv[2];
  assert.ok(directory, 'Pass fictional PDF fixture directory');
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    const errors = [];
    let analyses = 0, conversions = 0;
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => { if (request.url().endsWith('/api/convert')) conversions++; });
    await page.route('**/api/analyze', async route => {
      assert.ok(route.request().postDataBuffer().includes(Buffer.from('Content-Type: image/jpeg')));
      analyses++;
      await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ fields: [{ id: 0, label: `Fictional page result ${analyses}`, guidance: 'Enter the requested information.', box: [88, 158, 825, 67] }] }) });
    });
    await page.route('**/api/ask', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ lines: ['First saved answer line.', 'Second saved answer line.'] }) }));
    await page.goto('http://127.0.0.1:5001');
    const chooser = page.waitForEvent('filechooser');
    await page.locator('#drop-zone').click();
    await (await chooser).setFiles(path.join(directory, 'packet.pdf'));
    await page.locator('#result-state').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#page-select option').count(), 2);
    assert.equal(await page.locator('#page-select').inputValue(), '0');
    await page.waitForFunction(() => document.querySelector('#form-preview').naturalWidth === 800);
    const first = await page.locator('#ask-label').innerText();
    await page.locator('#ask-input').fill('Fictional question?');
    await page.locator('#ask-input').press('Enter');
    await page.locator('#answer').waitFor({ state: 'visible' });
    await page.locator('#page-select').selectOption('1');
    await page.waitForFunction(() => document.querySelector('#ask-label').textContent.includes('result 2'));
    assert.equal(await page.locator('#answer').isVisible(), false, 'Answer must not leak between pages');
    assert.equal(await page.locator('#ask-input').inputValue(), '', 'Question must not leak between pages');
    const second = await page.locator('#ask-label').innerText();
    assert.notEqual(first, second);
    const baseline = [analyses, conversions];
    await page.locator('#page-select').selectOption('0');
    await page.waitForFunction(() => document.querySelector('#ask-label').textContent.includes('result 1'));
    assert.equal(await page.locator('#answer').isVisible(), true);
    assert.equal(await page.locator('#ask-input').inputValue(), 'Fictional question?');
    assert.deepEqual([analyses, conversions], baseline, 'Cached page switch avoids rendering and inference');
    await page.locator('#page-select').selectOption('1');
    await page.evaluate(() => storageQueue);
    await page.reload();
    await page.locator('#result-state').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#page-select').inputValue(), '1');
    assert.equal(await page.locator('#ask-label').innerText(), second);
    assert.deepEqual([analyses, conversions], baseline, 'Reload retains selected page and cached results');
    await page.locator('#language-picker-button').click();
    await page.locator('#language-picker-search').fill('Spanish');
    await page.locator('.language-option').filter({ hasText: 'Spanish' }).click();
    await page.waitForFunction(() => document.querySelector('#ask-label').textContent.includes('result 3'));
    await page.locator('#language-picker-button').click();
    await page.locator('#language-picker-search').fill('English');
    await page.locator('.language-option').filter({ hasText: 'English' }).click();
    await page.waitForFunction(() => document.querySelector('#ask-label').textContent.includes('result 2'));
    assert.equal(conversions, baseline[1]);
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'No mobile horizontal overflow');
    await page.locator('#reset-button').click();
    await page.evaluate(() => storageQueue);
    await page.reload();
    await page.locator('#empty-state').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#page-control').isVisible(), false);
    const before = analyses;
    for (const file of ['encrypted.pdf', 'broken.pdf']) {
      await page.locator('#image-input').setInputFiles(path.join(directory, file));
      await page.locator('#error').waitFor({ state: 'visible' });
      assert.match(await page.locator('#error').innerText(), /Encrypted|could not be opened or converted/);
      assert.equal(analyses, before, 'Rejected PDF must not reach inference');
    }
    assert.deepEqual(errors, []);
    console.log('PASS: real PDF file chooser/rendering, page previews and selection, per-page questions/answers cache, reload, language cache, mobile layout, reset, encrypted/damaged errors; inference mocked');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
