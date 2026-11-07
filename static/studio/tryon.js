import {state, $, esc, active, image, node, request, message} from './core.js?v=bo7photos1';
import {uploadPicker, validateUpload, clearUpload} from './upload.js?v=bo7photos1';

const isReal = () => state.publicConfig?.vton_mode === 'real';
const isRemote = () => isReal() && state.publicConfig?.vton_remote === true;
const AVATAR_SOURCE = 'avatar';
// Measured: one image took 282 seconds on the Kaggle server. Lower this once requests get faster.
const MINUTES_PER_IMAGE = 5;
const HISTORY_POLL_MS = 10000;
const sourceKey = () => `dressme.tryon.source.${state.user?.id}`;
const FAILURES = {
  remote_unavailable: 'The try-on server could not be reached. It may be offline.',
  remote_busy: 'The try-on server was busy with another image. Send this one again in a few minutes.',
  remote_auth_failed: 'The try-on server refused the request.',
  remote_inference_failed: 'The try-on server could not generate this image.',
  remote_bad_response: 'The try-on server sent back something unusable.',
  worker_lost: 'The worker stopped before this image was finished.',
};

const minutes = count => count === 1 ? 'about 1 minute' : `about ${count} minutes`;
const waitText = count => isReal() ? minutes(count * MINUTES_PER_IMAGE) : 'a few seconds';
// The database stores UTC without saying so, and the browser would read that as local time.
const localDate = value => new Date(/(Z|[+-]\d\d:\d\d)$/.test(value) ? value : `${value}Z`);
const plural = (count, word) => `${count} ${word}${count === 1 ? '' : 's'}`;

export function rememberPersonSource(value) {
  try { localStorage.setItem(sourceKey(), value); } catch { /* the choice just is not remembered */ }
}

function rememberedSource() {
  try { return localStorage.getItem(sourceKey()); } catch { return null; }
}

function badge() {
  if (isRemote()) return `Real try-on · runs on the remote GPU server, ${waitText(1)} per image`;
  return isReal() ? 'Real try-on · generated on this machine, about 2 minutes per image' : 'MOCK · no virtual try-on model runs in this application';
}

function consentNote() {
  if (isRemote()) return 'virtual try-on, including sending it to the remote GPU server on Kaggle';
  return isReal() ? 'virtual try-on' : 'mock try-on';
}

export function tryonContent() {
  return `<p class="studio-badge">${badge()}</p><p class="studio-muted">Choose who to dress, tick one or more pieces from your wardrobe and send them to the queue.</p><div id="studio-tryon-notice" aria-live="polite"></div><div id="studio-tryon-controls" class="studio-panel"></div><details class="studio-more" id="studio-saved-photos" hidden><summary>Saved photos</summary><div class="studio-saved-photos" id="studio-saved-photo-list"></div></details><details class="studio-more" id="studio-person-panel"><summary>Add a new person photo</summary><form id="studio-person" class="studio-form">${uploadPicker({key: 'person-photo', name: 'image', title: 'Choose one person photo', accept: 'image/jpeg,image/png,image/webp', note: 'JPEG, PNG or WebP · private storage'})}<label class="studio-consent"><input name="consent" type="checkbox" required> I consent to private processing of this photo for ${consentNote()}.</label><button class="btn ghost" type="submit">Save consented photo</button></form></details>`;
}

export function historyContent() {
  return `<p class="studio-badge">${isReal() ? 'Try-on history' : 'MOCK history · previews are not generated clothing transfer'}</p><div id="studio-jobs" aria-live="polite"></div>`;
}

function garmentCard(garment, preselected) {
  const name = esc(garment.name || garment.category);
  const img = `<img src="${image(garment.image_url)}" alt="" loading="lazy">`;
  if (!garment.vton_eligibility?.candidate_category) {
    return `<div class="studio-garment-pick is-blocked">${img}<span>${name}</span><small>Not supported yet</small></div>`;
  }
  return `<label class="studio-garment-pick"><input class="studio-garment-input" type="checkbox" value="${garment.id}" ${garment.id === preselected ? 'checked' : ''} aria-label="Try on ${name}">${img}<span>${name}</span></label>`;
}

function savedPhotoCard(photo) {
  const label = `${photo.from_avatar ? 'Avatar image' : 'Saved photo'} · ${localDate(photo.created_at).toLocaleDateString()}`;
  return `<div class="studio-saved-photo"><img class="studio-person-thumb" src="${image(photo.image_url)}" alt="${esc(label)}"><p class="studio-muted">${esc(label)}</p><button class="btn danger" data-action="delete-photo" data-id="${photo.id}">Delete</button></div>`;
}

export async function refreshTryon(version = state.renderVersion) {
  let runtime;
  try {
    runtime = await request('/health/try-on');
  } catch {
    runtime = {available: false, reason: 'backend_unavailable'};
  }
  const [garments, photos, avatarRender, avatarPhoto] = await Promise.all([
    request('/garments?page_size=50'), request('/person-photos'),
    request('/avatars/current/render'), request('/person-photos/from-avatar'),
  ]);
  if (version !== state.renderVersion || active() !== 'bo7-tryon') return;
  state.garments = garments.items;
  state.photos = photos;
  state.avatarSource = {render: avatarRender, photo: avatarPhoto};
  const eligible = state.garments.filter(garment => garment.vton_eligibility?.candidate_category);
  const saved = photos.filter(photo => photo.id !== avatarPhoto?.id);
  const sources = [
    ...(avatarRender ? [{value: AVATAR_SOURCE, label: 'My avatar'}] : []),
    ...saved.map(photo => ({value: photo.id, label: `Saved photo · ${localDate(photo.created_at).toLocaleDateString()}`})),
  ];
  const remembered = rememberedSource();
  const chosen = sources.some(source => source.value === remembered) ? remembered : sources[0]?.value;
  const preselected = state.tryonGarment;
  state.tryonGarment = null;

  const notice = $('#studio-tryon-notice', node());
  if (notice) notice.innerHTML = state.tryonNotice || '';
  state.tryonNotice = null;

  const status = runtime.available
    ? (isReal() ? 'A worker is ready. Images are made one at a time, in order.' : 'A worker is available. Submissions create MOCK jobs only.')
    : `Submission is disabled because the worker is unavailable (${esc(runtime.reason || 'unknown')}). Start Redis and the RQ worker, then reload this page.`;
  const form = `<div class="studio-tryon-grid"><div><label>Who to dress<select id="studio-photo">${sources.map(source => `<option value="${source.value}" ${source.value === chosen ? 'selected' : ''}>${esc(source.label)}</option>`).join('')}</select></label><img class="studio-person-thumb" id="studio-person-preview" alt="The selected image for try-on"><label class="studio-consent" id="studio-avatar-consent-label" hidden><input type="checkbox" id="studio-avatar-consent"> I consent to using my avatar image for ${consentNote()}.</label></div><div><strong>Clothes from your wardrobe</strong><div class="studio-garment-grid">${state.garments.map(garment => garmentCard(garment, preselected)).join('')}</div></div></div><div class="studio-actions"><button class="btn" data-action="submit-mock" disabled>Generate</button></div><p class="studio-muted">Your choice of who to dress is remembered as the default on this browser.</p>`;
  const empty = `<section class="studio-empty"><h3>${eligible.length ? 'Create your avatar first' : 'Save an eligible garment first'}</h3><p>This workflow needs an owned candidate garment, and your avatar or a saved photo.</p><a class="btn ghost" href="${eligible.length ? '#bo7-avatar' : '#bo6-add'}">${eligible.length ? 'Create my avatar' : 'Add garment'}</a></section>`;
  const target = $('#studio-tryon-controls', node());
  target.innerHTML = `<div class="studio-result-head"><div><p class="studio-eyebrow">Worker status</p><h3>${isReal() ? 'Try-on queue' : 'Mock preview queue'}</h3></div><span class="studio-badge ${runtime.available ? 'is-ready' : 'is-unavailable'}">${runtime.available ? 'Ready' : 'Unavailable'}</span></div><p class="studio-muted">${status}</p>${eligible.length && sources.length ? form : empty}`;
  if (!sources.length) $('#studio-person-panel', node())?.setAttribute('open', '');
  $('#studio-saved-photos', node())?.toggleAttribute('hidden', !photos.length);
  $('#studio-saved-photo-list', node()).innerHTML = photos.map(savedPhotoCard).join('');
  await updateSubmitAvailability();
}

export async function savePersonPhoto(form) {
  const input = form.elements.image;
  await validateUpload(input);
  const data = new FormData(form);
  data.set('consent', 'true');
  await request('/person-photos', {method: 'POST', body: data});
  form.reset();
  await clearUpload('person-photo');
  await refreshTryon();
  message('Private person photo saved with your consent.');
}

const pickedGarments = () => [...node().querySelectorAll('.studio-garment-input:checked')].map(input => input.value);

export async function updateSubmitAvailability() {
  const button = $('[data-action="submit-mock"]', node());
  if (!button) return;
  const garments = pickedGarments();
  const photo = $('#studio-photo', node())?.value;
  const usingAvatar = photo === AVATAR_SOURCE;
  const preview = $('#studio-person-preview', node());
  const shown = usingAvatar ? state.avatarSource?.render : state.photos.find(item => item.id === photo);
  if (preview && shown) preview.src = image(shown.image_url);
  const needsConsent = usingAvatar && !state.avatarSource?.photo;
  $('#studio-avatar-consent-label', node())?.toggleAttribute('hidden', !needsConsent);
  const consented = !needsConsent || $('#studio-avatar-consent', node())?.checked;
  button.textContent = garments.length > 1 ? `Generate ${garments.length} try-ons` : 'Generate try-on';
  const runtime = await request('/health/try-on').catch(() => ({available: false}));
  button.disabled = !runtime.available || !garments.length || !photo || !consented;
  button.setAttribute('aria-disabled', String(button.disabled));
}

function jobState(job) {
  if (job.state === 'queued') {
    const ahead = job.queue_position ?? 0;
    return {title: 'In the queue', detail: `${ahead ? `${plural(ahead, 'image')} ahead of this one. ` : 'Next in line. '}Ready in ${waitText(ahead + 1)}.`};
  }
  if (job.state === 'running') return {title: 'Generating now', detail: `Ready in ${waitText(1)} at most.`};
  if (job.state === 'succeeded') return {title: 'Ready', detail: ''};
  if (job.state === 'cancelled') return {title: 'Cancelled', detail: ''};
  if (job.state === 'timed_out') return {title: 'Took too long', detail: FAILURES[job.error_code] || 'You can try this one again.'};
  return {title: 'Failed', detail: FAILURES[job.error_code] || `Something went wrong (${esc(job.error_code || 'unknown')}).`};
}

function zoomable(url, title) {
  return `<button class="studio-zoom" type="button" data-action="zoom-image" data-src="${image(url)}" data-title="${esc(title)}" aria-label="Enlarge ${esc(title)}"><img src="${image(url)}" alt="${esc(title)}" loading="lazy"></button>`;
}

function jobCard(job) {
  const {title, detail} = jobState(job);
  const waiting = ['queued', 'running'].includes(job.state);
  const garment = esc(job.garment_category || 'Garment');
  const label = job.mode === 'real' ? 'Try-on result' : 'Mock preview';
  const result = job.result_url ? zoomable(job.result_url, label) : `<div class="studio-job-waiting">${esc(title)}</div>`;
  const actions = waiting
    ? (job.cancellation_requested ? '<span class="studio-muted">Cancelling…</span>' : `<button class="btn ghost" data-action="cancel-job" data-id="${job.id}">Cancel</button>`)
    : `<button class="btn danger" data-action="delete-job" data-id="${job.id}">Delete</button>`;
  return `<article class="studio-card"><div class="studio-result-head"><h3>${esc(title)}</h3><span class="studio-badge">${esc(job.mode.toUpperCase())}</span></div><p class="studio-muted">${localDate(job.created_at).toLocaleString()}${detail ? ` · ${detail}` : ''}</p><div class="studio-job-images"><figure><figcaption>Person</figcaption>${zoomable(job.person_image_url, 'Person')}</figure><figure><figcaption>${garment}</figcaption>${zoomable(job.garment_image_url, garment)}</figure><figure><figcaption>${label}</figcaption>${result}</figure></div><div class="studio-actions">${actions}</div></article>`;
}

export async function refreshHistory(version = state.renderVersion) {
  const result = await request('/try-on/jobs');
  if (version !== state.renderVersion || active() !== 'bo7-history') return;
  state.jobs = result.items;
  // Only redraw on a change, so the images do not reload every few seconds.
  const signature = JSON.stringify(state.jobs.map(job => [job.id, job.state, job.queue_position, job.cancellation_requested]));
  const target = $('#studio-jobs', node());
  if (signature !== state.jobsSignature || !target.childElementCount) {
    state.jobsSignature = signature;
    target.innerHTML = state.jobs.length
      ? `<div class="studio-job-list">${state.jobs.map(jobCard).join('')}</div>`
      : `<section class="studio-empty"><h3>No try-on jobs yet</h3><p>Completed ${isReal() ? 'try-on' : 'MOCK'} results will appear here after a worker processes a request.</p><a class="btn" href="#bo7-tryon">${isReal() ? 'Prepare a try-on' : 'Prepare a mock preview'}</a></section>`;
  }
  clearTimeout(state.historyTimer);
  if (state.jobs.some(job => ['queued', 'running'].includes(job.state))) {
    state.historyTimer = setTimeout(() => refreshHistory(version).catch(() => {}), HISTORY_POLL_MS);
  }
}

function lightbox() {
  let dialog = document.getElementById('studio-lightbox');
  if (dialog) return dialog;
  dialog = document.createElement('dialog');
  dialog.id = 'studio-lightbox';
  dialog.className = 'studio-lightbox';
  dialog.innerHTML = '<div class="studio-lightbox-head"><p></p><div><a download="dressme-try-on.png">Download</a> <button type="button" autofocus>Close</button></div></div><div class="studio-lightbox-view"><img alt=""></div>';
  const view = dialog.querySelector('.studio-lightbox-view');
  dialog.querySelector('button').addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
  view.querySelector('img').addEventListener('click', () => view.classList.toggle('is-zoomed'));
  dialog.addEventListener('close', () => view.classList.remove('is-zoomed'));
  document.body.append(dialog);
  return dialog;
}

function showLarge(button) {
  const dialog = lightbox();
  const picture = dialog.querySelector('img');
  picture.src = button.dataset.src;
  picture.alt = button.dataset.title;
  dialog.querySelector('p').textContent = button.dataset.title;
  dialog.querySelector('a').href = button.dataset.src;
  dialog.showModal();
}

async function submitJobs(refresh) {
  const garments = pickedGarments();
  const source = $('#studio-photo', node())?.value;
  if (!garments.length || !source) throw new Error('Select at least one garment and who to dress.');
  let person_photo_id = source;
  if (source === AVATAR_SOURCE) {
    if (!state.avatarSource?.photo && !$('#studio-avatar-consent', node())?.checked) throw new Error('Confirm the consent to use your avatar image.');
    person_photo_id = (state.avatarSource.photo || await request('/person-photos/from-avatar', {method: 'POST', body: {consent: true}})).id;
  }
  rememberPersonSource(source);
  state.tryOnIdempotencyKey ||= crypto.randomUUID();
  let queued = 0;
  let problem = '';
  for (const garment_id of garments) {
    try {
      await request('/try-on/jobs', {method: 'POST', body: {garment_id, person_photo_id}, key: `${state.tryOnIdempotencyKey}:${garment_id}`});
      queued += 1;
    } catch (error) {
      problem = error.message;
      break;
    }
  }
  if (!problem) state.tryOnIdempotencyKey = null;
  if (!queued) throw new Error(problem);
  const note = queued === garments.length ? '' : ` ${garments.length - queued} could not be added: ${esc(problem)}`;
  state.tryonNotice = `<div class="studio-tryon-notice" role="status"><span>${plural(queued, 'try-on')} added to the queue. Come back in ${waitText(queued)}: ${queued === 1 ? 'it' : 'they'} will be ready in Try-On History.${note}</span><a class="btn" href="#bo7-history">Open Try-On History</a></div>`;
  return refresh('bo7-tryon');
}

export async function handleTryonAction(action, button, refresh) {
  if (action === 'submit-mock') return submitJobs(refresh);
  if (action === 'zoom-image') return showLarge(button);
  if (action === 'try-garment') {
    state.tryonGarment = button.dataset.id;
    location.hash = '#bo7-tryon';
    return;
  }
  if (action === 'cancel-job') {
    await request('/try-on/jobs/' + button.dataset.id + '/cancel', {method: 'POST'});
    return refresh('bo7-history');
  }
  if (action === 'delete-photo') {
    if (!confirm('Delete this photo and every try-on made with it? Any queued or running job for it stops too.')) return;
    await request('/person-photos/' + button.dataset.id, {method: 'DELETE'});
    await refresh('bo7-tryon');
    message('Photo and its try-ons deleted.');
    return;
  }
  if (action === 'delete-job') {
    if (!confirm('Delete this job and its private result?')) return;
    await request('/try-on/jobs/' + button.dataset.id, {method: 'DELETE'});
    return refresh('bo7-history');
  }
}
