// Progressive enhancement: app.js owns the native select and preference storage.
(() => {
  const select = document.querySelector('#language-select');
  const picker = document.querySelector('#language-picker');
  if (!select || !picker) return;

  const make = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  };
  const trigger = make('button', 'language-picker-button');
  trigger.type = 'button';
  trigger.id = 'language-picker-button';
  trigger.setAttribute('aria-haspopup', 'dialog');
  trigger.setAttribute('aria-expanded', 'false');
  trigger.setAttribute('aria-controls', 'language-picker-panel');
  const globe = make('span', 'language-globe', '🌐');
  globe.setAttribute('aria-hidden', 'true');
  const caption = make('span', 'language-caption', 'Help in');
  const current = make('bdi', 'language-current');
  const chevron = make('span', 'language-chevron', '⌄');
  chevron.setAttribute('aria-hidden', 'true');
  trigger.append(globe, caption, current, chevron);

  const panel = make('div', 'language-picker-panel');
  panel.id = 'language-picker-panel';
  panel.hidden = true;
  panel.setAttribute('role', 'dialog');
  panel.setAttribute('aria-label', 'Choose help language');
  const note = make('p', 'language-panel-note');
  note.id = 'language-picker-note';
  const searchLabel = make('label', 'language-search-label', 'Search languages');
  searchLabel.htmlFor = 'language-picker-search';
  const search = make('input', 'language-search');
  search.id = 'language-picker-search';
  search.type = 'search';
  search.placeholder = 'Search languages';
  search.autocomplete = 'off';
  search.spellcheck = false;
  const list = make('div', 'language-options');
  list.setAttribute('role', 'group');
  list.setAttribute('aria-label', 'Languages');
  const empty = make('p', 'language-empty', 'No languages found');
  empty.id = 'language-picker-empty';
  empty.setAttribute('role', 'status');
  empty.hidden = true;

  const normalize = text => text.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase();
  const choices = Array.from(select.options, option => {
    const button = make('button', 'language-option');
    button.type = 'button';
    const nativeName = make('bdi', 'language-native', option.textContent.trim());
    nativeName.lang = option.value;
    const englishName = option.dataset.english || option.textContent.trim();
    button.append(nativeName, make('span', 'language-english', englishName));
    button.addEventListener('click', () => {
      if (select.value !== option.value) {
        select.value = option.value;
        select.dispatchEvent(new Event('change', { bubbles: true }));
      }
      close(true);
    });
    list.append(button);
    return { option, button, searchText: normalize(`${option.textContent} ${englishName}`) };
  });

  function sync() {
    const selected = select.options[select.selectedIndex];
    if (!selected) return;
    current.textContent = selected.textContent.trim();
    current.lang = selected.value;
    trigger.setAttribute('aria-label', `Help language: ${selected.textContent.trim()}`);
    choices.forEach(({ option, button }) => button.setAttribute('aria-pressed', String(option.value === select.value)));
  }
  // A loaded (or loading) form is re-analyzed when the help language changes.
  const formLoaded = () => ['#result-state', '#loading-state'].some(selector => {
    const element = document.querySelector(selector);
    return Boolean(element && !element.hidden && element.getClientRects().length);
  });
  function updateNote() {
    note.textContent = 'Field names, tips and answers appear in this language.'
      + (formLoaded() ? ' Changing it re-reads your form.' : '');
  }
  function filter() {
    const query = normalize(search.value.trim());
    choices.forEach(choice => { choice.button.hidden = !choice.searchText.includes(query); });
    empty.hidden = choices.some(choice => !choice.button.hidden);
  }
  function close(restoreFocus = false) {
    panel.hidden = true;
    trigger.setAttribute('aria-expanded', 'false');
    if (restoreFocus) trigger.focus();
  }
  trigger.addEventListener('click', () => {
    if (!panel.hidden) { close(); return; }
    sync();
    updateNote();
    search.value = '';
    filter();
    panel.hidden = false;
    trigger.setAttribute('aria-expanded', 'true');
    search.focus();
  });
  search.addEventListener('input', filter);
  picker.addEventListener('keydown', event => {
    if (panel.hidden) return;
    if (event.key === 'Escape') { event.preventDefault(); close(true); return; }
    const visible = choices.filter(choice => !choice.button.hidden).map(choice => choice.button);
    const index = visible.indexOf(document.activeElement);
    if (event.key === 'ArrowDown' && visible.length) {
      event.preventDefault();
      visible[(index + 1) % visible.length].focus();
    } else if (event.key === 'ArrowUp' && visible.length) {
      event.preventDefault();
      visible[index <= 0 ? visible.length - 1 : index - 1].focus();
    }
  });
  document.addEventListener('click', event => {
    if (!picker.contains(event.target)) close();
  });
  picker.addEventListener('focusout', event => {
    // Safari can report no relatedTarget when a mouse click moves focus to a
    // button. Closing here would hide that button before its click fires.
    // Outside pointer clicks are handled by the document click listener.
    if (event.relatedTarget && !picker.contains(event.relatedTarget)) close();
  });
  select.addEventListener('change', sync);
  panel.append(note, searchLabel, search, list, empty);
  picker.append(trigger, panel);
  sync(); // Defer script runs after app.js restores the canonical native value.
  picker.querySelector('.language-control').hidden = true;
  picker.classList.add('language-enhanced');
})();
