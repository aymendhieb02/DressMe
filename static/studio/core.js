export const ROOT = '/studio-api';
export const PAGES = [
  ['bo6-wardrobe', 'My Wardrobe'], ['bo6-add', 'Add Garment'],
  ['bo7-avatar', 'My Avatar'], ['bo7-tryon', 'Virtual Try-On'], ['bo7-history', 'Try-On History'],
];

export const state = {
  user: null, csrf: null, pending: null, uploadKey: null, previewUrls: {},
  uploadGeneration: 0, publicConfig: null, garments: [], photos: [], jobs: [],
  selected: null, busy: false, avatarConfig: null, avatarSdk: null,
  avatarGate: null, avatarConsent: null, authView: 'login', authEmail: '',
  returnPage: 'bo6-wardrobe', focusAfterRender: null,
  renderVersion: 0,
  filters: {q: '', category: '', color: '', sort: 'newest', page: 1},
  tryOnIdempotencyKey: null,
};

export const $ = (selector, root = document) => root?.querySelector(selector) ?? null;
export const $$ = (selector, root = document) => root ? [...root.querySelectorAll(selector)] : [];
export const esc = value => String(value ?? '').replace(/[&<>"']/g, character => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[character]));
export const active = () => location.hash.slice(1);
export const node = () => document.querySelector(`[data-studio-page="${active()}"]`);
export const image = url => ROOT + url;

export function message(text, error = false) {
  const target = $('.studio-status', node()) || document.querySelector('.studio-status');
  if (!target) return;
  target.textContent = text;
  target.setAttribute('role', error ? 'alert' : 'status');
  target.classList.toggle('is-error', error);
}

export async function request(path, {method = 'GET', body, key, retry = true} = {}) {
  const headers = {};
  if (body && !(body instanceof FormData)) headers['Content-Type'] = 'application/json';
  if (key) headers['Idempotency-Key'] = key;
  if (!['GET', 'HEAD'].includes(method) && state.csrf) headers['X-CSRF-Token'] = state.csrf;
  let response;
  try {
    response = await fetch(ROOT + path, {
      method, headers,
      body: body instanceof FormData ? body : body === undefined ? undefined : JSON.stringify(body),
      credentials: 'same-origin',
    });
  } catch {
    throw new Error('DressMe is unavailable right now. Check the local services and try again.');
  }
  if (response.status === 403 && retry && state.user) {
    const detail = await response.clone().json().catch(() => ({}));
    if (detail.error?.code === 'csrf_failed') {
      await csrf();
      return request(path, {method, body, key, retry: false});
    }
  }
  if (response.status === 401 && state.user) {
    clearPrivateState();
    document.dispatchEvent(new CustomEvent('dressme:session-expired'));
    throw new Error('Your session expired. Sign in again to continue.');
  }
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    const reason = detail.error?.message || detail.detail?.message || detail.detail;
    throw new Error(typeof reason === 'string' ? reason : `Request failed (${response.status}).`);
  }
  return response.status === 204 ? null : response.json();
}

export async function csrf() {
  let response;
  try {
    response = await fetch(ROOT + '/auth/csrf', {
      method: 'POST', headers: {'X-CSRF-Bootstrap': '1'}, credentials: 'same-origin',
    });
  } catch {
    throw new Error('The application service could not verify this session.');
  }
  if (!response.ok) throw new Error('Your session could not be verified. Sign in again.');
  state.csrf = (await response.json()).csrf_token;
}

export async function loadPublicConfig() {
  try {
    const response = await fetch('/api/studio-config', {credentials: 'same-origin'});
    if (!response.ok) throw new Error();
    state.publicConfig = await response.json();
  } catch {
    state.publicConfig = null;
  }
}

export async function loadSession() {
  try {
    state.user = await request('/auth/me');
    await csrf();
  } catch {
    state.user = null;
    state.csrf = null;
  }
}

export function clearPrivateState() {
  for (const url of Object.values(state.previewUrls)) URL.revokeObjectURL(url);
  state.previewUrls = {};
  state.user = null;
  state.csrf = null;
  state.pending = null;
  state.uploadKey = null;
  state.uploadGeneration += 1;
  state.garments = [];
  state.photos = [];
  state.jobs = [];
  state.selected = null;
  state.tryOnIdempotencyKey = null;
  state.avatarConsent = null;
  state.filters = {q: '', category: '', color: '', sort: 'newest', page: 1};
}

export function clearLoadedPrivateData() {
  for (const url of Object.values(state.previewUrls)) URL.revokeObjectURL(url);
  state.previewUrls = {};
  state.garments = [];
  state.photos = [];
  state.jobs = [];
  state.selected = null;
  state.avatarConsent = null;
  state.pending = null;
  state.uploadKey = null;
  state.filters = {q: '', category: '', color: '', sort: 'newest', page: 1};
  state.tryOnIdempotencyKey = null;
}

export function studioPage(id) {
  return PAGES.some(([page]) => page === id) ? id : 'bo6-wardrobe';
}
