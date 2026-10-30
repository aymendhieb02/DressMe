/* Private BO6/BO7 pages. The five original sections and their handlers remain in index.html. */
const PAGES = [
  ['bo6-wardrobe','My Wardrobe'], ['bo6-add','Add Garment'],
  ['bo7-avatar','My Avatar'], ['bo7-tryon','Virtual Try-On'], ['bo7-history','Try-On History']
];
const ROOT = '/studio-api';
const state = {user:null, csrf:null, pending:null, uploadKey:null, previewUrl:null, modelUrl:null, garments:[], photos:[], jobs:[], selected:null, busy:false, avatarConfig:null, avatarSdk:null, avatarGate:null, avatarConsent:null};
const $ = (selector, root=document) => root.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const image = url => ROOT + url;
const active = () => location.hash.slice(1);
const node = () => document.querySelector(`[data-studio-page="${active()}"]`);
const message = (text, error=false) => { const target=$('.studio-status',node()); if(target){target.textContent=text; target.setAttribute('role',error?'alert':'status')} };
async function request(path, {method='GET', body, key, retry=true}={}) {
  const headers = {}; if(body && !(body instanceof FormData)) headers['Content-Type']='application/json';
  if(key) headers['Idempotency-Key']=key;
  if(!['GET','HEAD'].includes(method) && state.csrf) headers['X-CSRF-Token']=state.csrf;
  let response;
  try { response=await fetch(ROOT+path,{method,headers,body:body instanceof FormData?body:body===undefined?undefined:JSON.stringify(body),credentials:'same-origin'}); }
  catch { throw new Error('The application server is unavailable. Please try again later.') }
  if(response.status===403 && retry && state.user) {
    const detail=await response.clone().json().catch(()=>({}));
    if(detail.error?.code==='csrf_failed') { await csrf(); return request(path,{method,body,key,retry:false}) }
  }
  if(response.status===401) { state.user=null;state.csrf=null;state.pending=null;state.garments=[];state.photos=[];state.jobs=[];render();throw new Error('Session expired. Please sign in again.') }
  if(!response.ok) { const detail=await response.json().catch(()=>({}));throw new Error(detail.error?.message||detail.detail?.message||String(detail.detail||`Request failed (${response.status})`)) }
  return response.status===204?null:response.json();
}
async function csrf(){
  const response=await fetch(ROOT+'/auth/csrf',{method:'POST',headers:{'X-CSRF-Bootstrap':'1'},credentials:'same-origin'});
  if(!response.ok) throw new Error('Your session could not be verified. Please sign in again.');
  state.csrf=(await response.json()).csrf_token;
}
async function loadSession(){try{state.user=await request('/auth/me');await csrf()}catch{state.user=null;state.csrf=null} render()}
function shell(page){
  return `<div class="studio"><nav class="studio-nav" aria-label="My Studio">${PAGES.map(([id,title])=>`<a href="#${id}" ${id===page?'aria-current="page"':''}>${title}</a>`).join('')}<a href="#ootd">Style Engine</a></nav><div class="studio-body"><div class="studio-head"><h2>${esc(PAGES.find(p=>p[0]===page)?.[1])}</h2>${state.user?`<button class="btn ghost" data-action="logout">Sign out</button>`:''}</div><div class="studio-status" role="status" aria-live="polite"></div>${state.user?content(page):authForm()}</div></div>`;
}
function authForm(){return `<p class="studio-muted">Sign in to manage private garments, photos, avatars and try-on jobs. The original Style Engine and Shopping pages remain public.</p><form class="studio-form" id="studio-auth"><div class="studio-fields"><label>Email<input name="email" type="email" autocomplete="email" required></label><label>Password<input name="password" type="password" minlength="12" autocomplete="current-password" required></label></div><div class="studio-actions"><button class="btn" name="mode" value="login">Sign in</button><button class="btn ghost" name="mode" value="register">Create account</button></div></form>`}
function content(page){
 if(page==='bo6-wardrobe') return `<p class="studio-muted">Your saved garments are private. CSV export includes your full wardrobe, regardless of filters.</p><div class="studio-fields"><label>Search descriptions<input id="studio-search" type="search"></label><label>Category<select id="studio-category"><option value="">All categories</option>${categories().map(c=>`<option>${c}</option>`).join('')}</select></label><label>Color<select id="studio-color"><option value="">All colors</option>${['beige','black','blue','brown','green','grey','navy','orange','pink','purple','red','white','yellow'].map(c=>`<option>${c}</option>`).join('')}</select></label><label>Sort<select id="studio-sort"><option value="newest">Newest</option><option value="oldest">Oldest</option></select></label></div><div class="studio-actions"><button class="btn" data-action="filter">Apply</button><button class="btn ghost" data-action="reset">Reset</button><a class="btn ghost" href="${ROOT}/garments/export.csv">Export all owned garments · CSV</a><a class="btn" href="#bo6-add">Add garment</a></div><div id="studio-wardrobe-list"></div><div id="studio-detail"></div>`;
 if(page==='bo6-add') return `<p class="studio-muted">Upload → analyze → confirm → describe → save. Suggestions remain separate from your confirmed values.</p><form id="studio-upload" class="studio-form"><label>Garment photo (JPEG, PNG or WebP, up to 10 MB)<input type="file" name="image" accept="image/jpeg,image/png,image/webp" required></label><div id="studio-preview"></div><button class="btn">Analyze photo</button></form><div id="studio-review"></div>`;
 if(page==='bo7-avatar') return `<p class="studio-muted">Avatar creation uses Avaturn. Automatic photo initialization and in-page customization need a provider session approved for this origin; they are not verified here. You can save an existing Avaturn GLB export privately.</p><div id="studio-provider"></div><h3>Import an existing Avaturn export</h3><form id="studio-avatar-import" class="studio-form"><label><input type="checkbox" name="consent" required style="width:auto"> I consent to Avaturn photo processing and private storage of this export.</label><label>Avaturn avatar ID<input name="provider_avatar_id" required maxlength="128"></label><label>Avaturn GLB export<input name="model" type="file" accept=".glb,model/gltf-binary" required></label><button class="btn">Save Avaturn export</button></form><div id="studio-avatar"></div>`;
 if(page==='bo7-tryon') return `<p class="studio-badge">MOCK · no try-on model runs in this application</p><p class="studio-muted">Choose one owned garment and a consented person photo. Real web inference is unavailable.</p><form id="studio-person" class="studio-form"><label>Person photo<input name="image" type="file" accept="image/jpeg,image/png,image/webp" required></label><label><input name="consent" type="checkbox" required style="width:auto"> I consent to private processing of this photo for try-on.</label><button class="btn ghost">Save person photo</button></form><div id="studio-tryon-controls"></div>`;
 return `<p class="studio-badge">MOCK history · previews are not generated clothing transfer</p><div id="studio-jobs"></div>`;
}
function categories(){return ['dress','jacket','jeans','shirt','shorts','skirt','sweater','sweatshirt','t-shirt','top','trousers']}
function closeAvatarSdk(){state.avatarSdk?.destroy();state.avatarSdk=null;if(state.avatarGate)window.removeEventListener('message',state.avatarGate,true);state.avatarGate=null}
function render(){closeAvatarSdk();if(state.previewUrl){URL.revokeObjectURL(state.previewUrl);state.previewUrl=null}if(state.modelUrl){URL.revokeObjectURL(state.modelUrl);state.modelUrl=null}const el=node();if(!el)return;document.querySelectorAll('[data-studio-page]').forEach(other=>{if(other!==el)other.replaceChildren()});el.innerHTML=shell(active());if(state.user) refresh(active()).catch(e=>message(e.message,true))}
async function refresh(page){
 if(page==='bo6-wardrobe') return wardrobe();
 if(page==='bo7-avatar') {state.avatarConfig=await fetch('/api/studio-config').then(r=>r.json());const avatar=await request('/avatars/current');const savedRender=await request('/avatars/current/render');$('#studio-provider',node()).innerHTML=state.avatarConfig.avaturn_url?`<h3>Avaturn creator</h3><label><input type="checkbox" id="studio-provider-consent" style="width:auto"> I consent to Avaturn photo processing to initialize and customize an avatar.</label><div class="studio-actions"><button class="btn" data-action="open-creator">Open Avaturn creator</button><button class="btn ghost" data-action="close-creator">Close creator</button></div><div id="studio-creator"></div>`:'<p class="studio-muted">Avaturn creator is not configured for this origin. Set AVATURN_URL to an approved HTTPS .avaturn.dev creator URL before using photo initialization.</p>';$('#studio-avatar',node()).innerHTML=avatar?`<p>Saved Avaturn avatar, version ${avatar.version}.</p><div id="studio-model"></div><a class="btn ghost" href="${image(avatar.model_url)}">Download private GLB</a>${savedRender?`<h3>Saved render</h3><img class="studio-preview" src="${image(savedRender.image_url)}" alt="Saved avatar render">`:''}<div class="studio-actions"><button class="btn ghost" data-action="delete-avatar">Delete avatar</button></div>`:'<p>No saved avatar. Provider creation and export have not been verified for this origin.</p>';if(avatar){try{await import('/static/vendor/model-viewer.min.js');const response=await fetch(image(avatar.model_url),{credentials:'same-origin'});if(!response.ok)throw Error('Private model unavailable');const blob=await response.blob();if(state.modelUrl)URL.revokeObjectURL(state.modelUrl);state.modelUrl=URL.createObjectURL(blob);const viewer=document.createElement('model-viewer');viewer.className='studio-model-viewer';viewer.setAttribute('alt','Your saved 3D avatar');viewer.setAttribute('camera-controls','');viewer.setAttribute('auto-rotate','');viewer.src=state.modelUrl;$('#studio-model',node()).append(viewer)}catch{message('The 3D viewer could not load; your private GLB is still available for download.',true)}}return }
 if(page==='bo7-tryon') {const runtime=await request('/health/try-on');state.garments=(await request('/garments?page_size=50')).items;state.photos=await request('/person-photos');const target=$('#studio-tryon-controls',node());target.innerHTML=`<h3>Submit a mock preview</h3><p class="studio-muted">Mock queue: ${runtime.available?'available':'unavailable ('+esc(runtime.reason)+')'}.</p><div class="studio-fields"><label>Owned garment<select id="studio-garment"><option value="">Choose garment</option>${state.garments.filter(g=>g.vton_eligibility?.candidate_category).map(g=>`<option value="${g.id}">${esc(g.name||g.category)}</option>`).join('')}</select></label><label>Consented person photo<select id="studio-photo"><option value="">Choose photo</option>${state.photos.map(p=>`<option value="${p.id}">${esc(p.created_at)}</option>`).join('')}</select></label></div><div class="studio-actions"><button class="btn" data-action="submit-mock" ${runtime.available?'':'disabled'}>Submit MOCK job</button></div>${state.photos.map(p=>`<img class="studio-preview" src="${image(p.image_url)}" alt="Your saved person photo">`).join('')}`;return }
 if(page==='bo7-history') {state.jobs=(await request('/try-on/jobs')).items;$('#studio-jobs',node()).innerHTML=state.jobs.length?state.jobs.map(j=>`<article class="studio-card"><b>${esc(j.state)}</b> · ${esc(j.mode).toUpperCase()}<p>${esc(j.error_code||j.created_at)}</p>${j.result_url?`<img src="${image(j.result_url)}" alt="Mock preview result">`:''}<div class="studio-actions">${['queued','running'].includes(j.state)?`<button class="btn ghost" data-action="cancel-job" data-id="${j.id}">Cancel</button>`:''}<button class="btn ghost" data-action="delete-job" data-id="${j.id}">Delete</button></div></article>`).join(''):'<p>No try-on jobs yet.</p>';return }
}
async function wardrobe(page=1){const q=$('#studio-search',node())?.value||'',category=$('#studio-category',node())?.value||'',color=$('#studio-color',node())?.value||'',sort=$('#studio-sort',node())?.value||'newest';const params=new URLSearchParams({page:String(page),page_size:'24',sort});if(q)params.set('q',q);if(category)params.set('category',category);if(color)params.set('color',color);const result=await request('/garments?'+params);state.garments=result.items;$('#studio-wardrobe-list',node()).innerHTML=`<p>${result.total} garment${result.total===1?'':'s'}</p><div class="studio-grid">${result.items.map(g=>`<article class="studio-card"><img src="${image(g.image_url)}" alt="${esc(g.category)}"><h3>${esc(g.name||g.category)}</h3><p>${esc(g.description)}</p><button class="btn ghost" data-action="detail" data-id="${g.id}">View and edit</button></article>`).join('')}</div>${result.total===0?'<p>No matching garments. Try Reset or Add garment.</p>':''}<div class="studio-actions">${page>1?`<button class="btn ghost" data-action="page" data-page="${page-1}">Previous</button>`:''}${page*24<result.total?`<button class="btn ghost" data-action="page" data-page="${page+1}">Next</button>`:''}</div>`}
function review(){const p=state.pending,pred=p.prediction||{},sug=pred.suggestions||[],attrs=pred.attributes||{};const target=$('#studio-review',node());target.innerHTML=`<h3>Review suggestions</h3><div class="studio-suggestions"><b>AI category suggestions:</b> ${sug.map(s=>`${esc(s.category)} (${Number(s.score).toFixed(3)})`).join(' · ')||'None'}<p>Model scores are uncalibrated. Every value requires your confirmation.</p>${Object.entries(attrs).map(([name,value])=>`<p><b>${esc(name)}:</b> ${value.eligible?value.suggestions?.map(s=>esc(s.value)).join(' · ')||'No suggestion':'Not estimated for this category'}</p>`).join('')}${p.quality?.warnings?.map(w=>`<p>Photo tip: ${esc(w.message)} ${esc(w.action)}</p>`).join('')||''}</div><form id="studio-confirm" class="studio-form"><div class="studio-fields"><label>Confirmed category<select name="category" required><option value="">Choose a category</option>${categories().map(c=>`<option value="${c}">${c}</option>`).join('')}</select></label><label>Photo type<select name="garment_photo_type" required><option value="">Choose photo type</option><option value="flat-lay">Flat lay</option><option value="model">Worn by model</option></select></label><label>Color (optional)<select name="color"><option value="">Unknown</option>${['beige','black','blue','brown','green','grey','navy','orange','pink','purple','red','white','yellow'].map(c=>`<option>${c}</option>`).join('')}</select></label><label>Pattern (optional)<select name="pattern"><option value="">Unknown</option>${['solid','striped','checked','printed','floral'].map(c=>`<option>${c}</option>`).join('')}</select></label><label>Sleeve length (optional)<select name="sleeve_length"><option value="">Unknown</option>${['sleeveless','short','long'].map(c=>`<option>${c}</option>`).join('')}</select></label><label>Name (optional)<input name="name" maxlength="120"></label></div><div class="studio-actions"><button class="btn ghost" type="button" data-action="describe">Generate description</button></div><label>Description<textarea name="description" placeholder="Generate after confirming category, or enter your own text"></textarea></label><button class="btn">Save garment</button></form>`}
async function fetchAvatarExport(result){
 const max=50*1024*1024, source=result.url;
 if(typeof source!=='string'||!source)throw Error('Avaturn returned no export URL.');
 let url;
 if(result.urlType==='dataURL'){if(!source.startsWith('data:')||source.length>Math.ceil(max*4/3)+1024)throw Error('Avaturn export exceeds 50 MB.');url=source}
 else if(result.urlType==='httpURL'){const parsed=new URL(source);if(parsed.protocol!=='https:'||parsed.username||parsed.password||!state.avatarConfig.export_origins.includes(parsed.origin))throw Error('Avaturn export origin is not configured.');url=parsed.href}
 else throw Error('Avaturn returned an unsupported export type.');
 const response=await fetch(url,{credentials:'omit',redirect:'error',mode:result.urlType==='dataURL'?'same-origin':'cors'});
 if(!response.ok)throw Error('Avaturn export download failed.');
 const type=response.headers.get('content-type')?.split(';')[0].trim().toLowerCase();
 if(type&&!['model/gltf-binary','application/octet-stream'].includes(type))throw Error('Avaturn export is not a GLB.');
 if(Number(response.headers.get('content-length')||0)>max)throw Error('Avaturn export exceeds 50 MB.');
 const reader=response.body?.getReader();if(!reader)throw Error('Avaturn export stream is unavailable.');
 const chunks=[];let size=0;try{while(true){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;if(size>max){await reader.cancel();throw Error('Avaturn export exceeds 50 MB.')}chunks.push(value)}}finally{reader.releaseLock()}
 return new File(chunks,'avaturn-avatar.glb',{type:'model/gltf-binary'});
}
async function openCreator(){
 if(!state.avatarConfig?.avaturn_url)throw Error('Avaturn creator is not configured.');
 if(!$('#studio-provider-consent',node()).checked)throw Error('Accept the Avaturn photo-processing disclosure first.');
 state.avatarConsent=await request('/avatars/consents',{method:'POST',body:{accepted:true}});
 const {AvaturnSDK}=await import('/static/vendor/avaturn-sdk.js');
 closeAvatarSdk();
 const sdk=new AvaturnSDK();state.avatarSdk=sdk;
 const expectedOrigin=new URL(state.avatarConfig.avaturn_url).origin;
 state.avatarGate=event=>{if(event.data?.source!=='v1.avaturn-sdk-server')return;const frame=$('#studio-creator iframe',node());if(event.origin!==expectedOrigin||event.source!==frame?.contentWindow)event.stopImmediatePropagation()};
 window.addEventListener('message',state.avatarGate,true);
 sdk.on('error',issue=>message(issue.message||'Avaturn could not continue.',true));
 sdk.on('export',result=>{safe(async()=>{
   if(state.avatarSdk!==sdk||active()!=='bo7-avatar'||!result.avatarId)throw Error('Avaturn export is no longer active.');
   message('Downloading the Avaturn GLB…');const file=await fetchAvatarExport(result);
   const form=new FormData();form.set('model',file);form.set('provider_avatar_id',result.avatarId);form.set('consent_id',state.avatarConsent.id);form.set('consent_version',state.avatarConsent.consent_version);
   await request('/avatars/current',{method:'PUT',body:form});closeAvatarSdk();await refresh('bo7-avatar');message('Avaturn avatar saved privately.');
 })});
 try{await sdk.init($('#studio-creator',node()),{url:state.avatarConfig.avaturn_url,iframeClassName:'studio-avaturn-frame'})}catch(error){closeAvatarSdk();throw error}
 const frame=$('#studio-creator iframe',node());if(frame)frame.title='Avaturn 3D avatar creator';message('Avaturn creator loaded. Complete the provider flow and export to save.');
}
async function detail(id){const g=await request('/garments/'+id);state.selected=g;$('#studio-detail',node()).innerHTML=`<h3>Garment details</h3><img class="studio-preview" src="${image(g.image_url)}" alt="${esc(g.category)}"><form id="studio-edit" class="studio-form"><input type="hidden" name="id" value="${g.id}"><div class="studio-fields"><label>Name<input name="name" value="${esc(g.name||'')}"></label><label>Category<select name="category">${categories().map(c=>`<option ${c===g.category?'selected':''}>${c}</option>`).join('')}</select></label></div><label>Description (${g.description_is_manual?'manually edited':'automatic'})<textarea name="description">${esc(g.description)}</textarea></label><div class="studio-actions"><button class="btn">Save edits</button><button class="btn ghost" type="button" data-action="delete-garment" data-id="${g.id}">Delete</button><button class="btn ghost" type="button" data-action="close-detail">Cancel</button></div></form>`}
async function safe(action){if(state.busy){message('Still processing. Please retry in a moment.');return}state.busy=true;try{await action()}catch(e){message(e.message,true)}finally{state.busy=false}}
document.addEventListener('submit',e=>{if(!e.target.closest('.studio'))return;e.preventDefault();const f=e.target;
 safe(async()=>{const formId=f.getAttribute('id');if(formId==='studio-auth'){const b=Object.fromEntries(new FormData(f));const mode=e.submitter?.value||'login';const result=await request('/auth/'+mode,{method:'POST',body:b});state.user=result.user;state.csrf=result.csrf_token;render();message('Signed in.');}
 else if(formId==='studio-upload'){const file=f.elements.image.files[0];if(!file)return;if(file.size>10*1024*1024)throw Error('Photo exceeds 10 MB.');const data=new FormData();data.append('image',file);state.uploadKey ||= crypto.randomUUID();state.pending=await request('/garments/analyze',{method:'POST',body:data,key:state.uploadKey});review();message('Analysis complete. Confirm every value before saving.');}
 else if(formId==='studio-confirm'){const data=Object.fromEntries(new FormData(f));if(!data.category||!data.garment_photo_type)throw Error('Confirm category and photo type.');const body={pending_upload_id:state.pending.id,category:data.category,garment_photo_type:data.garment_photo_type};for(const name of ['color','pattern','sleeve_length','name'])if(data[name])body[name]=data[name];if(data.description?.trim() && f.elements.description.dataset.generated!==data.description.trim())body.description=data.description.trim();const garment=await request('/garments',{method:'POST',body});state.pending=null;state.uploadKey=null;location.hash='bo6-wardrobe';render();message('Saved '+garment.category+'.');}
 else if(formId==='studio-edit'){const data=Object.fromEntries(new FormData(f));const changes={name:data.name,category:data.category};if(data.description!==state.selected.description)changes.description=data.description;await request('/garments/'+data.id,{method:'PATCH',body:changes});await wardrobe();$('#studio-detail',node()).innerHTML='';message('Garment updated.');}
 else if(formId==='studio-person'){const data=new FormData(f);data.set('consent','true');await request('/person-photos',{method:'POST',body:data});await refresh('bo7-tryon');message('Private person photo saved.');}
 else if(formId==='studio-avatar-import'){const consent=await request('/avatars/consents',{method:'POST',body:{accepted:true},expected:201});const data=new FormData(f);data.delete('consent');data.set('consent_id',consent.id);data.set('consent_version',consent.consent_version);await request('/avatars/current',{method:'PUT',body:data});await refresh('bo7-avatar');message('Private Avaturn export saved.');}
 });
});
document.addEventListener('change',e=>{
 if(e.target.matches('#studio-upload input[type=file]')){
   if(state.previewUrl)URL.revokeObjectURL(state.previewUrl);
   state.uploadKey=null;state.pending=null;const file=e.target.files?.[0],target=$('#studio-preview',node());
   if(!file){target.replaceChildren();return}
   if(!['image/jpeg','image/png','image/webp'].includes(file.type)||file.size>10*1024*1024){target.textContent='Choose a JPEG, PNG or WebP image up to 10 MB.';return}
   state.previewUrl=URL.createObjectURL(file);target.innerHTML=`<p>${esc(file.name)}</p><img class="studio-preview" alt="Selected garment preview" src="${state.previewUrl}">`;
 }
 if(e.target.closest('#studio-confirm')&&e.target.matches('select[name=category],select[name=color],select[name=pattern],select[name=sleeve_length]')){
   const f=$('#studio-confirm',node()),textarea=f.elements.description;
   if(textarea.dataset.generated&&textarea.value===textarea.dataset.generated){textarea.value='';delete textarea.dataset.generated;message('Confirmed values changed. Generate the description again before saving.')}
   const category=f.elements.category.value;
   if(['jeans','shorts','skirt','trousers'].includes(category)){f.elements.sleeve_length.value='';f.elements.sleeve_length.disabled=true}else f.elements.sleeve_length.disabled=false;
 }
});
document.addEventListener('click',e=>{const button=e.target.closest('[data-action]');if(!button||!button.closest('.studio'))return;const action=button.dataset.action;
 safe(async()=>{if(action==='logout'){await request('/auth/logout',{method:'POST'});state.user=null;state.csrf=null;state.pending=null;render();return}
 if(action==='filter')return wardrobe();if(action==='reset'){render();return}if(action==='page')return wardrobe(Number(button.dataset.page));if(action==='detail')return detail(button.dataset.id);if(action==='close-detail'){$('#studio-detail',node()).innerHTML='';return}
 if(action==='delete-garment'){if(!confirm('Delete this garment and its private image?'))return;await request('/garments/'+button.dataset.id,{method:'DELETE'});await wardrobe();$('#studio-detail',node()).innerHTML='';return}
 if(action==='describe'){const f=$('#studio-confirm',node()),data=Object.fromEntries(new FormData(f));if(!data.category)throw Error('Choose and confirm a category first.');const confirmed={category:data.category};for(const field of ['color','pattern','sleeve_length'])if(data[field])confirmed[field]=data[field];const described=await request('/garments/describe',{method:'POST',body:{pending_upload_id:state.pending.id,confirmed}});f.elements.description.value=described.text||described.description||'';f.elements.description.dataset.generated=f.elements.description.value;message('Automatic description generated. You can edit it before saving.');return}
 if(action==='submit-mock'){const garment_id=$('#studio-garment',node()).value,person_photo_id=$('#studio-photo',node()).value;if(!garment_id||!person_photo_id)throw Error('Select a garment and person photo.');const j=await request('/try-on/jobs',{method:'POST',body:{garment_id,person_photo_id},key:crypto.randomUUID()});message(`MOCK job ${j.state}. No try-on model ran.`);return}
 if(action==='cancel-job'){await request('/try-on/jobs/'+button.dataset.id+'/cancel',{method:'POST'});return refresh('bo7-history')}
 if(action==='delete-job'){if(!confirm('Delete this job and its private result?'))return;await request('/try-on/jobs/'+button.dataset.id,{method:'DELETE'});return refresh('bo7-history')}
 if(action==='delete-avatar'){if(!confirm('Delete the saved avatar?'))return;await request('/avatars/current',{method:'DELETE'});return refresh('bo7-avatar')}
 if(action==='open-creator')return openCreator();
 if(action==='close-creator'){closeAvatarSdk();$('#studio-creator',node()).replaceChildren();message('Avaturn creator closed.');return}
 });
});
document.addEventListener('dressme:section',e=>{if(PAGES.some(([id])=>id===e.detail))render()});
window.addEventListener('hashchange',()=>{if(document.getElementById(active()) && typeof window.go==='function')window.go(active())});
loadSession();
