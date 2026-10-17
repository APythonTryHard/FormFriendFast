// Real browser -> local Flask: mobile photo/file choice, both upload paths, dismissal and layout.
// /api/analyze is MOCKED with fictional fields (no provider calls); /api/convert is the real local path.
// Usage: NODE_PATH=<tools>/node_modules node tests/test_mobile_upload_browser.cjs <fictional-fixture-directory> [chromium|webkit]
const assert = require('node:assert/strict');
const path = require('node:path');
const playwright = require('playwright');
const BASE = 'http://127.0.0.1:5001';
const FIELDS = { fields: [{ id: 0, label: 'MOCK Full name', guidance: 'MOCK guidance.', box: [88, 158, 825, 67] }] };

async function noOverflow(page, label) {
  const result = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, width: document.documentElement.clientWidth }));
  assert.ok(result.scroll <= result.width, `${label}: horizontal overflow ${result.scroll} > ${result.width}`);
}

(async () => {
  const [fixtures, engine = 'chromium'] = process.argv.slice(2);
  assert.ok(fixtures, 'Pass a directory containing fictional fixtures');
  const browser = await playwright[engine].launch({ headless: true });
  const analyses = [];
  try {
    for (const [width, height] of [[320, 640], [375, 667], [390, 844], [430, 932], [768, 1024]]) {
      const context = await browser.newContext({ viewport: { width, height }, isMobile: true, hasTouch: true });
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/api/analyze', route => { analyses.push(route.request().url()); return route.fulfill({ contentType: 'application/json', body: JSON.stringify(FIELDS) }); });
      await page.goto(BASE);
      const dropZone = page.locator('#drop-zone');
      const sheet = page.locator('#upload-sheet');
      const photo = page.getByRole('button', { name: 'Take or choose a photo' });
      const file = page.getByRole('button', { name: 'Choose a PDF or file' });
      assert.equal(await dropZone.getAttribute('aria-haspopup'), 'dialog');
      await noOverflow(page, `${width} empty`);

      // Tap opens the sheet, not a picker; Escape, backdrop and Cancel dismiss it.
      let chooserOpened = false;
      const watch = () => { chooserOpened = true; };
      page.on('filechooser', watch);
      await dropZone.tap();
      await sheet.waitFor({ state: 'visible' });
      assert.equal(chooserOpened, false, 'Tapping Upload must offer a choice before any picker');
      assert.equal(await photo.evaluate(el => el === document.activeElement), true, 'Focus starts on the first choice');
      for (const control of [photo, file, page.getByRole('button', { name: 'Cancel' })]) {
        const box = await control.boundingBox();
        assert.ok(box.height >= 44 && box.x >= 0 && box.x + box.width <= width && box.y + box.height <= height, `${width}: ${await control.innerText()} fits and is touch-sized`);
      }
      await noOverflow(page, `${width} sheet`);
      await page.keyboard.press('Escape');
      await sheet.waitFor({ state: 'hidden' });
      await dropZone.tap();
      await page.mouse.click(width / 2, 10); // Backdrop above the panel.
      await sheet.waitFor({ state: 'hidden' });
      await dropZone.tap();
      await page.getByRole('button', { name: 'Cancel' }).tap();
      await sheet.waitFor({ state: 'hidden' });
      assert.equal(chooserOpened, false, 'Dismissal never opens a picker');
      page.off('filechooser', watch);

      // Photo path: image-only picker without forced capture; cancelling leaves the page ready.
      let chooser = page.waitForEvent('filechooser');
      await dropZone.tap();
      await photo.tap();
      let picker = await chooser;
      assert.equal(await picker.element().evaluate(el => el.id), 'photo-input');
      assert.equal(await picker.element().getAttribute('accept'), 'image/*');
      assert.equal(await picker.element().getAttribute('capture'), null);
      assert.equal(picker.isMultiple(), false);
      assert.equal(await sheet.isVisible(), false, 'Sheet closes before the picker');
      // Simulated cancel: the chooser is dismissed without files.
      assert.equal(await page.locator('#empty-state').isVisible(), true);
      chooser = page.waitForEvent('filechooser');
      await dropZone.tap();
      await photo.tap();
      const analysesBeforeStep = analyses.length;
      await (await chooser).setFiles(path.join(fixtures, 'fictional.heic'));
      // Language step: nothing is sent until Continue; touch-sized, stacked, no overflow.
      await page.locator('#language-step').waitFor({ state: 'visible' });
      assert.equal(await page.locator('#upload-language').evaluate(el => el === document.activeElement), true, 'Focus starts on the language select');
      assert.equal(await page.locator('#language-step-file').innerText(), 'fictional.heic');
      assert.equal(analyses.length, analysesBeforeStep, 'No analysis before the language is confirmed');
      const selectBox = await page.locator('#upload-language').boundingBox();
      for (const control of ['#upload-language', '#language-continue', '#language-cancel']) {
        const box = await page.locator(control).boundingBox();
        assert.ok(box.height >= 44 && box.x >= 0 && box.x + box.width <= width, `${width}: ${control} fits and is touch-sized`);
      }
      if (width <= 650) assert.ok((await page.locator('#language-continue').boundingBox()).y >= selectBox.y + selectBox.height, `${width}: Continue stacks under the select`);
      if (width <= 650) assert.equal(await page.locator('#upload-language').evaluate(el => getComputedStyle(el).fontSize), '16px');
      await noOverflow(page, `${width} language step`);
      await page.locator('#language-continue').tap();
      await page.locator('#result-state').waitFor({ state: 'visible' });
      await page.waitForFunction(() => document.querySelector('#form-preview').naturalWidth === 400);
      assert.equal(await page.locator('#filename').innerText(), 'fictional.heic');
      assert.equal(await page.locator('.field-box').count(), 1);
      await noOverflow(page, `${width} photo result`);

      // Reselecting the same photo after Start over works.
      await page.locator('#reset-button').tap();
      chooser = page.waitForEvent('filechooser');
      await dropZone.tap();
      await photo.tap();
      await (await chooser).setFiles(path.join(fixtures, 'fictional.heic'));
      await page.locator('#language-continue').click();
      await page.locator('#result-state').waitFor({ state: 'visible' });
      await page.locator('#reset-button').tap();

      // File path: the existing input and accept list; PDFs keep page selection.
      chooser = page.waitForEvent('filechooser');
      await dropZone.tap();
      await file.tap();
      picker = await chooser;
      assert.equal(await picker.element().evaluate(el => el.id), 'image-input');
      assert.match(await picker.element().getAttribute('accept'), /^application\/pdf,\.pdf,image\/\*,\.heic,/);
      await picker.setFiles(path.join(fixtures, 'packet.pdf'));
      await page.locator('#language-continue').click();
      await page.locator('#result-state').waitFor({ state: 'visible' });
      assert.equal(await page.locator('#page-select option').count(), 2);
      for (const control of ['#page-select', '#reset-button', '#ask-input', '#ask-button']) {
        const box = await page.locator(control).boundingBox();
        assert.ok(box.height >= 44 && box.x >= 0 && box.x + box.width <= width, `${width}: ${control} fits and is touch-sized`);
      }
      await noOverflow(page, `${width} pdf result`);

      // A rejected photo shows the existing safe error without inference.
      await page.locator('#reset-button').tap();
      const before = analyses.length;
      await page.locator('#photo-input').setInputFiles(path.join(fixtures, 'broken.heic'));
      await page.locator('#language-continue').click();
      await page.locator('#error').waitFor({ state: 'visible' });
      assert.match(await page.locator('#error').innerText(), /could not be converted/);
      assert.equal(analyses.length, before);
      await page.evaluate(() => storageQueue);
      assert.deepEqual(errors, []);
      await context.close();
    }

    // Desktop keeps the direct picker (no sheet) and gains keyboard access.
    const desktop = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    await desktop.route('**/api/analyze', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify(FIELDS) }));
    await desktop.goto(BASE);
    assert.equal(await desktop.locator('#drop-zone').getAttribute('aria-haspopup'), null);
    let chooser = desktop.waitForEvent('filechooser');
    await desktop.locator('#drop-zone').click();
    let picker = await chooser;
    assert.equal(await picker.element().evaluate(el => el.id), 'image-input');
    assert.equal(await desktop.locator('#upload-sheet').isVisible(), false);
    chooser = desktop.waitForEvent('filechooser');
    await desktop.locator('#drop-zone').focus();
    await desktop.keyboard.press('Enter');
    picker = await chooser;
    await picker.setFiles(path.join(fixtures, 'fictional.png'));
    await desktop.locator('#language-continue').click();
    await desktop.locator('#result-state').waitFor({ state: 'visible' });
    await desktop.locator('#reset-button').click();
    await desktop.evaluate(() => storageQueue);
    console.log(`PASS ${engine}: 320/375/390/430/768 touch layouts without overflow; Upload offers photo or file; Escape/backdrop/Cancel dismissal; photo picker image/* without capture; cancel + reselection; HEIC photo and PDF file through real conversion; safe photo error; language step before any analysis (focus, touch size, stacking, no overflow); desktop direct picker + keyboard; analysis mocked (${analyses.length} mocked calls)`);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
