import {state, $, esc, request, message} from './core.js';

const IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp']);

export function uploadPicker({key, name, title, accept, note, required = true, image = false}) {
  return `<div class="studio-upload" data-upload-picker="${key}"><label class="studio-upload-zone"><input class="studio-upload-input" data-upload-key="${key}" type="file" name="${name}" accept="${accept}" ${required ? 'required' : ''}><span class="studio-upload-icon" aria-hidden="true">＋</span><strong>${title}</strong><span>Choose a file or drop it here</span><small>${note}</small></label><div class="studio-upload-status" data-upload-status="${key}" role="status" aria-live="polite"></div><div class="studio-file-preview" data-upload-preview="${key}" aria-live="polite"></div></div>`;
}

export async function abandonPending() {
  const old = state.pending?.id;
  state.pending = null;
  state.uploadKey = null;
  state.uploadGeneration += 1;
  if (!old || !state.user) return;
  try {
    await request('/garments/uploads/' + old, {method: 'DELETE'});
  } catch {
    message('The previous temporary upload could not be removed immediately. It will expire automatically.', true);
  }
}

function removePreview(key) {
  const url = state.previewUrls[key];
  if (url) URL.revokeObjectURL(url);
  delete state.previewUrls[key];
}

function withinLimit(key, file) {
  const limits = state.publicConfig?.upload_limits;
  if (!limits) throw new Error('Upload settings are unavailable. Reload Studio before choosing a file.');
  if (key === 'avatar-model') {
    const limit = limits.avatar_bytes;
    if (file.size > limit) throw new Error(`Choose a GLB no larger than ${Math.ceil(limit / 1024 / 1024)} MB.`);
    if (!file.name.toLowerCase().endsWith('.glb')) throw new Error('Choose an Avaturn .glb export.');
  } else {
    const limit = limits.image_bytes;
    if (file.size > limit) throw new Error(`Choose an image no larger than ${Math.ceil(limit / 1024 / 1024)} MB.`);
    if (!IMAGE_TYPES.has(file.type)) throw new Error('Choose a JPEG, PNG or WebP image.');
  }
}

function showFile(key, file, previewEnabled, picker = null) {
  const target = picker?.querySelector(`[data-upload-preview="${key}"]`) || $(`[data-upload-preview="${key}"]`);
  if (!target) return;
  target.replaceChildren();
  if (!file) return;
  const row = document.createElement('div');
  row.className = 'studio-file-row';
  if (previewEnabled && file.type.startsWith('image/')) {
    const preview = document.createElement('img');
    preview.className = 'studio-preview';
    preview.alt = 'Selected image preview';
    preview.src = URL.createObjectURL(file);
    state.previewUrls[key] = preview.src;
    row.append(preview);
  }
  const details = document.createElement('div');
  details.className = 'studio-file-details';
  const filename = document.createElement('strong');
  filename.textContent = file.name;
  const size = document.createElement('span');
  size.textContent = `${(file.size / 1024 / 1024).toFixed(2)} MB selected`;
  const clear = document.createElement('button');
  clear.type = 'button';
  clear.className = 'btn ghost';
  clear.dataset.action = 'clear-upload';
  clear.dataset.uploadKey = key;
  clear.textContent = 'Remove file';
  details.append(filename, size, clear);
  row.append(details);
  target.append(row);
}

export async function handleUploadSelection(input) {
  const key = input.dataset.uploadKey;
  const picker = input.closest('[data-upload-picker]');
  const status = picker?.querySelector('.studio-upload-status');
  if (key === 'garment' && state.pending) await abandonPending();
  if (key === 'garment') {
    state.uploadGeneration += 1;
    state.uploadKey = null;
    input.closest('.studio-review-shell')?.querySelector('#studio-review')?.replaceChildren();
  }
  removePreview(key);
  const file = input.files?.[0];
  showFile(key, null, false, picker);
  if (!file) return;
  try {
    withinLimit(key, file);
    showFile(key, file, key !== 'avatar-model', picker);
    if (status) status.textContent = 'File selected. Check the preview before continuing.';
  } catch (error) {
    input.value = '';
    if (status) status.textContent = error.message;
    message(error.message, true);
  }
}

export async function clearUpload(key) {
  const input = $(`[data-upload-key="${key}"]`);
  if (key === 'garment') {
    await abandonPending();
    input?.closest('.studio-review-shell')?.querySelector('#studio-review')?.replaceChildren();
  }
  if (input) input.value = '';
  removePreview(key);
  showFile(key, null, false, input?.closest('[data-upload-picker]'));
  const status = input?.closest('[data-upload-picker]')?.querySelector('.studio-upload-status');
  if (status) status.textContent = 'File removed.';
}

export async function handleDrop(event) {
  const zone = event.target.closest('.studio-upload-zone');
  if (!zone) return;
  event.preventDefault();
  zone.classList.remove('is-dragging');
  const input = zone.querySelector('input[type=file]');
  const file = event.dataTransfer?.files?.[0];
  if (!input || !file) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  input.files = transfer.files;
  await handleUploadSelection(input);
}

export function handleDragOver(event) {
  const zone = event.target.closest('.studio-upload-zone');
  if (!zone) return;
  event.preventDefault();
  zone.classList.add('is-dragging');
}

export function clearDrag(event) {
  event.target.closest('.studio-upload-zone')?.classList.remove('is-dragging');
}

export async function validateUpload(input) {
  const file = input.files?.[0];
  if (!file) throw new Error('Choose a file before continuing.');
  withinLimit(input.dataset.uploadKey, file);
  return file;
}
