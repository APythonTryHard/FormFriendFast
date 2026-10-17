const input = document.querySelector('#image-input');
const languageSelect = document.querySelector('#language-select');
const pageSelect = document.querySelector('#page-select');
const pageControl = document.querySelector('#page-control');
let currentFile = null;
const dropZone = document.querySelector('#drop-zone');
const emptyState = document.querySelector('#empty-state');
const loadingState = document.querySelector('#loading-state');
const resultState = document.querySelector('#result-state');
const resetButton = document.querySelector('#reset-button');
const preview = document.querySelector('#form-preview');
const boxLayer = document.querySelector('#box-layer');
const fieldsList = document.querySelector('#fields-list');
const error = document.querySelector('#error');
const explainPanel = document.querySelector('#explain-panel');
const explainLabel = document.querySelector('#explain-label');
const explainButton = document.querySelector('#explain-button');
const explanation = document.querySelector('#explanation');
const explainError = document.querySelector('#explain-error');
let objectUrl = null;
let controller = null;
let generation = 0;
let currentFields = [];
let selectedField = null;
let explanationController = null;
let explanationGeneration = 0;
let savedForm = null;
let documentEpoch = 0;
let renderingSaved = false;
let storageQueue = Promise.resolve();

// Only one current document, in an origin-local IndexedDB store. Queue writes
// behind opening and each other; epoch checks discard replaced/reset snapshots.
const database = new Promise((resolve, reject) => {
  try {
    const request = indexedDB.open('formfriend-browser', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('current-form');
    request.onsuccess = () => {
      request.result.onversionchange = () => request.result.close();
      resolve(request.result);
    };
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error('Browser database blocked'));
  } catch (err) { reject(err); }
});
database.catch(() => storageWarning());

function storeForm() {
  const epoch = documentEpoch;
  // Snapshot now, not when opening completes; never save a mutable result map.
  let snapshot;
  try { snapshot = savedForm ? { ...savedForm, results: structuredClone(savedForm.results) } : null; }
  catch { storageWarning(); return; }
  storageQueue = storageQueue.then(async () => {
    const db = await database;
    if (epoch !== documentEpoch) return;
    await new Promise((resolve, reject) => {
      const transaction = db.transaction('current-form', 'readwrite');
      transaction.oncomplete = resolve;
      transaction.onerror = transaction.onabort = () => reject(transaction.error);
      const store = transaction.objectStore('current-form');
      if (snapshot) store.put(snapshot, 'current');
      else store.delete('current');
    });
  }).catch(() => storageWarning());
}

function resultKey(language = languageSelect.value) {
  return savedForm?.pageCount > 1 ? `${language}:${savedForm.pageIndex}` : language;
}
function cachedResult() { return savedForm?.results[resultKey()]; }

function updatePageControls() {
  pageControl.hidden = !(savedForm?.pageCount > 1);
  pageSelect.disabled = false;
  pageSelect.replaceChildren();
  if (pageControl.hidden) return;
  for (let index = 0; index < savedForm.pageCount; index++) {
    const option = document.createElement('option');
    option.value = String(index);
    option.textContent = `${index + 1} of ${savedForm.pageCount}`;
    pageSelect.append(option);
  }
  pageSelect.value = String(savedForm.pageIndex);
}

async function selectPdfPage(index) {
  if (!savedForm?.source || !Number.isInteger(index) || index < 0 || index >= savedForm.pageCount) return;
  if (savedForm.pageImages[index]) {
    savedForm.pageIndex = index;
    const file = new File([savedForm.pageImages[index]], savedForm.name, { type: 'image/jpeg' });
    return analyze(file, true);
  }
  const source = savedForm.source;
  const name = savedForm.name;
  clear(true);
  const current = generation;
  controller = new AbortController();
  emptyState.hidden = true;
  loadingState.hidden = false;
  resetButton.hidden = false;
  updatePageControls();
  pageSelect.disabled = true;
  document.querySelector('#loading-title').textContent = 'Preparing PDF page…';
  document.querySelector('#loading-filename').textContent = `${name} · Page ${index + 1}`;
  const data = new FormData();
  data.append('image', source, name);
  data.append('page', String(index));
  try {
    const response = await fetch('/api/convert', { method: 'POST', body: data, signal: controller.signal });
    if (current !== generation) return;
    if (!response.ok) {
      const result = await response.json();
      throw new Error(result.error || 'This PDF page could not be converted.');
    }
    const blob = await response.blob();
    if (current !== generation) return;
    const file = new File([blob], name, { type: 'image/jpeg' });
    savedForm.pageIndex = index;
    savedForm.pageImages = { ...savedForm.pageImages, [index]: file };
    await analyze(file, true);
  } catch (err) {
    if (current !== generation || err.name === 'AbortError') return;
    clear(true);
    currentFile = new File([savedForm.file], name, { type: 'image/jpeg' });
    updatePageControls();
    resetButton.hidden = false;
    showError(err.message || 'This PDF page could not be converted.');
  }
}

function displayCached(result) {
  renderingSaved = true;
  try {
    showFields(result.fields);
    if (result.selected !== null) selectField(result.selected);
  } finally { renderingSaved = false; }
  loadingState.hidden = true;
  resultState.hidden = false;
}

async function restoreForm() {
  const epoch = documentEpoch;
  try {
    const db = await database;
    const record = await new Promise((resolve, reject) => {
      const transaction = db.transaction('current-form', 'readonly');
      const request = transaction.objectStore('current-form').get('current');
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
      transaction.onabort = () => reject(transaction.error);
    });
    if (epoch !== documentEpoch || !record) return;
    if (!(record.file instanceof Blob) || !record.results || record.version !== 1) {
      documentEpoch++;
      storeForm();
      storageWarning();
      return;
    }
    savedForm = record;
    // Some engines deserialize File as Blob; keep the original filename explicitly.
    const file = new File([record.file], record.name, { type: record.file.type });
    analyze(file, true);
  } catch { storageWarning(); }
}

function clearExplanation() {
  explanationGeneration++;
  if (explanationController) explanationController.abort();
  explanationController = null;
  explanation.textContent = '';
  explanation.hidden = true;
  explainError.textContent = '';
  explainError.hidden = true;
  explainButton.disabled = false;
  explainButton.textContent = 'Explain';
}

function clear(keepSaved = false) {
  if (!keepSaved) {
    documentEpoch++;
    savedForm = null;
    storeForm();
  }
  currentFile = null;
  clearExplanation();
  currentFields = [];
  selectedField = null;
  explainPanel.hidden = true;
  explainLabel.textContent = '';
  generation++;
  if (controller) controller.abort();
  controller = null;
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = null;
  preview.removeAttribute('src');
  input.value = '';
  boxLayer.replaceChildren();
  fieldsList.replaceChildren();
  emptyState.hidden = false;
  loadingState.hidden = true;
  resultState.hidden = true;
  resetButton.hidden = true;
  pageControl.hidden = true;
  pageSelect.disabled = false;
  error.hidden = true;
  dropZone.querySelector('strong').textContent = 'Choose an image or PDF';
}

function showError(message) {
  error.textContent = message;
  error.hidden = false;
}

function selectField(id) {
  const field = currentFields.find(field => field.id === id);
  if (!field) return;
  if (selectedField !== field) clearExplanation();
  selectedField = field;
  explainPanel.hidden = false;
  explainLabel.textContent = `${currentFields.indexOf(field) + 1}. ${field.label}`;
  for (const element of document.querySelectorAll('[data-field-id]')) {
    element.classList.toggle('selected', Number(element.dataset.fieldId) === id);
  }
  const card = fieldsList.querySelector(`[data-field-id="${id}"]`);
  card?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  const cached = cachedResult();
  const lines = cached?.explanations[id];
  if (lines) {
    explanation.textContent = lines.join('\n');
    explanation.hidden = false;
  }
  if (cached && !renderingSaved) {
    cached.selected = id;
    storeForm();
  }
}

function showFields(fields) {
  const language = languageSelect.value;
  const direction = ['ar', 'he', 'fa', 'ur', 'ps'].includes(language) ? 'rtl' : 'ltr';
  for (const element of [fieldsList, explainLabel, explanation]) {
    element.lang = language;
    element.dir = direction;
  }
  clearExplanation();
  currentFields = fields;
  selectedField = null;
  explainPanel.hidden = true;
  document.querySelector('#field-count').textContent = fields.length;
  boxLayer.replaceChildren();
  fieldsList.replaceChildren();
  if (!fields.length) {
    const note = document.createElement('p');
    note.className = 'no-fields';
    note.textContent = 'No readable fields were found in this image. Try a clearer, straight-on photo of the full form.';
    fieldsList.append(note);
  }
  fields.forEach((field, index) => {
    const box = document.createElement('button');
    box.type = 'button';
    box.className = 'field-box';
    box.dataset.fieldId = field.id;
    box.setAttribute('aria-label', `Field ${index + 1}: ${field.label}`);
    const [x, y, width, height] = field.box;
    Object.assign(box.style, { left: `${x / 10}%`, top: `${y / 10}%`, width: `${width / 10}%`, height: `${height / 10}%` });
    const number = document.createElement('span');
    number.className = 'box-number';
    number.textContent = index + 1;
    box.append(number);
    box.addEventListener('click', () => selectField(field.id));
    boxLayer.append(box);

    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'field-card';
    card.dataset.fieldId = field.id;
    const badge = document.createElement('span');
    badge.className = 'field-index';
    badge.textContent = index + 1;
    const copy = document.createElement('span');
    copy.className = 'field-copy';
    const label = document.createElement('strong');
    label.textContent = field.label;
    const guidance = document.createElement('span');
    guidance.textContent = field.guidance;
    copy.append(label, guidance);
    card.append(badge, copy);
    card.addEventListener('click', () => selectField(field.id));
    fieldsList.append(card);
  });
  if (fields.length) selectField(fields[0].id);
}

async function explainSelectedField() {
  if (!selectedField || explanationController) return;
  const cached = cachedResult();
  if (cached?.explanations[selectedField.id]) {
    explanation.textContent = cached.explanations[selectedField.id].join('\n');
    explanation.hidden = false;
    return;
  }
  clearExplanation();
  const current = explanationGeneration;
  const field = selectedField;
  explanationController = new AbortController();
  explainButton.disabled = true;
  explainButton.textContent = 'Explaining…';
  try {
    const response = await fetch('/api/explain', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label: field.label, guidance: field.guidance, language: languageSelect.value }),
      signal: explanationController.signal,
    });
    const result = await response.json();
    if (current !== explanationGeneration) return;
    if (!response.ok) throw new Error(result.error || 'Could not explain this field.');
    explanation.textContent = result.lines.join('\n');
    explanation.hidden = false;
    if (cached) { cached.explanations[field.id] = result.lines; storeForm(); }
  } catch (err) {
    if (current !== explanationGeneration || err.name === 'AbortError') return;
    explainError.textContent = err.message || 'Could not explain this field.';
    explainError.hidden = false;
  } finally {
    if (current === explanationGeneration) {
      explanationController = null;
      explainButton.disabled = false;
      explainButton.textContent = 'Explain';
    }
  }
}

async function uploadImage(file) {
  clear();
  if (!file) return;
  if (file.size > 8 * 1024 * 1024) {
    showError('Image is too large (maximum 8 MB).');
    return;
  }
  const current = generation;
  controller = new AbortController();
  emptyState.hidden = true;
  loadingState.hidden = false;
  resetButton.hidden = false;
  document.querySelector('#loading-title').textContent = 'Preparing image…';
  document.querySelector('#loading-filename').textContent = file.name;
  const data = new FormData();
  data.append('image', file);
  try {
    const response = await fetch('/api/convert', { method: 'POST', body: data, signal: controller.signal });
    if (current !== generation) return;
    if (!response.ok) {
      const result = await response.json();
      throw new Error(result.error || 'This image could not be converted.');
    }
    const converted = await response.blob();
    if (current !== generation) return;
    const normalized = new File([converted], file.name, { type: 'image/jpeg' });
    const pageCount = Number(response.headers?.get('X-Page-Count') || 1);
    savedForm = { version: 1, file: normalized, name: file.name, results: {},
      source: pageCount > 1 ? file : null, pageCount, pageIndex: 0, pageImages: { 0: normalized } };
    await analyze(normalized, true);
  } catch (err) {
    if (current !== generation || err.name === 'AbortError') return;
    clear();
    showError(err.message || 'This image could not be converted.');
  }
}

async function analyze(file, sameDocument = false) {
  clear(sameDocument);
  if (!file) return;
  if (file.size > 8 * 1024 * 1024) {
    showError('Image is too large (maximum 8 MB).');
    return;
  }
  currentFile = file;
  if (!sameDocument || !savedForm) {
    savedForm = { version: 1, file, name: file.name, results: {} };
  }
  savedForm.file = file;
  updatePageControls();
  storeForm(); // Persist upload before inference; an interrupted request restarts.
  const language = languageSelect.value;
  const key = resultKey(language);
  const current = generation;
  controller = new AbortController();
  objectUrl = URL.createObjectURL(file);
  preview.src = objectUrl;
  document.querySelector('#filename').textContent = file.name;
  document.querySelector('#loading-filename').textContent = file.name;
  document.querySelector('#loading-title').textContent = 'Analyzing form…';
  emptyState.hidden = true;
  loadingState.hidden = false;
  resetButton.hidden = false;
  const cached = cachedResult();
  if (cached) { displayCached(cached); return; }
  const data = new FormData();
  data.append('image', file);
  data.append('language', language);
  try {
    const response = await fetch('/api/analyze', { method: 'POST', body: data, signal: controller.signal });
    const result = await response.json();
    if (current !== generation) return;
    if (!response.ok) throw new Error(result.error || 'Could not analyze this image.');
    const cached = { fields: result.fields, selected: result.fields[0]?.id ?? null, explanations: {} };
    savedForm.results[key] = cached;
    displayCached(cached);
    storeForm();
  } catch (err) {
    if (current !== generation || err.name === 'AbortError') return;
    clear(true);
    currentFile = file;
    resetButton.hidden = false;
    updatePageControls();
    showError(err.message || 'Could not analyze this image.');
  } finally {
    if (current === generation) controller = null;
  }
}

function validLanguage(value) {
  return Array.from(languageSelect.options).some(option => option.value === value) ? value : 'en';
}
function storageWarning() {
  const notice = document.querySelector('#storage-notice');
  if (notice) {
    notice.textContent = 'Browser storage is unavailable or full. Changes may not survive reload; Start over may not clear previously saved data. Clear site data in your browser if needed.';
    notice.hidden = false;
  }
}
try { languageSelect.value = validLanguage(localStorage.getItem('formfriend-language')); }
catch { languageSelect.value = 'en'; storageWarning(); }

languageSelect.addEventListener('change', () => {
  languageSelect.value = validLanguage(languageSelect.value);
  try { localStorage.setItem('formfriend-language', languageSelect.value); }
  catch { storageWarning(); }
  if (currentFile) analyze(currentFile, true);
});
pageSelect.addEventListener('change', () => selectPdfPage(Number(pageSelect.value)));
input.addEventListener('change', () => uploadImage(input.files[0]));
explainButton.addEventListener('click', explainSelectedField);
resetButton.addEventListener('click', () => clear());
for (const event of ['dragenter', 'dragover']) dropZone.addEventListener(event, e => { e.preventDefault(); dropZone.classList.add('dragging'); });
for (const event of ['dragleave', 'drop']) dropZone.addEventListener(event, e => { e.preventDefault(); dropZone.classList.remove('dragging'); });
dropZone.addEventListener('drop', e => uploadImage(e.dataTransfer.files[0]));
window.addEventListener('beforeunload', () => { if (objectUrl) URL.revokeObjectURL(objectUrl); });
restoreForm();
