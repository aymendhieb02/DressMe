import {state, $, esc, image, node, active, request, message} from './core.js';
import {uploadPicker, clearUpload} from './upload.js';

const CATEGORY = ['dress', 'jacket', 'jeans', 'shirt', 'shorts', 'skirt', 'sweater', 'sweatshirt', 't-shirt', 'top', 'trousers'];
const COLORS = ['beige', 'black', 'blue', 'brown', 'green', 'grey', 'navy', 'orange', 'pink', 'purple', 'red', 'white', 'yellow'];
const PATTERNS = ['solid', 'striped', 'checked', 'printed', 'floral'];
const SLEEVES = ['sleeveless', 'short', 'long'];
const BOTTOMS = new Set(['jeans', 'shorts', 'skirt', 'trousers']);

export function categories() { return CATEGORY; }

export function wardrobeContent() {
  const f = state.filters;
  return `<p class="studio-muted">Your photos and saved garment details are private. CSV export downloads your entire owned wardrobe, regardless of search or filters.</p><div class="studio-filter-grid"><label>Search descriptions<input id="studio-search" type="search" value="${esc(f.q)}" placeholder="Search your wardrobe"></label><label>Category<select id="studio-category"><option value="">All categories</option>${CATEGORY.map(value => `<option value="${value}" ${f.category === value ? 'selected' : ''}>${value}</option>`).join('')}</select></label><label>Color<select id="studio-color"><option value="">All colors</option>${COLORS.map(value => `<option value="${value}" ${f.color === value ? 'selected' : ''}>${value}</option>`).join('')}</select></label><label>Sort<select id="studio-sort"><option value="newest" ${f.sort === 'newest' ? 'selected' : ''}>Newest first</option><option value="oldest" ${f.sort === 'oldest' ? 'selected' : ''}>Oldest first</option></select></label></div><div class="studio-actions"><button class="btn" data-action="filter">Apply filters</button><button class="btn ghost" data-action="reset-filters">Clear filters</button><a class="btn ghost" href="/studio-api/garments/export.csv">Export full wardrobe · CSV</a><a class="btn" href="#bo6-add">Add garment</a></div><div id="studio-wardrobe-list" aria-live="polite"></div><div id="studio-detail"></div>`;
}

export function addGarmentContent() {
  const bytes = state.publicConfig?.upload_limits?.image_bytes;
  const size = bytes ? `${Math.ceil(bytes / 1024 / 1024)} MB` : 'checking server limit';
  return `<p class="studio-muted">Add a piece in five steps: upload → analyze → review → description → save. AI values are suggestions; nothing is confirmed until you select or change it.</p><ol class="studio-steps" aria-label="Garment steps"><li>Upload</li><li>Analyze</li><li>Review</li><li>Description</li><li>Save</li></ol><div class="studio-review-shell"><form id="studio-upload" class="studio-form"><h3>1. Choose a garment photo</h3>${uploadPicker({key: 'garment', name: 'image', title: 'Add one garment photo', accept: 'image/jpeg,image/png,image/webp', note: `JPEG, PNG or WebP · up to ${size}`, image: true})}<p class="studio-upload-status" data-upload-status="garment" role="status"></p><button class="btn" type="submit" ${bytes ? '' : 'disabled'}>2. Analyze photo</button><p class="studio-muted">Use one full, in-focus garment on a simple background. If analysis fails, try brighter, more evenly lit clothing with the full item in frame.</p></form><div id="studio-review"></div></div>`;
}

export async function renderWardrobe(page = 1, version = state.renderVersion) {
  if (active() !== 'bo6-wardrobe') return;
  const q = $('#studio-search', node())?.value ?? state.filters.q;
  const category = $('#studio-category', node())?.value ?? state.filters.category;
  const color = $('#studio-color', node())?.value ?? state.filters.color;
  const sort = $('#studio-sort', node())?.value ?? state.filters.sort;
  state.filters = {q, category, color, sort, page};
  const params = new URLSearchParams({page: String(page), page_size: '24', sort});
  if (q.trim()) params.set('q', q.trim());
  if (category) params.set('category', category);
  if (color) params.set('color', color);
  const result = await request('/garments?' + params);
  if (version !== state.renderVersion || active() !== 'bo6-wardrobe') return result;
  state.garments = result.items;
  const target = $('#studio-wardrobe-list', node());
  const filterLabels = [q && `Search: “${esc(q)}”`, category && `Category: ${esc(category)}`, color && `Color: ${esc(color)}`].filter(Boolean);
  const empty = result.total === 0;
  const emptyState = filterLabels.length
    ? `<section class="studio-empty"><h3>No matching garments</h3><p>Try a broader search or clear the active filters.</p><button class="btn ghost" data-action="reset-filters">Clear filters</button></section>`
    : `<section class="studio-empty"><h3>Your wardrobe is ready for its first piece</h3><p>Upload a garment photo and review the AI suggestions before saving.</p><a class="btn" href="#bo6-add">Add a garment</a></section>`;
  target.innerHTML = `<div class="studio-result-head"><p><strong>${result.total}</strong> ${result.total === 1 ? 'garment' : 'garments'}${filterLabels.length ? ' match your filters' : ' in your wardrobe'}</p>${filterLabels.length ? `<div class="studio-filter-chips" aria-label="Active filters">${filterLabels.map(label => `<span>${label}</span>`).join('')}<button class="studio-link" data-action="reset-filters">Clear all</button></div>` : ''}</div>${empty ? emptyState : `<div class="studio-grid">${result.items.map(g => `<article class="studio-card"><img src="${image(g.image_url)}" alt="${esc(g.name || g.category)}"><div class="studio-card-copy"><span class="studio-card-kicker">${esc(g.category)} · ${g.description_is_manual ? 'Edited description' : 'Automatic description'}</span><h3>${esc(g.name || g.category)}</h3><p>${esc(g.description)}</p><button class="btn ghost" data-action="detail" data-id="${g.id}">View details and edit</button></div></article>`).join('')}</div><div class="studio-pagination"><span>Page ${result.page} of ${Math.max(1, Math.ceil(result.total / result.page_size))}</span><div class="studio-actions">${page > 1 ? `<button class="btn ghost" data-action="page" data-page="${page - 1}">Previous</button>` : ''}${page * result.page_size < result.total ? `<button class="btn ghost" data-action="page" data-page="${page + 1}">Next</button>` : ''}</div></div>`}`;
  return result;
}

function optionList(values, selected, emptyLabel) {
  return `<option value="">${emptyLabel}</option>${values.map(value => `<option value="${value}" ${selected === value ? 'selected' : ''}>${value}</option>`).join('')}`;
}

export async function detail(id, version = state.renderVersion) {
  if (active() !== 'bo6-wardrobe') return;
  const g = await request('/garments/' + id);
  if (version !== state.renderVersion || active() !== 'bo6-wardrobe') return;
  state.selected = g;
  const descriptionSource = g.description_is_manual ? 'Manually edited by you' : 'Generated by DressMe from your confirmed fields';
  const sources = Object.entries(g.field_sources || {}).filter(([field]) => ['category', 'color', 'pattern', 'sleeve_length'].includes(field));
  const target = $('#studio-detail', node());
  target.innerHTML = `<section class="studio-detail-card" aria-labelledby="studio-detail-title"><div class="studio-detail-image"><img class="studio-preview" src="${image(g.image_url)}" alt="Private photo of ${esc(g.name || g.category)}"></div><div class="studio-detail-copy"><div class="studio-result-head"><div><p class="studio-eyebrow">Saved garment</p><h3 id="studio-detail-title">${esc(g.name || g.category)}</h3></div><span class="studio-badge ${g.description_is_manual ? 'is-manual' : 'is-auto'}">${g.description_is_manual ? 'Edited by you' : 'Automatic description'}</span></div><p><strong>Category:</strong> ${esc(g.category)} · <strong>Photo:</strong> ${esc(g.garment_photo_type)}</p><p><strong>Attributes:</strong> color ${esc(g.color || 'unknown')}, pattern ${esc(g.pattern || 'unknown')}, sleeve ${esc(g.sleeve_length || 'not estimated')}</p><p class="studio-muted">${descriptionSource}.</p>${sources.length ? `<details><summary>Suggestion and confirmation history</summary><ul>${sources.map(([field, source]) => `<li>${esc(field.replaceAll('_', ' '))}: ${esc(source)}</li>`).join('')}</ul></details>` : ''}<form id="studio-edit" class="studio-form"><input type="hidden" name="id" value="${g.id}"><div class="studio-fields"><label>Name<input name="name" value="${esc(g.name || '')}" maxlength="120"></label><label>Category<select name="category" required>${CATEGORY.map(value => `<option value="${value}" ${g.category === value ? 'selected' : ''}>${value}</option>`).join('')}</select></label><label>Photo type<select name="garment_photo_type">${['flat-lay', 'model'].map(value => `<option value="${value}" ${g.garment_photo_type === value ? 'selected' : ''}>${value === 'flat-lay' ? 'Flat lay' : 'Worn by model'}</option>`).join('')}</select></label><label>Color<select name="color">${optionList(COLORS, g.color, 'Unknown')}</select></label><label>Pattern<select name="pattern">${optionList(PATTERNS, g.pattern, 'Unknown')}</select></label><label>Sleeve length<select name="sleeve_length">${optionList(SLEEVES, g.sleeve_length, 'Not estimated')}</select></label></div><label>Description <span class="studio-muted">(${g.description_is_manual ? 'manual text; retained when attributes change' : 'regenerated from confirmed fields when attributes change'})</span><textarea name="description" maxlength="500" required>${esc(g.description)}</textarea></label><label>Notes<textarea name="notes" maxlength="2000">${esc(g.notes || '')}</textarea></label><div class="studio-actions"><button class="btn" type="submit">Save changes</button>${!g.description_is_manual ? '<button class="btn ghost" type="button" data-action="regenerate-detail">Regenerate description</button>' : ''}<button class="btn ghost" type="button" data-action="close-detail">Cancel</button><button class="btn danger" type="button" data-action="delete-garment" data-id="${g.id}">Delete garment</button></div><p class="studio-muted" data-edit-status role="status"></p></form></div></section>`;
  $('#studio-detail-title', target)?.setAttribute('tabindex', '-1');
  $('#studio-detail-title', target)?.focus();
  const sleeve = $('#studio-edit select[name=sleeve_length]', target);
  if (BOTTOMS.has(g.category)) { sleeve.disabled = true; sleeve.value = ''; }
}

export function review() {
  if (!state.pending) return;
  const prediction = state.pending.prediction || {};
  const categoriesSuggested = prediction.suggestions || [];
  const attributes = prediction.attributes || {};
  const target = $('#studio-review', node());
  target.innerHTML = `<section class="studio-review-layout"><div class="studio-review-photo-panel"><div class="studio-suggestions"><p class="studio-eyebrow">AI suggestions</p><h3>Review the details</h3><p>Suggestions are not confirmations. Select a value to fill its field, or make your own correction.</p><b>Category</b><div class="studio-chips">${categoriesSuggested.map(item => `<button type="button" class="studio-chip" aria-pressed="false" data-group="category" data-action="suggest-category" data-value="${esc(item.category)}">${esc(item.category)} · ${Number(item.score).toFixed(3)}</button>`).join('') || '<span>No category suggestion</span>'}</div><p class="studio-muted">Model scores are uncalibrated and are shown for review.</p>${Object.entries(attributes).map(([field, result]) => `<div class="studio-attribute"><b>${esc(field.replaceAll('_', ' '))}</b>${result.eligible ? `<div class="studio-chips">${(result.suggestions || []).map(item => `<button type="button" class="studio-chip" aria-pressed="false" data-group="${esc(field)}" data-action="suggest-attribute" data-field="${esc(field)}" data-value="${esc(item.value)}">${esc(item.value)}${Number.isFinite(item.score) ? ` · ${Number(item.score).toFixed(3)}` : ''}</button>`).join('') || '<span>No suggestion</span>'}</div>` : `<p>Not estimated: ${esc(result.reason || 'not applicable')}</p>`}</div>`).join('')}${state.pending.quality?.warnings?.map(w => `<p class="studio-photo-tip"><strong>Photo tip:</strong> ${esc(w.message)} ${esc(w.action)}</p>`).join('') || ''}</div></div><div class="studio-review-fields"><h3>Your confirmed values</h3><p class="studio-muted">Choose the required category and photo type. Optional attributes can stay unknown.</p><form id="studio-confirm" class="studio-form"><div class="studio-fields"><label>Category <span class="studio-required">Required</span><select name="category" required><option value="">Choose a category</option>${CATEGORY.map(value => `<option value="${value}">${value}</option>`).join('')}</select></label><label>Photo type <span class="studio-required">Required</span><select name="garment_photo_type" required><option value="">Choose photo type</option><option value="flat-lay">Flat lay</option><option value="model">Worn by model</option></select></label><label>Color <span class="studio-muted">Optional</span><select name="color">${optionList(COLORS, '', 'Unknown')}</select></label><label>Pattern <span class="studio-muted">Optional</span><select name="pattern">${optionList(PATTERNS, '', 'Unknown')}</select></label><label>Sleeve length <span class="studio-muted">Optional</span><select name="sleeve_length">${optionList(SLEEVES, '', 'Not estimated')}</select></label><label>Name <span class="studio-muted">Optional</span><input name="name" maxlength="120"></label></div><div class="studio-description-panel"><div class="studio-actions"><button class="btn ghost" type="button" data-action="describe">Generate description</button><span class="studio-muted" id="studio-description-state" aria-live="polite"></span></div><label>Description<textarea name="description" maxlength="500" placeholder="Choose required values, then generate or write your own description"></textarea></label></div><div class="studio-actions"><button class="btn" type="submit">Save garment</button><button class="btn ghost" type="button" data-action="discard-review">Discard review</button></div></form></div></section>`;
  syncSuggestionState($('#studio-confirm', target));
}

export function syncSuggestionState(form) {
  if (!form) return;
  const suggestionRoot = form.closest('#studio-review') || form.parentElement;
  for (const button of suggestionRoot.querySelectorAll('.studio-chip[data-group]')) {
    const control = form.elements[button.dataset.group];
    const selected = !!control && !control.disabled && control.value === button.dataset.value;
    button.disabled = !control || control.disabled;
    button.setAttribute('aria-pressed', String(selected));
    button.classList.toggle('is-selected', selected);
  }
}

export function chooseSuggestion(button) {
  const form = $('#studio-confirm', node());
  const field = button.dataset.action === 'suggest-category' ? 'category' : button.dataset.field;
  const select = form?.elements[field];
  const value = button.dataset.value;
  if (!select || !value) throw new Error('That suggestion is unavailable.');
  if (select.value !== value) {
    if (![...select.options].some(option => option.value === value)) select.add(new Option(value, value));
    select.value = value;
    select.dispatchEvent(new Event('change', {bubbles: true}));
  }
  syncSuggestionState(form);
}

export function handleConfirmedChange(event) {
  const form = event.target.closest('#studio-confirm');
  if (!form || !event.target.matches('select[name=category],select[name=color],select[name=pattern],select[name=sleeve_length]')) return;
  const textarea = form.elements.description;
  if (textarea.dataset.generated && textarea.value === textarea.dataset.generated) {
    textarea.dataset.stale = 'true';
    $('#studio-description-state', node()).textContent = 'Generated text is out of date. Regenerate before saving.';
    message('Confirmed values changed. The description will be regenerated when you save.');
  }
  const category = form.elements.category.value;
  if (BOTTOMS.has(category)) { form.elements.sleeve_length.value = ''; form.elements.sleeve_length.disabled = true; }
  else form.elements.sleeve_length.disabled = false;
  syncSuggestionState(form);
}

export async function generateDescription(version = state.renderVersion) {
  const form = $('#studio-confirm', node());
  const data = Object.fromEntries(new FormData(form));
  if (!data.category || !data.garment_photo_type) throw new Error('Confirm a category and photo type first.');
  const confirmed = {category: data.category};
  for (const field of ['color', 'pattern', 'sleeve_length']) if (data[field]) confirmed[field] = data[field];
  const described = await request('/garments/describe', {method: 'POST', body: {pending_upload_id: state.pending.id, confirmed}});
  if (version !== state.renderVersion || active() !== 'bo6-add') return;
  form.elements.description.value = described.text || described.description || '';
  form.elements.description.dataset.generated = form.elements.description.value;
  delete form.elements.description.dataset.stale;
  $('#studio-description-state', node()).textContent = 'Generated from your confirmed values. You can edit this text.';
  message('Automatic description generated.');
}

export async function saveReview(form) {
  const data = Object.fromEntries(new FormData(form));
  if (!data.category || !data.garment_photo_type) throw new Error('Choose a category and photo type before saving.');
  const body = {pending_upload_id: state.pending.id, category: data.category, garment_photo_type: data.garment_photo_type};
  for (const key of ['color', 'pattern', 'sleeve_length', 'name']) if (data[key]) body[key] = data[key];
  const description = form.elements.description;
  if (data.description?.trim() && description.dataset.generated !== data.description.trim()) body.description = data.description.trim();
  const garment = await request('/garments', {method: 'POST', body});
  state.pending = null;
  state.uploadKey = null;
  await clearUpload('garment');
  state.filters = {q: '', category: '', color: '', sort: 'newest', page: 1};
  if (active() === 'bo6-add') location.hash = 'bo6-wardrobe';
  message('Saved ' + garment.category + '.');
}

export async function saveEdit(form) {
  const data = Object.fromEntries(new FormData(form));
  const original = state.selected;
  const changes = {};
  for (const key of ['name', 'category', 'garment_photo_type', 'color', 'pattern', 'sleeve_length', 'notes']) {
    if ((data[key] || null) !== (original[key] || null)) changes[key] = data[key] || null;
  }
  if (data.description !== original.description) changes.description = data.description;
  if (!Object.keys(changes).length) { message('There are no changes to save.'); return; }
  const updated = await request('/garments/' + original.id, {method: 'PATCH', body: changes});
  if (active() !== 'bo6-wardrobe') return;
  state.selected = updated;
  await renderWardrobe(state.filters.page);
  $('#studio-detail', node()).replaceChildren();
  message('Garment updated.');
}

export async function regenerateDetailDescription() {
  if (!state.selected) return;
  const updated = await request(`/garments/${state.selected.id}/regenerate-description`, {method: 'POST'});
  state.selected = updated;
  await detail(updated.id);
  message('Description regenerated from the confirmed garment attributes.');
}
