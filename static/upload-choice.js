// Progressive enhancement: on touch-first devices, tapping the drop zone offers
// a photo (library or camera, as the browser allows) or a file. Both choices
// feed app.js's existing upload path. Desktop keeps the native label picker.
(() => {
  const dropZone = document.querySelector('#drop-zone');
  const fileInput = document.querySelector('#image-input');
  const photoInput = document.querySelector('#photo-input');
  const sheet = document.querySelector('#upload-sheet');
  if (!dropZone || !fileInput) return;
  const coarse = typeof window.matchMedia === 'function' ? window.matchMedia('(pointer: coarse)') : null;
  const offersChoice = () => Boolean(coarse?.matches && photoInput && sheet && typeof sheet.showModal === 'function');

  function syncPopupState() {
    if (offersChoice()) dropZone.setAttribute('aria-haspopup', 'dialog');
    else dropZone.removeAttribute('aria-haspopup');
  }
  function openPicker(input) {
    if (sheet?.open) sheet.close();
    input.click(); // Synchronous, so the browser still sees the user's tap.
  }
  function activate() {
    if (!offersChoice()) { openPicker(fileInput); return; }
    if (sheet.open) return;
    sheet.showModal();
    sheet.querySelector('[data-upload-choice]')?.focus();
  }

  dropZone.addEventListener('click', event => {
    // Clicks forwarded to the input (including openPicker's) bubble back here.
    if (event.target === fileInput || !offersChoice()) return;
    event.preventDefault();
    activate();
  });
  dropZone.addEventListener('keydown', event => {
    if (event.target !== dropZone || (event.key !== 'Enter' && event.key !== ' ')) return;
    event.preventDefault();
    activate();
  });
  sheet?.addEventListener('click', event => {
    const choice = event.target.closest?.('[data-upload-choice]');
    if (choice) {
      openPicker(choice.dataset.uploadChoice === 'photo' ? photoInput : fileInput);
    } else if (event.target === sheet || event.target.closest?.('[data-upload-cancel]')) {
      sheet.close(); // The dialog's own area outside the panel is the backdrop.
    }
  });
  coarse?.addEventListener?.('change', syncPopupState);
  syncPopupState();
})();
