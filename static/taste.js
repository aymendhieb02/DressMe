import {request, state, esc} from './studio/core.js?v=bo7ootd9';

const $ = selector => document.querySelector(selector);
const api = (path, body, method = 'POST') => request(path, {base: '/api', method, body});
const slots = {'': 'All', haut: 'Tops', bas: 'Bottoms', robe: 'Dresses', veste: 'Jackets',
  chaussures: 'Shoes', sac: 'Bags', montre: 'Watches', bijou: 'Jewellery', accessoire: 'Accessories'};
const genders = {all: 'Everyone', Women: 'Women', Men: 'Men'};
const tabs = {disc: 'Discover', you: 'For you', me: 'My taste'};
const taste = {gender: 'all', slot: '', tab: 'disc', same: true, current: [], reactions: null,
  mode: 'photos', files: [], urls: [], busy: false};
let loading;

async function ensureState() {
  if (!state.user) return false;
  if (taste.reactions) return true;
  if (!loading) loading = api('/reco/state', undefined, 'GET').then(data => {
    taste.reactions = data;
    taste.gender = data.gender;
    updateCounts();
    return true;
  }).finally(() => { loading = null; });
  return loading;
}

function error(target, reason) { target.innerHTML = `<div class="taste-error" role="alert">${esc(reason.message || reason)}</div>`; }
function loadingAt(target) { target.innerHTML = '<p class="taste-loading" role="status">Finding pieces…</p>'; }
function updateCounts() {
  $('#taste-count').textContent = (taste.reactions?.liked.length || 0) + (taste.reactions?.disliked.length || 0);
  $('#taste-likes-count').textContent = `${taste.reactions?.liked.length || 0} liked piece(s) available for analysis.`;
}
function pills(target, values, selected, attribute) {
  target.innerHTML = Object.entries(values).map(([key, label]) =>
    `<button class="cc ${key === selected ? 'on' : ''}" type="button" data-${attribute}="${esc(key)}">${esc(label)}</button>`).join('');
}
function controls() {
  pills($('#taste-gender'), genders, taste.gender, 'gender');
  pills($('#taste-tabs'), tabs, taste.tab, 'tab');
  pills($('#taste-slots'), slots, taste.slot, 'slot');
  $('#taste-slots').hidden = taste.tab === 'me';
}
function card(item, actions = true) {
  const reason = item.because ? `Close to what you liked: ${item.because.name}` : (item.reason || '');
  return `<article class="taste-card" data-item="${Number(item.id)}">
    <img loading="lazy" src="${esc(item.img)}" alt="${esc(item.name)}">
    <p><em>${esc(item.type)}</em><br>${esc(item.name)}<br><small>${esc(item.colour || '')}</small></p>
    ${reason ? `<div class="taste-because">${esc(reason)}</div>` : ''}
    ${actions ? '<div class="taste-actions"><button type="button" data-kind="like" aria-label="Like">♥</button><button type="button" data-kind="dislike" aria-label="Dislike">✕</button><button type="button" data-kind="save" aria-label="Save">★</button></div>' : ''}
  </article>`;
}
function grid(items, actions = true) { return `<div class="taste-grid">${items.map(item => card(item, actions)).join('')}</div>`; }
function bar(item, scale = 1) {
  const share = Number(item.share) || 0;
  return `<div class="taste-bar"><span>${esc(item.style)}</span><div><i style="width:${Math.max(2, Math.min(100, share / scale * 100))}%"></i></div><b>${Math.round(share * 100)}%</b></div>`;
}
function body() { return {gender: taste.gender, slot: taste.slot || null, n: 12, same: taste.same}; }

async function showTaste() {
  const out = $('#taste-output');
  loadingAt(out);
  try {
    if (!await ensureState()) return;
    controls();
    if (taste.tab === 'disc') {
      const result = await api('/reco/feed', body());
      taste.current = result.items;
      out.innerHTML = (result.items.length ? grid(result.items) : '<p class="sub">You have seen everything on this shelf. Try another filter or start over.</p>')
        + '<button class="btn ghost" id="taste-more" type="button">Show other pieces</button>';
    } else if (taste.tab === 'you') {
      const result = await api('/reco/foryou', body());
      taste.current = result.items;
      if (!result.ready) { out.innerHTML = `<p class="sub">Like ${result.need} more piece(s) in Discover to unlock recommendations.</p>`; return; }
      out.innerHTML = `<p class="sub">Your styles: ${result.styles.map(esc).join(' · ')} &nbsp; <label><input id="taste-same" type="checkbox" ${taste.same ? 'checked' : ''}> Stay in my styles</label></p>`
        + (result.items.length ? grid(result.items) : '<p class="sub">No more pieces on this shelf.</p>')
        + '<button class="btn ghost" id="taste-more" type="button">More recommendations</button>';
    } else {
      const result = await api('/reco/profile', body());
      taste.current = [];
      out.innerHTML = (result.ready
        ? '<h3>Styles in what you like</h3>' + result.styles.slice(0, 8).map(item => bar(item, result.styles[0].share || 1)).join('')
        : `<p class="sub">Like ${result.need} more piece(s) to reveal your taste profile.</p>`)
        + (taste.reactions.saved.length ? '<h3>Saved pieces</h3>' + grid(taste.reactions.saved.slice(-12).reverse(), false) : '')
        + '<p class="sub">Style scores are automatic estimates from the catalog.</p>';
    }
  } catch (reason) { error(out, reason); }
}

async function refreshReactions() {
  taste.reactions = await api('/reco/state', undefined, 'GET');
  updateCounts();
}
async function reactTo(itemId, kind, target) {
  if (taste.busy) return;
  taste.busy = true;
  const buttons = target.querySelectorAll('button');
  buttons.forEach(button => { button.disabled = true; });
  try {
    await api('/reco/reaction', {item_id: itemId, kind});
    await refreshReactions();
    target.remove();
    taste.current = taste.current.filter(item => item.id !== itemId);
    if (location.hash === '#reco' && taste.tab !== 'me' && taste.current.length < 4) await showTaste();
  } catch (reason) {
    error(location.hash === '#bubble' ? $('#taste-bubble-output') : $('#taste-output'), reason);
    buttons.forEach(button => { button.disabled = false; });
  } finally { taste.busy = false; }
}
async function showMore() {
  const out = $('#taste-output');
  try {
    if (taste.current.length) await api('/reco/seen', {item_ids: taste.current.map(item => item.id)});
    await showTaste();
  } catch (reason) { error(out, reason); }
}

$('#taste-gender').addEventListener('click', event => { const button = event.target.closest('[data-gender]'); if (button) { taste.gender = button.dataset.gender; showTaste(); } });
$('#taste-tabs').addEventListener('click', event => { const button = event.target.closest('[data-tab]'); if (button) { taste.tab = button.dataset.tab; showTaste(); } });
$('#taste-slots').addEventListener('click', event => { const button = event.target.closest('[data-slot]'); if (button) { taste.slot = button.dataset.slot; showTaste(); } });
$('#taste-output').addEventListener('click', event => { if (event.target.id === 'taste-more') showMore(); });
$('#taste-output').addEventListener('change', event => { if (event.target.id === 'taste-same') { taste.same = event.target.checked; showTaste(); } });
$('#taste-reset').addEventListener('click', async () => {
  const out = $('#taste-output');
  loadingAt(out);
  try { await api('/reco/state', undefined, 'DELETE'); await refreshReactions(); await showTaste(); }
  catch (reason) { error(out, reason); }
});
document.addEventListener('click', event => {
  const button = event.target.closest('.taste-actions [data-kind]');
  const target = button?.closest('[data-item]');
  if (target) reactTo(Number(target.dataset.item), button.dataset.kind, target);
});

function setStyleMode(mode) {
  taste.mode = mode;
  $('#taste-style-photos').hidden = mode !== 'photos';
  $('#taste-style-likes').hidden = mode !== 'likes';
  document.querySelectorAll('#taste-style-mode [data-mode]').forEach(button => button.classList.toggle('on', button.dataset.mode === mode));
  updateCounts();
}
$('#taste-style-mode').addEventListener('click', event => { const button = event.target.closest('[data-mode]'); if (button) setStyleMode(button.dataset.mode); });
$('#taste-photos').addEventListener('change', event => {
  taste.urls.forEach(url => URL.revokeObjectURL(url));
  taste.files = [...event.target.files];
  const out = $('#taste-style-output');
  out.innerHTML = '';
  if (taste.files.length > 12 || taste.files.some(file => file.size > 8_000_000 || !['image/jpeg', 'image/png', 'image/webp'].includes(file.type))) {
    taste.files = []; error(out, 'Choose up to 12 JPG, PNG or WEBP images, each under 8 MB.');
  }
  taste.urls = taste.files.map(file => URL.createObjectURL(file));
  $('#taste-previews').innerHTML = taste.urls.map(url => `<img src="${esc(url)}" alt="Selected garment preview">`).join('');
  $('#taste-photo-name').textContent = taste.files.length ? `${taste.files.length} photo(s) selected` : 'Up to 12 JPG, PNG or WEBP images, 8 MB each';
});
function percent(value) { return `${Math.round(Number(value) * 100)}%`; }
function showStyleResult(result, previews = []) {
  const out = $('#taste-style-output');
  out.innerHTML = `<div class="res"><div><span class="pill" style="background:var(--c2)">${esc(result.dominant)}</span> <b style="font:400 2rem Fraunces,serif">${percent(result.dominant_share)}</b><p class="sub">Dominant style across ${result.items.length} piece(s).</p></div><div style="flex:1;min-width:240px">${result.profile.map(item => bar(item)).join('')}</div></div>
    <h3>What the model saw</h3><div class="taste-grid">${result.items.map((item, index) => `<article class="taste-card"><img src="${esc(item.img || previews[index] || '')}" alt="${esc(item.label)}"><p><em>${esc(item.type)}</em> · ${percent(item.type_conf)}<br>${esc(item.style)} · ${percent(item.style_conf)}</p></article>`).join('')}</div>
    <h3>Pieces in your style</h3>${result.recs.length ? grid(result.recs, false) : '<p class="sub">No matching catalog pieces found.</p>'}
    <p class="sub">The model estimates Casual, Sporty, Formal and Ethnic from product photos. Personal photos may be less accurate.</p>`;
}
async function analyzeStyle(mode) {
  const out = $('#taste-style-output');
  if (mode === 'photos' && !taste.files.length) { error(out, 'Choose at least one garment photo first.'); return; }
  loadingAt(out);
  try {
    await ensureState();
    let result;
    if (mode === 'photos') {
      const data = new FormData();
      taste.files.forEach(file => data.append('files', file));
      data.append('gender', taste.gender);
      result = await api('/style/photos', data);
    } else if (mode === 'likes') result = await api('/style/likes', {gender: taste.gender});
    else result = await api('/style/sample', {gender: taste.gender});
    showStyleResult(result, mode === 'photos' ? taste.urls : []);
  } catch (reason) { error(out, reason); }
}
$('#taste-analyze').addEventListener('click', () => analyzeStyle('photos'));
$('#taste-analyze-likes').addEventListener('click', () => analyzeStyle('likes'));
$('#taste-sample').addEventListener('click', () => analyzeStyle('sample'));

function surpriseHelp() {
  const value = Number($('#taste-surprise').value);
  $('#taste-surprise-value').textContent = `${value}%`;
  $('#taste-surprise-help').textContent = value < 20 ? 'Mostly familiar matches from your likes.'
    : value < 55 ? 'A balanced mix of familiar and less explored styles.'
    : value < 85 ? 'More room for styles you rarely like.' : 'Strongly favors styles outside your usual picks.';
}
$('#taste-surprise').addEventListener('input', surpriseHelp);
$('#taste-bubble-go').addEventListener('click', async () => {
  const out = $('#taste-bubble-output');
  loadingAt(out);
  try {
    await ensureState();
    const result = await api('/bubble/recommendations', {gender: taste.gender, alpha: Number($('#taste-surprise').value) / 100, n: 12});
    out.innerHTML = result.ready ? (result.items.length ? grid(result.items) : '<p class="sub">No more pieces to suggest. Try Taste Studio again.</p>')
      : `<p class="sub">Like ${result.need} more piece(s) in Taste Studio to unlock Bubble Breaker.</p>`;
  } catch (reason) { error(out, reason); }
});

document.addEventListener('dressme:section', event => {
  if (!['reco', 'style', 'bubble'].includes(event.detail)) return;
  ensureState().then(() => {
    if (event.detail === 'reco') showTaste();
    else if (event.detail === 'style') setStyleMode(taste.mode);
  }).catch(reason => error($('#' + (event.detail === 'style' ? 'taste-style-output' : event.detail === 'bubble' ? 'taste-bubble-output' : 'taste-output')), reason));
});
document.addEventListener('dressme:authenticated', () => {
  const page = location.hash.slice(1);
  if (page === 'reco') showTaste();
  if (page === 'style') ensureState().then(() => setStyleMode(taste.mode));
});
