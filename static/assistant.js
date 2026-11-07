import {request as authenticatedRequest, state as authState} from './studio/core.js?v=bo7ootd9';
(() => {
  'use strict';
  const q = s => document.querySelector(s);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let profile = {wardrobe_ids: [], wardrobe: [], preferences: []}, catalog = [], busy = true, chatEnabled = true;
  const labels = {top:'Haut',bottom:'Bas',onepiece:'Robe / combinaison',shoes:'Chaussures',outerwear:'Veste / manteau',layer:'Couche',bag:'Sac',accessory:'Accessoire',unknown:'À renseigner'};
  async function request(path, method = 'GET', body) {
    return authenticatedRequest('/' + path, {method, body, base:'/api/assistant'});
  }
  function errorText(error) { q('#assistant-profile-status').textContent = error.message; }
  function message(text, user = false) {
    const node = document.createElement('article');
    node.className = 'assistant-message' + (user ? ' user' : '');
    const paragraph = document.createElement('p'); paragraph.textContent = text; node.appendChild(paragraph);
    q('#assistant-messages').appendChild(node); node.scrollIntoView({block:'nearest',behavior:'smooth'});
    return node;
  }
  function productCard(item, controls = '') {
    const colors = item.colors?.length ? item.colors.join(', ') : 'couleur inconnue';
    const price = item.price == null ? 'prix inconnu' : `${item.price} ${item.currency || '(devise inconnue)'}`;
    return `<div class="assistant-product"><img loading="lazy" src="${esc(item.image_url)}" alt="${esc(item.name)}"><p><b>${esc(item.name)}</b><br>${esc(labels[item.role] || item.role)} · ${esc(colors)}<br>${esc(price)}<br>${esc(item.gender || 'genre inconnu')}</p>${controls}</div>`;
  }
  function outfit(row, title) {
    const d = row.score_details;
    const weights = Object.keys(d.components).map(k => `<tr><td>${esc(k)}</td><td>${d.components[k].toFixed(6)}</td><td>${d.weights[k].toFixed(2)}</td><td>${d.contributions[k].toFixed(6)}</td></tr>`).join('');
    const checks = row.constraint_report.map(r => `<li>${esc(r.facet?.quote || r.criterion)} : ${r.passed === true ? 'vérifié' : r.passed === false ? 'non satisfait' : 'non vérifiable'}${r.reason ? ' · ' + esc(r.reason) : ''}</li>`).join('');
    return `<h3>${esc(title)}</h3><span class="assistant-badge">${row.all_constraints_verified ? 'Critères explicites vérifiés' : 'Résultat avec limites explicites'}</span><div class="assistant-products">${row.items.map(p => productCard(p)).join('')}</div><p>${esc(row.explanation)}</p><details><summary>Score, préférences et preuves</summary><table><thead><tr><th>Composante</th><th>Valeur</th><th>Poids</th><th>Contribution</th></tr></thead><tbody>${weights}<tr><th>Total</th><td colspan="3">${d.total.toFixed(6)}</td></tr></tbody></table><p>Les poids sont configurables ; ils ne sont pas scientifiquement optimaux.</p><ul>${checks || '<li>Aucun filtre explicite supplémentaire.</li>'}</ul><pre>${esc(JSON.stringify({bo1:row.bo1, preferences:d.preferences,item_ids:row.item_ids}, null, 2))}</pre></details>`;
  }
  function renderResult(result) {
    const node = message(result.message || result.status);
    if (['technical_error','model_unavailable','understanding_error'].includes(result.status)) node.classList.add('err');
    if (result.products?.length) node.insertAdjacentHTML('beforeend', `<div class="assistant-products">${result.products.map(r => productCard(r.item)).join('')}</div>`);
    (result.results || []).forEach((row, i) => node.insertAdjacentHTML('beforeend', outfit(row, `Proposition ${i + 1}`)));
    if (result.comparison?.kind === 'replacement') {
      const c = result.comparison;
      const p = document.createElement('p');
      p.textContent = `Proposition ${c.selection_number || 1} · remplacement recalculé : ${c.before_bo1.toFixed(3)} → ${c.after_bo1.toFixed(3)}/10 ; variation ${c.delta_bo1 >= 0 ? '+' : ''}${c.delta_bo1.toFixed(3)}. ${c.kept_ids.length} pièce(s) conservée(s) dans cette tenue.`;
      node.appendChild(p);
    } else if (result.comparison?.kind === 'ranking') {
      const c=result.comparison;
      const p=document.createElement('p');
      p.textContent=`Écart entre les propositions comparées : score BO1 ${c.delta_bo1>=0?'+':''}${c.delta_bo1.toFixed(3)}/10 ; classement pondéré ${c.delta_total>=0?'+':''}${c.delta_total.toFixed(6)}. Contributions à cet écart : `+Object.entries(c.delta_contributions).map(([k,v])=>`${k} ${v>=0?'+':''}${v.toFixed(6)}`).join(' ; ')+'.';
      node.appendChild(p);
    } else if (result.comparison?.before?.length) {
      const details = document.createElement('details');
      const c=result.comparison;
      details.innerHTML = `<summary>Voir la comparaison des préférences</summary><p>${c.same_candidate_pool ? 'Les classements avant et après utilisent les mêmes alternatives.' : 'Deux recherches recalculées ; les combinaisons peuvent différer.'}${c.candidate_pool_changed ? ' Des alternatives ont été ajoutées pour examiner les préférences demandées ; le classement avant est recalculé sur cet ensemble commun.' : ''}</p>` + c.before.map((row,i) => outfit(row, `Classement avant · ${i + 1}`)).join('');
      node.appendChild(details);
      if (c.previous_selection?.length) {
        const previous=document.createElement('details');
        previous.innerHTML='<summary>Propositions affichées avant cette demande</summary>'+c.previous_selection.map((row,i)=>outfit(row,`Proposition précédente ${i+1}`)).join('');
        node.appendChild(previous);
      }
    }
    if (result.limits) { const p = document.createElement('p'); p.className = 'assistant-limits'; p.textContent = result.limits.join(' '); node.appendChild(p); }
    if (result.diagnostics) {
      const details = document.createElement('details'), summary = document.createElement('summary'), pre = document.createElement('pre');
      summary.textContent = 'Plan compris et diagnostic'; pre.textContent = JSON.stringify(result.diagnostics, null, 2);
      details.append(summary, pre); node.appendChild(details);
    }
    node.scrollIntoView({block:'nearest',behavior:'smooth'});
  }
  async function health() {
    const data = await request('health');
    q('#assistant-diagnostics').textContent = JSON.stringify(data, null, 2);
    chatEnabled = Boolean(data.catalog) && data.parser?.enabled !== false;
    q('#assistant-message').disabled = !chatEnabled;
    q('#assistant-send').disabled = busy || !chatEnabled;
    if (!data.catalog) { q('#assistant-health').textContent = 'Service indisponible : ' + (data.error || data.status); return; }
    q('#assistant-health').textContent = `${data.catalog.products} articles · BO1 : score disponible · parseur : ${!chatEnabled ? 'chat en pause sur ce PC' : data.parser.loaded ? 'Qwen3 + ton adaptateur chargé' : data.parser.error ? 'indisponible (voir diagnostic)' : 'Qwen3 + ton adaptateur, chargement au premier message'} · recherche : ${data.rag.error ? 'indisponible' : data.rag.mode}.`;
  }
  async function loadProfile() {
    profile = await request('profile');
    q('#assistant-gender').textContent = {men:'Genre du compte : homme.', women:'Genre du compte : femme.'}[profile.gender] || 'Aucun filtre de genre par défaut. Tu peux le renseigner dans Account.';
    q('#assistant-colors').value = profile.preferences.filter(p => p.field === 'color' && p.mode !== 'exclude').flatMap(p => p.values).join(', ');
    q('#assistant-wardrobe').innerHTML = profile.wardrobe.length ? profile.wardrobe.map(p => productCard(p, `<button class="btn ghost" data-edit="${esc(p.image_id)}">Modifier</button><button class="btn ghost" data-remove="${esc(p.image_id)}">Retirer</button>${p.scoreable ? '' : '<p>Encodage BO1 non vérifié.</p>'}`)).join('') : '<p class="sub">Ton dressing est vide. Le catalogue de démonstration reste disponible.</p>';
  }
  function modal(title) {
    const overlay = document.createElement('div'); overlay.className = 'modal';
    overlay.innerHTML = `<div class="assistant-modal"><div class="row"><h2>${esc(title)}</h2><button class="btn ghost" data-close>Fermer</button></div><div data-content></div></div>`;
    overlay.onclick = e => { if (e.target === overlay || e.target.closest('[data-close]')) overlay.remove(); };
    document.body.appendChild(overlay); return overlay;
  }
  async function addCatalog() {
    if (!catalog.length) catalog = await request('catalog');
    const overlay = modal('Ajouter une pièce possédée');
    const content = overlay.querySelector('[data-content]');
    content.innerHTML = '<label>Recherche dans le catalogue<input type="search" placeholder="shirt, pantalon, beige…"></label><p class="sub" data-count></p><div class="assistant-products"></div>';
    function draw(query = '') {
      const matches = catalog.filter(p => !profile.wardrobe_ids.includes(p.image_id) && `${p.name} ${p.role} ${(p.colors || []).join(' ')}`.toLowerCase().includes(query.toLowerCase()));
      content.querySelector('[data-count]').textContent = `${matches.length} article(s) trouvé(s), ${Math.min(120,matches.length)} affiché(s).`;
      content.querySelector('.assistant-products').innerHTML = matches.slice(0,120).map(p => productCard(p, `<button class="btn" data-pick="${esc(p.image_id)}">Je possède cette pièce</button>`)).join('');
    }
    content.querySelector('input').oninput = e => draw(e.target.value);
    content.onclick = async e => { const button = e.target.closest('[data-pick]'); if (!button) return; try { await request('wardrobe','PUT',{item_ids:[...profile.wardrobe_ids,button.dataset.pick]}); await loadProfile(); overlay.remove(); } catch(error) { errorText(error); } };
    draw(); content.querySelector('input').focus();
  }
  function editMetadata(id) {
    const item = profile.wardrobe.find(p => p.image_id === id); if (!item) return;
    const overlay = modal('Métadonnées de ma pièce');
    const content = overlay.querySelector('[data-content]');
    content.innerHTML = `<p class="sub">Les changements sont propres à ton dressing. Une valeur vide reste inconnue.</p><form><label>Nom<input name="name" required maxlength="300" value="${esc(item.name)}"></label><label>Genre<select name="gender"><option value="">Inconnu</option>${['men','women','unisex'].map(v => `<option ${v===item.gender?'selected':''}>${v}</option>`).join('')}</select></label><label>Palette complète (anglais)<input name="colors" value="${esc((item.colors||[]).join(', '))}"></label><label>Rôle<select name="role">${Object.keys(labels).map(v => `<option value="${v}" ${v===item.role?'selected':''}>${esc(labels[v])}</option>`).join('')}</select></label><label>Prix<input name="price" type="number" min="0" step="0.01" value="${esc(item.price)}"></label><label>Devise ISO<input name="currency" maxlength="3" pattern="[A-Za-z]{3}" value="${esc(item.currency)}" placeholder="EUR, TND…"></label><div class="row"><button class="btn" type="submit">Enregistrer</button><span data-error role="status"></span></div></form>`;
    content.querySelector('form').onsubmit = async e => {
      e.preventDefault(); const data = new FormData(e.target);
      const body = {name:data.get('name'), gender:data.get('gender')||null,colors:data.get('colors').split(',').map(s=>s.trim()).filter(Boolean), role:data.get('role'),price:data.get('price')===''?null:Number(data.get('price')),currency:data.get('currency').toUpperCase()||null};
      try { await request('wardrobe/'+encodeURIComponent(id),'PATCH',body); await loadProfile(); overlay.remove(); } catch(error) { content.querySelector('[data-error]').textContent = error.message; }
    };
  }
  q('#assistant-form').onsubmit = async e => {
    e.preventDefault(); if (busy || !chatEnabled) return;
    const text = q('#assistant-message').value.trim(); if (!text) return;
    busy = true; q('#assistant-send').disabled = q('#assistant-reset').disabled = true;
    message(text, true); q('#assistant-message').value = '';
    const waiting = message('Compréhension et calculs en cours. Le premier chargement peut prendre plusieurs minutes.'); waiting.setAttribute('role','status');
    try { const result = await request('chat','POST',{message:text}); waiting.remove(); renderResult(result); await loadProfile(); }
    catch(error) { waiting.textContent = 'Erreur technique : ' + error.message; }
    finally { busy=false; q('#assistant-reset').disabled=false; q('#assistant-send').disabled=!chatEnabled; health().catch(errorText); }
  };
  q('#assistant-reset').onclick = async () => { try { await request('reset','POST',{}); q('#assistant-messages').replaceChildren(); message('Nouvelle conversation. Tes préférences et ton dressing sont conservés.'); } catch(error) { errorText(error); } };
  q('#assistant-add').onclick = () => addCatalog().catch(errorText);
  q('#assistant-import').onclick = async () => {
    try {
      const selected = typeof WD !== 'undefined' ? WD.items.map(p => p.k) : [];
      if (!selected.length) throw new Error('Sélectionne d’abord tes pièces dans Wardrobe Completion.');
      if (!catalog.length) catalog = await request('catalog');
      const known = new Set(catalog.map(p=>p.image_id));
      const ids = [...new Set([...profile.wardrobe_ids,...selected.filter(id=>known.has(id))])];
      await request('wardrobe','PUT',{item_ids:ids}); await loadProfile();
      q('#assistant-profile-status').textContent = 'Sélection importée par identifiant produit.';
    } catch(error) { errorText(error); }
  };
  q('#assistant-wardrobe').onclick = async e => {
    const edit = e.target.closest('[data-edit]'); if (edit) editMetadata(edit.dataset.edit);
    const remove = e.target.closest('[data-remove]'); if (!remove) return;
    try { await request('wardrobe','PUT',{item_ids:profile.wardrobe_ids.filter(id=>id!==remove.dataset.remove)}); await loadProfile(); } catch(error) { errorText(error); }
  };
  q('#assistant-photo').onchange = async e => {
    const file = e.target.files[0]; if (!file) return;
    const form = new FormData(); form.append('file',file);
    try { const data = await request('wardrobe/photo','POST',form); await loadProfile(); q('#assistant-profile-status').textContent=data.message; editMetadata(data.item_id); } catch(error) { errorText(error); }
    e.target.value='';
  };
  q('#assistant-prefs').onsubmit = async e => {
    e.preventDefault(); const colors = q('#assistant-colors').value.split(',').map(x=>x.trim().toLowerCase()).filter(Boolean);
    const preferences = profile.preferences.filter(p=>p.field!=='color');
    if (colors.length) preferences.push({field:'color',values:colors,mode:'any',strength:'prefer',quote:colors.join(', '),roles:[]});
    try { await request('preferences','PUT',{preferences}); await loadProfile(); q('#assistant-profile-status').textContent = 'Préférences enregistrées, facultatives pour le classement.'; } catch(error) { errorText(error); }
  };
  q('#assistant-send').disabled=q('#assistant-reset').disabled=true;
  let initialized = false;
  function initialize() {
    if (initialized || !authState.user) return;
    initialized = true;
    Promise.all([health(), loadProfile()]).then(()=> {
    if (profile.history.length) profile.history.forEach(h=>message(h.text,h.role==='user'));
    else message(chatEnabled ? 'Décris la tenue que tu cherches. Tu peux ensuite demander une explication, comparer un scénario ou remplacer une seule pièce.' : 'Le chat est en pause sur ce PC. Ton dressing et tes préférences restent disponibles.');
    if (profile.current_results?.length) renderResult({message:'Sélection conservée dans cette conversation.',results:profile.current_results});
  }).catch(error=>{q('#assistant-health').textContent='Service local indisponible : '+error.message;})
    .finally(()=>{busy=false;q('#assistant-send').disabled=!chatEnabled;q('#assistant-reset').disabled=false;});
  }
  document.addEventListener('dressme:authenticated', initialize);
  document.addEventListener('dressme:session-expired', () => q('#assistant-messages').replaceChildren());
  initialize();
})();
