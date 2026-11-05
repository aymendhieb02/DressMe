import {state, $, esc, image, node, active, request, message} from './core.js?v=bo7pose2';
import {uploadPicker, validateUpload, clearUpload} from './upload.js?v=bo7pose2';
import {captureAvatarRender} from './avatar-render.js?v=bo7pose2';

// Images made with an older profile are replaced when the page opens. Matches PROFILE_VERSION on the server.
const AVATAR_IMAGE_VERSION = 2;

export function avatarContent() {
  const bytes = state.publicConfig?.upload_limits?.avatar_bytes;
  const size = bytes ? `${Math.ceil(bytes / 1024 / 1024)} MB` : 'checking server limit';
  return `<p class="studio-muted">Create your 3D avatar with Avaturn. DressMe then makes a 2D image of it that you can use for virtual try-on.</p><div id="studio-provider" class="studio-panel"></div><div id="studio-avatar"></div><details class="studio-more" id="studio-avatar-import-panel"><summary>Already have an Avaturn GLB? Import it instead</summary><form id="studio-avatar-import" class="studio-form"><label class="studio-consent"><input type="checkbox" name="consent" required> I consent to Avaturn processing and private storage of this export.</label><label>Avaturn avatar ID<input name="provider_avatar_id" required maxlength="128" autocomplete="off"></label>${uploadPicker({key: 'avatar-model', name: 'model', title: 'Choose an Avaturn GLB', accept: '.glb,model/gltf-binary', note: `GLB export · up to ${size}`})}<button class="btn" type="submit" ${bytes ? '' : 'disabled'}>Save private avatar</button></form></details>`;
}

export function closeAvatarSdk() {
  state.avatarSdk?.destroy();
  state.avatarSdk = null;
  if (state.avatarGate) window.removeEventListener('message', state.avatarGate, true);
  state.avatarGate = null;
  if (state.previewUrls.avatarModel) URL.revokeObjectURL(state.previewUrls.avatarModel);
  delete state.previewUrls.avatarModel;
}

async function fetchAvatarExport(result) {
  const max = state.publicConfig?.upload_limits?.avatar_bytes || 50 * 1024 * 1024;
  const source = result.url;
  if (typeof source !== 'string' || !source) throw new Error('Avaturn returned no export URL.');
  let url;
  if (result.urlType === 'dataURL') {
    if (!source.startsWith('data:') || source.length > Math.ceil(max * 4 / 3) + 1024) throw new Error('Avaturn export exceeds the configured file limit.');
    url = source;
  } else if (result.urlType === 'httpURL') {
    const parsed = new URL(source);
    if (parsed.protocol !== 'https:' || parsed.username || parsed.password || !state.avatarConfig.export_origins.includes(parsed.origin)) throw new Error('Avaturn export origin is not configured.');
    url = parsed.href;
  } else throw new Error('Avaturn returned an unsupported export type.');
  const response = await fetch(url, {credentials: 'omit', redirect: 'error', mode: result.urlType === 'dataURL' ? 'same-origin' : 'cors'});
  if (!response.ok) throw new Error('Avaturn export download failed.');
  const type = response.headers.get('content-type')?.split(';')[0].trim().toLowerCase();
  if (type && !['model/gltf-binary', 'application/octet-stream'].includes(type)) throw new Error('Avaturn export is not a GLB.');
  if (Number(response.headers.get('content-length') || 0) > max) throw new Error('Avaturn export exceeds the configured file limit.');
  const reader = response.body?.getReader();
  if (!reader) throw new Error('Avaturn export stream is unavailable.');
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > max) { await reader.cancel(); throw new Error('Avaturn export exceeds the configured file limit.'); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  return new File(chunks, 'avaturn-avatar.glb', {type: 'model/gltf-binary'});
}

export async function refreshAvatar(version = state.renderVersion) {
  let providerConfig = {};
  try {
    const response = await fetch('/api/studio-config', {credentials: 'same-origin'});
    if (!response.ok) throw new Error();
    providerConfig = await response.json();
  } catch {
    message('Avatar provider settings are unavailable. You can still import a GLB file below.', true);
  }
  state.avatarConfig = providerConfig;
  const [avatar, savedRender] = await Promise.all([
    request('/avatars/current'), request('/avatars/current/render'),
  ]);
  if (version !== state.renderVersion || active() !== 'bo7-avatar') return;
  const provider = $('#studio-provider', node());
  provider.innerHTML = providerConfig.avaturn_url
    ? `<p class="studio-eyebrow">Avaturn creator</p><h3>${avatar ? 'Create a new avatar' : 'Create your avatar'}</h3><label class="studio-consent"><input type="checkbox" id="studio-provider-consent"> I consent to Avaturn photo processing to initialize and customize my avatar.</label><div class="studio-actions"><button class="btn studio-primary-action" data-action="open-creator">Open creator</button><button class="btn ghost" data-action="close-creator" hidden>Close creator</button></div><div id="studio-creator"></div>`
    : `<p class="studio-eyebrow">Provider unavailable</p><p>Avaturn is not configured for this origin. Add an approved HTTPS creator URL to the private application configuration.</p>`;
  if (!providerConfig.avaturn_url) $('#studio-avatar-import-panel', node())?.setAttribute('open', '');
  const target = $('#studio-avatar', node());
  target.innerHTML = avatar
    ? `<section class="studio-panel"><div class="studio-result-head"><div><p class="studio-eyebrow">Saved privately</p><h3>Your avatar · version ${avatar.version}</h3></div><button class="btn danger" data-action="delete-avatar">Delete avatar</button></div><div id="studio-model"></div><a class="btn ghost" href="${image(avatar.model_url)}">Download private GLB</a><div class="studio-panel" id="studio-render"></div></section>`
    : `<section class="studio-empty"><h3>No avatar saved yet</h3><p>Open the creator above. Once you export your avatar, it is saved here with a 2D image for try-on.</p></section>`;
  if (!avatar) return;
  if (savedRender) showAvatarImage(savedRender);
  let model;
  try {
    await import('/static/vendor/model-viewer.min.js');
    const response = await fetch(image(avatar.model_url), {credentials: 'same-origin'});
    if (!response.ok) throw new Error('Private model unavailable');
    model = await response.blob();
    if (state.previewUrls.avatarModel) URL.revokeObjectURL(state.previewUrls.avatarModel);
    state.previewUrls.avatarModel = URL.createObjectURL(model);
    const viewer = document.createElement('model-viewer');
    viewer.className = 'studio-model-viewer';
    viewer.setAttribute('alt', 'Your saved 3D avatar');
    viewer.setAttribute('camera-controls', '');
    viewer.setAttribute('auto-rotate', '');
    viewer.src = state.previewUrls.avatarModel;
    $('#studio-model', node()).append(viewer);
  } catch {
    message('The 3D viewer could not load. Your private GLB is still available for download.', true);
  }
  const recreate = state.recreateAvatarImage;
  state.recreateAvatarImage = false;
  const outdated = savedRender && savedRender.profile_version < AVATAR_IMAGE_VERSION;
  if (model && (!savedRender || outdated || recreate)) await createAvatarImage(avatar, model, version);
}

function showAvatarImage(render) {
  const slot = $('#studio-render', node());
  if (!slot) return;
  slot.innerHTML = `<div class="studio-result-head"><h4>Your 2D image</h4><a class="btn ghost" href="#bo7-tryon">Use for try-on</a></div><img class="studio-avatar-render" src="${image(render.image_url)}" alt="2D image of your avatar"><button class="studio-link" data-action="recreate-avatar-image">Recreate image</button>`;
}

async function createAvatarImage(avatar, model, version) {
  const slot = $('#studio-render', node());
  if (slot) slot.innerHTML = '<p class="studio-muted" role="status">Creating your 2D image…</p>';
  try {
    const {image: png, cameraSettings} = await captureAvatarRender(model);
    const form = new FormData();
    form.set('image', png, 'avatar-render.png');
    form.set('source_avatar_id', avatar.id);
    form.set('source_avatar_version', String(avatar.version));
    form.set('source_avatar_sha256', avatar.asset_sha256);
    form.set('camera_settings_json', JSON.stringify(cameraSettings));
    const saved = await request('/avatars/current/render', {method: 'PUT', body: form});
    if (version !== state.renderVersion || active() !== 'bo7-avatar') return;
    showAvatarImage(saved);
    message('Your 2D image is ready for try-on.');
  } catch (error) {
    if (version !== state.renderVersion || active() !== 'bo7-avatar') return;
    const failed = $('#studio-render', node());
    if (failed) failed.innerHTML = `<p class="studio-muted" role="alert">${esc(error.message || 'The 2D image could not be created.')}</p><button class="btn ghost" data-action="recreate-avatar-image">Try again</button>`;
  }
}

export async function openCreator(safe, refresh) {
  if (!state.avatarConfig?.avaturn_url) throw new Error('Avaturn creator is not configured.');
  if (!$('#studio-provider-consent', node())?.checked) throw new Error('Accept the Avaturn photo-processing disclosure first.');
  state.avatarConsent = await request('/avatars/consents', {method: 'POST', body: {accepted: true}});
  const {AvaturnSDK} = await import('/static/vendor/avaturn-sdk.js');
  closeAvatarSdk();
  const sdk = new AvaturnSDK();
  state.avatarSdk = sdk;
  const expectedOrigin = new URL(state.avatarConfig.avaturn_url).origin;
  state.avatarGate = event => {
    if (event.data?.source !== 'v1.avaturn-sdk-server') return;
    const frame = $('#studio-creator iframe', node());
    if (event.origin !== expectedOrigin || event.source !== frame?.contentWindow) event.stopImmediatePropagation();
  };
  window.addEventListener('message', state.avatarGate, true);
  sdk.on('error', issue => message(issue.message || 'Avaturn could not continue.', true));
  sdk.on('export', result => safe(async () => {
    if (state.avatarSdk !== sdk || active() !== 'bo7-avatar' || !result.avatarId) throw new Error('Avaturn export is no longer active.');
    message('Downloading the Avaturn GLB…');
    const file = await fetchAvatarExport(result);
    const form = new FormData();
    form.set('model', file);
    form.set('provider_avatar_id', result.avatarId);
    form.set('consent_id', state.avatarConsent.id);
    form.set('consent_version', state.avatarConsent.consent_version);
    await request('/avatars/current', {method: 'PUT', body: form});
    closeAvatarSdk();
    await refresh('bo7-avatar');
    message('Avaturn avatar saved privately.');
  }));
  try {
    await sdk.init($('#studio-creator', node()), {url: state.avatarConfig.avaturn_url, iframeClassName: 'studio-avaturn-frame'});
  } catch (error) { closeAvatarSdk(); throw error; }
  const frame = $('#studio-creator iframe', node());
  if (frame) frame.title = 'Avaturn 3D avatar creator';
  $('[data-action="close-creator"]', node())?.removeAttribute('hidden');
  message('Avaturn creator loaded. Complete the provider flow and export to save.');
}

export async function saveAvatarImport(form, refresh) {
  const input = form.elements.model;
  await validateUpload(input);
  const consent = await request('/avatars/consents', {method: 'POST', body: {accepted: true}});
  const data = new FormData(form);
  data.delete('consent');
  data.set('consent_id', consent.id);
  data.set('consent_version', consent.consent_version);
  await request('/avatars/current', {method: 'PUT', body: data});
  form.reset();
  await clearUpload('avatar-model');
  await refresh('bo7-avatar');
  message('Private Avaturn export saved.');
}

export async function handleAvatarAction(action, button, context) {
  if (action === 'delete-avatar') {
    if (!confirm('Delete the saved avatar and its private file?')) return;
    await request('/avatars/current', {method: 'DELETE'});
    await context.refresh('bo7-avatar');
    return;
  }
  if (action === 'open-creator') return openCreator(context.safe, context.refresh);
  if (action === 'recreate-avatar-image') {
    state.recreateAvatarImage = true;
    return context.refresh('bo7-avatar');
  }
  if (action === 'close-creator') {
    closeAvatarSdk();
    $('#studio-creator', node())?.replaceChildren();
    button.setAttribute('hidden', '');
    message('Avaturn creator closed.');
  }
}
