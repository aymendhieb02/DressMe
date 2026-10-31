import {state, $, esc, active, image, node, request, message} from './core.js';
import {uploadPicker, validateUpload, clearUpload} from './upload.js';

export function tryonContent() {
  return `<p class="studio-badge">MOCK · no virtual try-on model runs in this application</p><p class="studio-muted">Save a person photo with consent, choose one of your eligible garments and submit only when the worker is ready.</p><section class="studio-panel"><h3>Save a person photo</h3><form id="studio-person" class="studio-form">${uploadPicker({key: 'person-photo', name: 'image', title: 'Choose one person photo', accept: 'image/jpeg,image/png,image/webp', note: 'JPEG, PNG or WebP · private storage'})}<label class="studio-consent"><input name="consent" type="checkbox" required> I consent to private processing of this photo for mock try-on.</label><button class="btn ghost" type="submit">Save consented photo</button></form></section><div id="studio-tryon-controls" class="studio-panel"></div>`;
}

export function historyContent() {
  return `<p class="studio-badge">MOCK history · previews are not generated clothing transfer</p><div id="studio-jobs" aria-live="polite"></div>`;
}

export async function refreshTryon(version = state.renderVersion) {
  let runtime;
  try {
    runtime = await request('/health/try-on');
  } catch {
    runtime = {available: false, reason: 'backend_unavailable'};
  }
  const [garments, photos] = await Promise.all([
    request('/garments?page_size=50'), request('/person-photos'),
  ]);
  if (version !== state.renderVersion || active() !== 'bo7-tryon') return;
  state.garments = garments.items;
  state.photos = photos;
  const eligible = state.garments.filter(garment => garment.vton_eligibility?.candidate_category);
  const target = $('#studio-tryon-controls', node());
  target.innerHTML = `<div class="studio-result-head"><div><p class="studio-eyebrow">Worker status</p><h3>Mock preview queue</h3></div><span class="studio-badge ${runtime.available ? 'is-ready' : 'is-unavailable'}">${runtime.available ? 'Ready' : 'Unavailable'}</span></div><p class="studio-muted">${runtime.available ? 'A worker is available. Submissions create MOCK jobs only.' : `Submission is disabled because the worker is unavailable (${esc(runtime.reason || 'unknown')}). Start Redis and the RQ worker, then reload this page.`}</p>${eligible.length && photos.length ? `<div class="studio-fields"><label>Eligible owned garment<select id="studio-garment"><option value="">Choose garment</option>${eligible.map(garment => `<option value="${garment.id}">${esc(garment.name || garment.category)}</option>`).join('')}</select></label><label>Consented person photo<select id="studio-photo"><option value="">Choose a saved photo</option>${photos.map(photo => `<option value="${photo.id}">${esc(new Date(photo.created_at).toLocaleDateString())}</option>`).join('')}</select></label></div><button class="btn" data-action="submit-mock" ${runtime.available ? 'disabled' : 'disabled'}>Submit MOCK job</button><p class="studio-muted">Choose both saved inputs to enable submission.</p>` : `<section class="studio-empty"><h3>${eligible.length ? 'Add a consented person photo' : 'Save an eligible garment first'}</h3><p>This workflow needs an owned candidate garment and a private person photo.</p><a class="btn ghost" href="${eligible.length ? '#bo7-tryon' : '#bo6-add'}">${eligible.length ? 'Choose a photo above' : 'Add garment'}</a></section>`}${photos.map(photo => `<img class="studio-person-thumb" src="${image(photo.image_url)}" alt="Your saved private person photo">`).join('')}`;
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

export async function updateSubmitAvailability() {
  const button = $('[data-action="submit-mock"]', node());
  if (!button) return;
  const garment = $('#studio-garment', node())?.value;
  const photo = $('#studio-photo', node())?.value;
  const runtime = await request('/health/try-on').catch(() => ({available: false}));
  button.disabled = !runtime.available || !garment || !photo;
  button.setAttribute('aria-disabled', String(button.disabled));
}

export async function refreshHistory(version = state.renderVersion) {
  const result = await request('/try-on/jobs');
  if (version !== state.renderVersion || active() !== 'bo7-history') return;
  state.jobs = result.items;
  const target = $('#studio-jobs', node());
  target.innerHTML = state.jobs.length
    ? `<div class="studio-grid">${state.jobs.map(job => `<article class="studio-card"><div class="studio-result-head"><h3>${esc(job.state)}</h3><span class="studio-badge">${esc(job.mode.toUpperCase())}</span></div><p>${esc(job.error_code || new Date(job.created_at).toLocaleString())}</p>${job.result_url ? `<img class="studio-preview" src="${image(job.result_url)}" alt="Private mock preview result">` : ''}<div class="studio-actions">${['queued', 'running'].includes(job.state) ? `<button class="btn ghost" data-action="cancel-job" data-id="${job.id}">Cancel</button>` : ''}<button class="btn ghost" data-action="delete-job" data-id="${job.id}">Delete</button></div></article>`).join('')}</div>`
    : `<section class="studio-empty"><h3>No try-on jobs yet</h3><p>Completed MOCK results will appear here after a worker processes a request.</p><a class="btn" href="#bo7-tryon">Prepare a mock preview</a></section>`;
}

export async function handleTryonAction(action, button, refresh) {
  if (action === 'submit-mock') {
    const garment_id = $('#studio-garment', node())?.value;
    const person_photo_id = $('#studio-photo', node())?.value;
    if (!garment_id || !person_photo_id) throw new Error('Select an eligible garment and a consented person photo.');
    state.tryOnIdempotencyKey ||= crypto.randomUUID();
    const job = await request('/try-on/jobs', {method: 'POST', body: {garment_id, person_photo_id}, key: state.tryOnIdempotencyKey});
    state.tryOnIdempotencyKey = null;
    message(`MOCK job ${job.state}. No virtual try-on model ran.`);
    return refresh('bo7-tryon');
  }
  if (action === 'cancel-job') {
    await request('/try-on/jobs/' + button.dataset.id + '/cancel', {method: 'POST'});
    return refresh('bo7-history');
  }
  if (action === 'delete-job') {
    if (!confirm('Delete this job and its private result?')) return;
    await request('/try-on/jobs/' + button.dataset.id, {method: 'DELETE'});
    return refresh('bo7-history');
  }
}
