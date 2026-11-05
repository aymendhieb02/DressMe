/* Studio shell and event routing. Feature modules live in /static/studio/. */
import {
  PAGES, state, $, esc, active, node, message, request, loadPublicConfig,
  loadSession, clearPrivateState, clearLoadedPrivateData, studioPage,
  refreshSession,
} from './studio/core.js?v=bo7queue1';
window.refreshDressMe = refreshSession;
import {authForm, handleAuthSubmit, handleAuthView, handlePasswordVisibility, safeDestination} from './studio/auth.js?v=bo7queue1';
import {
  wardrobeContent, addGarmentContent, renderWardrobe, review, detail, NO_SLEEVES,
  syncSuggestionState, chooseSuggestion, handleConfirmedChange, generateDescription,
  saveReview, saveEdit, regenerateDetailDescription,
} from './studio/wardrobe.js?v=bo7queue1';
import {
  avatarContent, refreshAvatar, closeAvatarSdk, saveAvatarImport, handleAvatarAction,
} from './studio/avatar.js?v=bo7queue1';
import {
  tryonContent, historyContent, refreshTryon, refreshHistory, savePersonPhoto,
  updateSubmitAvailability, handleTryonAction, rememberPersonSource,
} from './studio/tryon.js?v=bo7queue1';
import {
  abandonPending, clearUpload, handleUploadSelection, handleDrop, handleDragOver,
  clearDrag, validateUpload,
} from './studio/upload.js?v=bo7queue1';

function content(page) {
  if (page === 'bo6-wardrobe') return wardrobeContent();
  if (page === 'bo6-add') return addGarmentContent();
  if (page === 'bo7-avatar') return avatarContent();
  if (page === 'bo7-tryon') return tryonContent();
  return historyContent();
}

function shell(page) {
  if (!state.user) {
    return `<div class="studio studio-auth-shell" aria-busy="false"><div class="studio-auth-public"><a class="studio-auth-brand" href="/" aria-label="DressMe landing page">DressMe <span>Your workspace</span></a><a href="/">Back to landing page</a></div><div class="studio-auth-layout"><aside class="studio-auth-story"><p class="studio-eyebrow">The DressMe experience</p><h2>Style starts with what you own.</h2><p>Explore your daily edit, refine a look, and keep your wardrobe together in one place.</p><ol><li><span>01</span> Find your daily edit</li><li><span>02</span> Explore your style</li><li><span>03</span> Build your wardrobe</li></ol></aside><div class="studio-body studio-auth-body">${authForm()}</div></div></div>`;
  }
  const currentTitle = PAGES.find(([id]) => id === page)?.[1] || 'My Studio';
  const studioLinks = PAGES.map(([id, title]) => `<a href="#${id}" ${id === page ? 'aria-current="page"' : ''}>${title}</a>`).join('');
  return `<div class="studio" aria-busy="false"><div class="studio-body"><div class="studio-head"><div><p class="studio-eyebrow">Your workspace</p><h2>${esc(currentTitle)}</h2></div></div><div class="studio-status" role="status" aria-live="polite"></div>${content(page)}</div></div>`;
}

let authAnimation;

function runRefresh(page, version = state.renderVersion) {
  const work = page === 'bo6-wardrobe' ? renderWardrobe(state.filters.page, version)
    : page === 'bo7-avatar' ? refreshAvatar(version)
    : page === 'bo7-tryon' ? refreshTryon(version)
    : page === 'bo7-history' ? refreshHistory(version)
    : Promise.resolve();
  return work.catch(error => { if (version === state.renderVersion && active() === page) message(error.message, true); });
}

function render() {
  const page = active();
  if (!PAGES.some(([id]) => id === page)) return;
  const version = ++state.renderVersion;
  const target = node();
  if (!target) return;
  if (page !== 'bo7-avatar') closeAvatarSdk();
  document.querySelectorAll('[data-studio-page]').forEach(other => {
    if (other !== target) other.replaceChildren();
  });
  target.innerHTML = shell(page);
  if (!state.user) {
    $('.studio-auth-card', target)?.insertAdjacentHTML('beforeend', '<div class="studio-status" role="status" aria-live="polite"></div>');
    authAnimation?.kill();
    if (!matchMedia('(prefers-reduced-motion: reduce)').matches && window.gsap) {
      authAnimation = window.gsap.timeline({defaults: {ease: 'power3.out'}})
        .fromTo('.studio-auth-story', {opacity: 0, x: -28}, {opacity: 1, x: 0, duration: .65})
        .fromTo('.studio-auth-card', {opacity: 0, y: 20}, {opacity: 1, y: 0, duration: .55}, .12);
    }
  }
  if (state.user) {
    runRefresh(page, version);
    if (page === 'bo6-add' && state.pending) review();
  }
  if (state.focusAfterRender) {
    $(state.focusAfterRender)?.focus();
    state.focusAfterRender = null;
  }
}

async function safe(action, source) {
  if (state.busy) {
    message('This action is still processing. Wait for it to finish before retrying.');
    return;
  }
  state.busy = true;
  const form = source?.closest('form');
  const studio = source?.closest('.studio') || $('.studio');
  studio?.setAttribute('aria-busy', 'true');
  const submitButtons = form ? [...form.querySelectorAll('button[type="submit"],button:not([type])')] : [];
  const priorDisabled = submitButtons.map(button => button.disabled);
  submitButtons.forEach(button => { button.disabled = true; });
  if (form) form.setAttribute('aria-busy', 'true');
  try { await action(); }
  catch (error) { message(error.message || 'That action could not be completed. Try again.', true); }
  finally {
    submitButtons.forEach((button, index) => { button.disabled = priorDisabled[index]; });
    form?.removeAttribute('aria-busy');
    studio?.setAttribute('aria-busy', 'false');
    state.busy = false;
  }
}

document.addEventListener('submit', event => {
  const form = event.target;
  if (!form.closest('.studio')) return;
  event.preventDefault();
  const formId = form.getAttribute('id');
  safe(async () => {
    if (['studio-auth', 'studio-recovery-request', 'studio-recovery-verify', 'studio-recovery-complete'].includes(formId)) {
      return handleAuthSubmit(form, render);
    }
    if (formId === 'studio-upload') {
      const file = await validateUpload(form.elements.image);
      const generation = state.uploadGeneration;
      state.uploadKey ||= crypto.randomUUID();
      const data = new FormData();
      data.append('image', file);
      let result;
      try {
        result = await request('/garments/analyze', {method: 'POST', body: data, key: state.uploadKey});
      } catch (error) {
        if (error.code !== 'ml_unavailable') throw error;
        result = await request('/garments/uploads/manual', {method: 'POST', body: data});
      }
      if (generation !== state.uploadGeneration || active() !== 'bo6-add') {
        try { await request('/garments/uploads/' + result.id, {method: 'DELETE'}); } catch { /* expiry cleanup remains available */ }
        return;
      }
      state.pending = result;
      review();
      message(result.prediction?.status === 'unavailable'
        ? 'Automatic analysis is unavailable. Enter the details and a short description yourself.'
        : 'Analysis complete. Review the suggestions and confirm every required value.');
      return;
    }
    if (formId === 'studio-confirm') return saveReview(form);
    if (formId === 'studio-edit') return saveEdit(form);
    if (formId === 'studio-person') return savePersonPhoto(form);
    if (formId === 'studio-avatar-import') return saveAvatarImport(form, runRefresh);
  }, form);
});

document.addEventListener('change', event => {
  const input = event.target;
  if (input.matches('.studio-upload-input')) {
    safe(() => handleUploadSelection(input), input);
    return;
  }
  if (input.closest('#studio-confirm')) handleConfirmedChange(event);
  if (input.matches('#studio-edit select[name="category"]')) {
    const form = input.form;
    const sleeve = form.elements.sleeve_length;
    if (NO_SLEEVES.has(input.value)) { sleeve.value = ''; sleeve.disabled = true; }
    else sleeve.disabled = false;
  }
  if (input.matches('.studio-garment-input,#studio-photo,#studio-avatar-consent')) updateSubmitAvailability();
});

document.addEventListener('dragover', handleDragOver);
document.addEventListener('dragleave', clearDrag);
document.addEventListener('drop', event => safe(() => handleDrop(event)));

document.addEventListener('click', event => {
  const viewButton = event.target.closest('[data-auth-view]');
  if (viewButton && viewButton.closest('.studio')) {
    event.preventDefault();
    state.authEmail = $('input[name="email"]', viewButton.closest('.studio'))?.value || state.authEmail;
    handleAuthView(viewButton.dataset.authView, render);
    $('.studio-auth-card form input')?.focus();
    return;
  }
  const toggle = event.target.closest('[data-auth-toggle]');
  if (toggle) { handlePasswordVisibility(toggle); return; }
  const button = event.target.closest('[data-action]');
  if (!button || !button.closest('.studio')) return;
  const action = button.dataset.action;
  safe(async () => {
    if (action === 'show-local-recovery') {
      const query = new URLSearchParams({email: state.authEmail});
      const response = await fetch('/api/dev-recovery-message?' + query, {credentials: 'same-origin'});
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.detail || 'No recent local recovery email was found. Request another code after the one-minute cooldown.');
      message(`Local recovery code: ${result.code}. Enter it above to continue.`);
      return;
    }
    if (action === 'logout') {
      await abandonPending();
      await request('/auth/logout', {method: 'POST'});
      closeAvatarSdk();
      clearPrivateState();
      window.location.replace('/');
      return;
    }
    if (action === 'clear-upload') return clearUpload(button.dataset.uploadKey);
    if (action === 'suggest-category' || action === 'suggest-attribute') return chooseSuggestion(button);
    if (action === 'filter') return renderWardrobe(1);
    if (action === 'reset-filters') {
      state.filters = {q: '', category: '', color: '', sort: 'newest', page: 1};
      render();
      return;
    }
    if (action === 'page') return renderWardrobe(Number(button.dataset.page));
    if (action === 'detail') return detail(button.dataset.id);
    if (action === 'close-detail') {
      const focusTarget = state.selected?.id ? $(`button[data-action="detail"][data-id="${CSS.escape(state.selected.id)}"]`) : null;
      $('#studio-detail', node()).replaceChildren();
      state.selected = null;
      focusTarget?.focus();
      return;
    }
    if (action === 'delete-garment') {
      if (!confirm('Delete this garment and its private image?')) return;
      await request('/garments/' + button.dataset.id, {method: 'DELETE'});
      $('#studio-detail', node()).replaceChildren();
      state.selected = null;
      await renderWardrobe(state.filters.page);
      message('Garment and private image deleted.');
      return;
    }
    if (action === 'describe') return generateDescription();
    if (action === 'discard-review') {
      await abandonPending();
      await clearUpload('garment');
      $('#studio-review', node()).replaceChildren();
      message('Review discarded. Choose a photo when you are ready.');
      return;
    }
    if (action === 'regenerate-detail') return regenerateDetailDescription();
    if (['delete-avatar', 'open-creator', 'close-creator'].includes(action)) {
      return handleAvatarAction(action, button, {refresh: runRefresh, safe});
    }
    return handleTryonAction(action, button, runRefresh);
  }, button);
});

let lastSection = active();
document.addEventListener('dressme:section', event => {
  const previous = lastSection;
  lastSection = event.detail;
  if (PAGES.some(([id]) => id === event.detail)) {
    if (previous === 'bo6-add' && event.detail !== 'bo6-add') {
      safe(async () => { await abandonPending(); await clearUpload('garment'); });
    }
    render();
    return;
  }
  state.renderVersion += 1;
  closeAvatarSdk();
  if (previous === 'bo6-add') safe(async () => { await abandonPending(); await clearUpload('garment'); });
  document.querySelectorAll('[data-studio-page]').forEach(section => section.replaceChildren());
  clearLoadedPrivateData();
});

document.addEventListener('input', event => {
  if (!event.target.closest('#studio-edit')) return;
  const form = event.target.form;
  const original = state.selected;
  const regen = $('[data-action="regenerate-detail"]', form);
  if (!regen || !original) return;
  const data = Object.fromEntries(new FormData(form));
  const dirty = ['name', 'category', 'garment_photo_type', 'color', 'pattern', 'sleeve_length', 'material', 'description', 'notes']
    .some(key => (data[key] || null) !== (original[key] || null));
  regen.disabled = dirty;
  regen.setAttribute('aria-label', dirty ? 'Save changes before regenerating the description' : 'Regenerate description from confirmed values');
  const status = $('[data-edit-status]', form);
  if (status) status.textContent = dirty && !original.description_is_manual
    ? 'Save your edits to regenerate the automatic description from the updated confirmed attributes.' : '';
});

document.addEventListener('change', event => {
  if (event.target.matches('.studio-garment-input,#studio-photo')) state.tryOnIdempotencyKey = null;
  if (event.target.matches('#studio-photo')) rememberPersonSource(event.target.value);
});

document.addEventListener('dressme:session-expired', () => {
  closeAvatarSdk();
  state.authView = 'login';
  const next = encodeURIComponent('/app' + location.hash);
  location.replace('/login?next=' + next + '&reason=' + (state.sessionReason || 'expired'));
});

$('#headerSignout')?.addEventListener('click', () => safe(async () => {
  await request('/auth/logout', {method: 'POST'});
  clearPrivateState();
  location.replace('/');
}));

$('#account-gender-form')?.addEventListener('submit', event => {
  event.preventDefault();
  safe(async () => {
    try {
      const gender = event.target.elements.gender.value;
      state.user = await request('/auth/me', {method:'PATCH', body:{gender}});
      $('#account-gender-status').textContent = 'Genre enregistré. Le chat l’utilise pour tes prochaines demandes.';
      const label = document.getElementById('assistant-gender');
      if (label) label.textContent = {men:'Genre du compte : homme.',women:'Genre du compte : femme.'}[gender] || 'Aucun filtre de genre par défaut.';
    } catch (error) { $('#account-gender-status').textContent = error.message; }
  }, event.target);
});

window.addEventListener('hashchange', () => {
  if (document.getElementById(active()) && typeof window.go === 'function') window.go(active(), true);
});

state.returnPage = studioPage(active());
if (location.pathname === '/login') {
  const requested = new URLSearchParams(location.search).get('view');
  if (['register', 'forgot', 'reset'].includes(requested)) state.authView = requested;
}
Promise.all([loadPublicConfig(), loadSession()]).then(() => {
  if (location.pathname === '/login' && state.user) { location.replace(safeDestination()); return; }
  if (location.pathname === '/app' && !state.user) {
    location.replace('/login?next=' + encodeURIComponent('/app' + location.hash)
      + (state.sessionReason ? '&reason=' + state.sessionReason : ''));
    return;
  }
  $('#accountEmail').textContent = state.user?.email || '';
  if ($('#account-gender-form')) $('#account-gender-form').elements.gender.value = state.user?.gender || '';
  render();
  if (location.pathname === '/login' && new URLSearchParams(location.search).get('reason')) {
    message(new URLSearchParams(location.search).get('reason') === 'elsewhere'
      ? 'Your account was signed in elsewhere. Sign in again to continue.'
      : 'Your session expired. Sign in again to continue.');
  }
  if (state.user) {
    document.dispatchEvent(new CustomEvent('dressme:authenticated'));
    window.startAppCatalog?.();
  }
  else if (location.pathname === '/login') {
    fetch('/api/public-style-wall', {credentials: 'same-origin'})
      .then(response => response.ok ? response.json() : [])
      .then(items => { if (items.length) window.renderPublicStyleWall?.(items); })
      .catch(() => {});
  }
});
