"""2e patch de static/index.html (à lancer APRES patch_index.py) :
   1) Daily Edit : popup d'occasions qui monte du bas au milieu de l'écran (4 occasions en cartes),
      il redescend après le choix, l'avatar reste à gauche avec une pastille de l'occasion choisie.
   2) Finish the Look : nouveau design, Style / Saison / Couleurs deviennent des FILTRES (popover + pastilles),
      curseur "Guess 1 / Guess 2", résultats animés, paire de pièces pour "Guess 2".
Usage :  python patch_index2.py static/index.html     (sauvegarde : index.html.bak2)
"""
import re, shutil, sys

path = sys.argv[1] if len(sys.argv) > 1 else "static/index.html"
out = open(path, encoding="utf-8").read()

def sub(pattern, new, label):
    global out
    out, n = re.subn(pattern, lambda m: new, out, count=1, flags=re.S)
    if n != 1:
        sys.exit(f"[ERREUR] bloc introuvable : {label}  (rien n'a été modifié ; patch_index.py a-t-il été lancé avant ?)")
    print("OK ", label)

# ====================================================================== CSS
OCC_CSS = r'''.occ{position:fixed;left:14px;bottom:0;z-index:7;display:flex;align-items:flex-end;gap:10px;max-width:min(94vw,420px);pointer-events:none}
.occ[hidden]{display:none}.occ>*{pointer-events:auto}
.occ-av{width:150px;height:128px;flex:none;overflow:hidden;cursor:pointer;border:0;padding:0;background:none;border-radius:75px 75px 0 0;
 filter:drop-shadow(0 10px 20px #17283a40);transform:translateY(105%);transition:transform .8s cubic-bezier(.2,1.25,.3,1)}
.occ-av img{width:150px;height:150px;object-fit:cover;display:block}
.occ.show .occ-av{transform:none}
.occ-av:focus-visible,.occ-tag:focus-visible{outline:3px solid #0e9f9a88;outline-offset:3px}
.occ-tag{margin-bottom:42px;border:0;cursor:pointer;padding:9px 16px;border-radius:999px;background:#fff;color:var(--ink);font:500 .82rem Inter,sans-serif;
 box-shadow:0 10px 26px #17283a2e;opacity:0;transform:translateX(-14px);transition:opacity .4s,transform .4s;white-space:nowrap}
.occ-tag::after{content:"\270E";margin-left:9px;opacity:.45}
.occ-tag.on{opacity:1;transform:none}
/* popup d'occasions : monte du bas jusqu'au milieu, redescend après le choix */
.occp{position:fixed;inset:0;z-index:20;display:flex;align-items:center;justify-content:center;padding:16px;pointer-events:none}
.occp[hidden]{display:none}
.occp::before{content:"";position:absolute;inset:0;background:#17283a55;backdrop-filter:blur(5px);opacity:0;transition:opacity .5s}
.occp.show{pointer-events:auto}.occp.show::before{opacity:1}
.occp-card{position:relative;width:min(700px,100%);background:#ffffffee;backdrop-filter:blur(18px);border:1px solid #fff;border-radius:32px;padding:30px 28px 22px;
 box-shadow:0 34px 90px #17283a55;transform:translateY(115vh);transition:transform .85s cubic-bezier(.2,1.1,.3,1)}
.occp.show .occp-card{transform:none}
.occp-card h3{font:300 1.9rem Fraunces,serif;letter-spacing:-.02em;margin:0}
.occp-card h3 em{font-style:italic;color:var(--c1)}
.occp-x{position:absolute;top:16px;right:20px;border:0;background:none;font-size:1.5rem;line-height:1;cursor:pointer;color:var(--ink);opacity:.4}
.occp-x:hover{opacity:1}
.occp-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:22px}
.ot{position:relative;overflow:hidden;border:0;cursor:pointer;text-align:left;padding:18px 14px 16px;border-radius:22px;background:#fff;color:var(--ink);font:inherit;
 box-shadow:0 8px 22px #17283a14,inset 0 0 0 1px #e1eeec;transition:transform .28s,box-shadow .28s;animation:up .55s both}
.ot::before{content:"";position:absolute;inset:0;background:var(--g);opacity:0;transition:opacity .3s}
.ot>*{position:relative;display:block}
.oi{width:46px;height:46px;border-radius:50%;display:grid!important;place-items:center;background:var(--g);color:#fff;margin-bottom:16px;transition:.3s}
.ot b{font:500 1rem Inter,sans-serif;margin-bottom:3px;transition:color .3s}
.ot small{font-size:.74rem;opacity:.65;line-height:1.35;transition:color .3s,opacity .3s}
.ot:hover,.ot:focus-visible{transform:translateY(-7px);box-shadow:0 18px 36px #17283a30;outline:none}
.ot:hover::before,.ot:focus-visible::before,.ot.on::before{opacity:1}
.ot:hover b,.ot:hover small,.ot:focus-visible b,.ot:focus-visible small,.ot.on b,.ot.on small{color:#fff;opacity:1}
.ot:hover .oi,.ot:focus-visible .oi,.ot.on .oi{background:#ffffff33}
.occp-skip{display:block;margin:18px auto 0;border:0;background:none;cursor:pointer;font:500 .84rem Inter,sans-serif;color:var(--ink);opacity:.55;text-decoration:underline;text-underline-offset:4px}
.occp-skip:hover{opacity:1}
@media(max-width:640px){.occp-grid{grid-template-columns:1fr 1fr}.occp-card{padding:26px 18px 18px}.occp-card h3{font-size:1.5rem}.occ-av{width:96px;height:82px;border-radius:48px 48px 0 0}.occ-av img{width:96px;height:96px}.occ-tag{margin-bottom:22px}}
@media(prefers-reduced-motion:reduce){.occp-card,.occ-av,.ot{transition:none;animation:none}}
'''
sub(r"\.occ\{position:fixed;.*?(?=/\* ---------- Verdict : styliste)", OCC_CSS, "CSS popup occasions")

FTL_CSS = r'''
/* ---------- Finish the Look : barre d'outils + filtres ---------- */
.ftools{display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin:18px 0 6px}
.seg{display:inline-flex;padding:4px;border-radius:999px;background:#e8f4f2;box-shadow:inset 0 0 0 1px #d3e8e5}
.seg button{border:0;background:none;padding:9px 20px;border-radius:999px;font:500 .86rem Inter,sans-serif;color:var(--ink);cursor:pointer;transition:.25s}
.seg button.on{background:var(--ink);color:#fff;box-shadow:0 6px 14px #17283a40}
.fwrap{position:relative}
.fbtn{display:inline-flex;align-items:center;gap:9px;border:0;cursor:pointer;padding:10px 18px;border-radius:999px;background:#fff;color:var(--ink);font:500 .86rem Inter,sans-serif;box-shadow:inset 0 0 0 2px #cfe6e3;transition:.2s}
.fbtn::before{content:"";width:14px;height:10px;background:linear-gradient(currentColor,currentColor) 0 0/100% 2px,linear-gradient(currentColor,currentColor) 50% 50%/70% 2px,linear-gradient(currentColor,currentColor) 0 100%/40% 2px;background-repeat:no-repeat}
.fbtn:hover,.fbtn[aria-expanded="true"]{box-shadow:inset 0 0 0 2px var(--c2);transform:translateY(-1px)}
.fbtn b{min-width:20px;height:20px;padding:0 6px;border-radius:999px;background:var(--c1);color:#fff;font:700 .7rem/20px Inter,sans-serif;text-align:center}
.fbtn b[hidden]{display:none}
.fpop{position:absolute;left:0;top:calc(100% + 12px);z-index:6;width:min(380px,86vw);padding:18px;border-radius:22px;background:#fff;box-shadow:0 24px 60px #17283a38;animation:up .3s both}
.fpop[hidden]{display:none}
.fgrp{margin-bottom:14px}.fgrp>span{display:block;font:500 .66rem Inter,sans-serif;letter-spacing:.28em;text-transform:uppercase;color:var(--c1);margin-bottom:8px}
.fgrp small{letter-spacing:0;text-transform:none;opacity:.55;margin-left:4px}
.fgrp .chips{margin:0;max-height:112px;overflow:auto;padding:2px}
.fgrp .cc{padding:6px 13px;font-size:.8rem}
.sws{display:flex;flex-wrap:wrap;gap:10px;padding:2px}
.sw{position:relative;width:30px;height:30px;border-radius:50%;border:0;cursor:pointer;background:var(--sw);box-shadow:inset 0 0 0 1px #17283a30;transition:transform .2s}
.sw:hover{transform:scale(1.14)}
.sw.on{box-shadow:0 0 0 3px #fff,0 0 0 5px var(--c2)}
.sw.on::after{content:"";position:absolute;left:10px;top:6px;width:6px;height:11px;border:solid #fff;border-width:0 2px 2px 0;transform:rotate(45deg);filter:drop-shadow(0 0 2px #0008)}
.fact{display:flex;justify-content:flex-end;gap:8px;margin-top:6px}.fact .btn{padding:8px 18px;font-size:.84rem}
.ftags{display:flex;flex-wrap:wrap;gap:8px}
.ftag{display:inline-flex;align-items:center;gap:7px;border:0;cursor:pointer;padding:6px 6px 6px 12px;border-radius:999px;background:#fff0ea;color:#c4452b;font:500 .78rem Inter,sans-serif;text-transform:capitalize}
.ftag i{width:12px;height:12px;border-radius:50%;box-shadow:inset 0 0 0 1px #17283a30}
.ftag span{display:grid;place-items:center;width:18px;height:18px;border-radius:50%;background:#ff6b4a22;font-size:.8rem;line-height:1}
.ftag:hover span{background:#ff6b4a}.ftag:hover span{color:#fff}
.rv{animation:flipin .7s cubic-bezier(.2,.9,.3,1) both}
@keyframes flipin{from{opacity:0;transform:perspective(800px) rotateY(-75deg) translateY(18px)}}
.pair{display:flex;flex-wrap:wrap;align-items:center;gap:18px;margin-top:14px;padding:18px;border-radius:26px;background:linear-gradient(135deg,#fff7f1,#e9f6f4);box-shadow:inset 0 0 0 1px #fff}
.pg{display:flex;align-items:center;gap:14px;flex-wrap:wrap}.pg .card{width:170px}
.plus{font:300 2.4rem Fraunces,serif;color:var(--c1)}
.nores{margin:14px 0;padding:16px 18px;border-radius:18px;background:#f1f8f7}
@media(max-width:520px){.seg button{padding:8px 14px}.pg .card{width:140px}}
'''
out = out.replace("</style>", FTL_CSS + "</style>", 1)
print("OK  CSS Finish the Look")

# ====================================================================== HTML popup occasions
OCC_HTML = '''<aside id="occ" class="occ" hidden aria-live="polite">
  <button class="occ-av" id="occ-av" type="button" aria-label="Choose the occasion"><img src="/static/avatar.png" alt="Your style assistant"></button>
  <button class="occ-tag" id="occ-tag" type="button" hidden></button>
</aside>
<div id="occp" class="occp" hidden role="dialog" aria-modal="true" aria-labelledby="occp-q">
  <div class="occp-card">
    <button class="occp-x" id="occp-x" type="button" aria-label="Close">&times;</button>
    <p class="eyebrow" style="color:var(--c1);opacity:1">Daily Edit</p>
    <h3 id="occp-q">What's the <em>occasion</em> today?</h3>
    <div class="occp-grid" id="occp-grid"></div>
    <button class="occp-skip" id="occp-skip" type="button">Weather only, no occasion</button>
  </div>
</div>'''
sub(r'<aside id="occ" class="occ" hidden aria-live="polite">.*?</aside>', OCC_HTML, "HTML popup occasions")

# ====================================================================== JS popup occasions
OCC_JS = r'''const OCCS=[
 {k:'casual',t:'Casual',s:'Relaxed, everyday ease',g:'linear-gradient(135deg,#0e9f9a,#3fcfb0)',i:'<path d="M20.38 3.46 16 2a4 4 0 0 1-8 0L3.62 3.46a2 2 0 0 0-1.34 2.23l.58 3.47a1 1 0 0 0 .99.84H6v10c0 1.1.9 2 2 2h8a2 2 0 0 0 2-2V10h2.15a1 1 0 0 0 .99-.84l.58-3.47a2 2 0 0 0-1.34-2.23z"/>'},
 {k:'meeting',t:'Meeting',s:'Sharp and professional',g:'linear-gradient(135deg,#17283a,#3d6285)',i:'<rect width="20" height="14" x="2" y="7" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>'},
 {k:'fancy',t:'Fancy',s:'Evening, polished',g:'linear-gradient(135deg,#ff6b4a,#ffa94d)',i:'<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 3v4M17 5h4M5 17v4M3 19h4"/>'},
 {k:'date',t:'Date night',s:'Effortlessly charming',g:'linear-gradient(135deg,#e5484d,#ff8fab)',i:'<path d="M19 14c1.5-1.5 3-3.2 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.8 0-3 .5-4.5 2-1.5-1.5-2.7-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4 3 5.5l7 7z"/>'}];
const occEl=$('#occ'),occP=$('#occp'),occTag=$('#occ-tag');let occT=null,occHide=null,occAsked=false;
$('#occp-grid').innerHTML=OCCS.map((o,n)=>`<button class="ot" type="button" data-o="${o.k}" style="--g:${o.g};animation-delay:${.4+n*.08}s"><span class="oi"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${o.i}</svg></span><b>${o.t}</b><small>${o.s}</small></button>`).join('');
function occPop(v){clearTimeout(occHide);
 if(v){occP.hidden=false;requestAnimationFrame(()=>requestAnimationFrame(()=>{occP.classList.add('show');const f=$('.ot',occP);if(f)f.focus({preventScroll:true})}))}
 else{occP.classList.remove('show');occHide=setTimeout(()=>{if(!occP.classList.contains('show'))occP.hidden=true},900)}}
function setOcc(k){OCC=k;$$('.ot',occP).forEach(x=>x.classList.toggle('on',x.dataset.o===k));occPop(false);
 const o=OCCS.find(x=>x.k===k);occTag.textContent=(o?o.t:'Weather only')+(lastBody?'':' · now pick a location');occTag.hidden=false;requestAnimationFrame(()=>occTag.classList.add('on'));
 if(lastBody)ootd(lastBody)}
function occShow(on){clearTimeout(occT);
 if(!on||isLoginRoute){occEl.classList.remove('show');occPop(false);occT=setTimeout(()=>{occEl.hidden=true},700);return}
 occEl.hidden=false;
 occT=setTimeout(()=>{occEl.classList.add('show');if(!occAsked){occAsked=true;setTimeout(()=>{if(tab==='ootd')occPop(true)},650)}},700)}   // l'avatar arrive, puis le popup monte
$('#occp-grid').onclick=e=>{const b=e.target.closest('[data-o]');if(b)setOcc(b.dataset.o)};
$('#occp-skip').onclick=()=>setOcc('');
$('#occp-x').onclick=()=>occPop(false);
occP.onclick=e=>{if(e.target===occP)occPop(false)};
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&occP.classList.contains('show'))occPop(false)});
$('#occ-av').onclick=()=>occPop(true);occTag.onclick=()=>occPop(true);
document.addEventListener('dressme:section',e=>occShow(e.detail==='ootd'));
occShow(tab==='ootd');'''
sub(r"const OCCS=\[\[.*?occShow\(tab==='ootd'\);", OCC_JS, "JS popup occasions")

# ====================================================================== HTML Finish the Look
COMP_HTML = '''<section id="comp" class="glass" hidden><p class="eyebrow">No. 03</p><h2>Finish the Look</h2>
<p class="sub">Pick up to 4 pieces. Our model guesses what is missing.</p>
<div class="row" id="b2"></div>
<div class="ftools">
 <div class="seg" id="nn2" role="group" aria-label="Pieces to guess"><button type="button" data-n2="1" class="on">Guess 1</button><button type="button" data-n2="2">Guess 2</button></div>
 <div class="fwrap">
  <button class="fbtn" id="fbtn" type="button" aria-expanded="false" aria-controls="fpop">Filters <b id="fcount" hidden>0</b></button>
  <div class="fpop" id="fpop" hidden>
   <div class="fgrp"><span>Style</span><div class="chips" id="f-sty"></div></div>
   <div class="fgrp"><span>Season</span><div class="chips" id="f-sea"></div></div>
   <div class="fgrp"><span>Colours <small>max 2</small></span><div class="sws" id="f-col"></div></div>
   <div class="fact"><button class="btn ghost" id="fclear" type="button">Clear</button><button class="btn" id="fdone" type="button">Done</button></div>
  </div>
 </div>
 <div class="ftags" id="ftags"></div>
</div>
<div class="chips" id="want"></div>
<button class="btn" id="go2">Complete my look</button> <button class="btn ghost" id="ex2">Try an example</button><div id="cout"></div></section>'''
sub(r'<section id="comp" class="glass" hidden>.*?</section>', COMP_HTML, "HTML Finish the Look")

# ====================================================================== JS Finish the Look
COMP_JS = r'''let want='auto',nGuess=1,coLoaded=false;const F={sty:'',sea:'',col:[]};const B2=Builder($('#b2'),5,()=>{});
const WANTS=['auto','top','bottom','dress','outer','shoes','bag','accessory'];
const WL=c=>c==='auto'?'Auto':c==='accessory'?'Accessory':(FR[c]||c);
const HEX={black:'#1c1c1e',white:'#ffffff',beige:'#d9c3a0',brown:'#7b5230',grey:'#9aa0a6',gray:'#9aa0a6',navy:'#1f2f5a',blue:'#3b82d6',green:'#3a9d6b',red:'#d6453d',pink:'#f2a1c0',yellow:'#f4cf3a',orange:'#f08a2e',purple:'#7e5bc4',gold:'#c9a227',silver:'#c4c8cc',cream:'#f5ecd6'};
const hexOf=c=>HEX[String(c).toLowerCase()]||'#cfd8dc';
function drawWant(){$('#want').innerHTML=nGuess===1?WANTS.map(c=>`<button class="cc ${c===want?'on':''}" data-w="${c}">${WL(c)}</button>`).join(''):'<span style="font-size:.85rem;opacity:.7">With 2 pieces, the model picks the missing categories itself.</span>'}
drawWant();
$('#want').onclick=e=>{const b=e.target.closest('[data-w]');if(!b)return;want=b.dataset.w;drawWant()};
$('#nn2').onclick=e=>{const b=e.target.closest('[data-n2]');if(!b)return;nGuess=+b.dataset.n2;$$('#nn2 button').forEach(x=>x.classList.toggle('on',x===b));drawWant()};
/* filtres : popover fermé par défaut, les choix actifs s'affichent en petites étiquettes */
const fpop=$('#fpop'),fbtn=$('#fbtn');
const fOpen=v=>{fpop.hidden=!v;fbtn.setAttribute('aria-expanded',String(v))};
fbtn.onclick=e=>{e.stopPropagation();fOpen(fpop.hidden)};
$('#fdone').onclick=()=>fOpen(false);
document.addEventListener('click',e=>{if(!fpop.hidden&&!e.target.closest('.fwrap'))fOpen(false)});
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!fpop.hidden){fOpen(false);fbtn.focus()}});
function fSync(){
 $$('#f-sty .cc').forEach(b=>b.classList.toggle('on',b.dataset.v===F.sty));
 $$('#f-sea .cc').forEach(b=>b.classList.toggle('on',b.dataset.v===F.sea));
 $$('#f-col .sw').forEach(b=>{const on=F.col.includes(b.dataset.v);b.classList.toggle('on',on);b.setAttribute('aria-pressed',String(on))});
 const tags=[];if(F.sty)tags.push(['sty',F.sty]);if(F.sea)tags.push(['sea',F.sea]);F.col.forEach(c=>tags.push(['col',c]));
 $('#ftags').innerHTML=tags.map(([k,v])=>`<button class="ftag" type="button" data-k="${k}" data-v="${esc(v)}" aria-label="Remove ${esc(v)}">${k==='col'?`<i style="background:${hexOf(v)}"></i>`:''}${esc(v)}<span aria-hidden="true">&times;</span></button>`).join('');
 const c=$('#fcount');c.hidden=!tags.length;c.textContent=tags.length}
$('#fclear').onclick=()=>{F.sty=F.sea='';F.col=[];fSync()};
$('#ftags').onclick=e=>{const b=e.target.closest('.ftag');if(!b)return;const k=b.dataset.k,v=b.dataset.v;if(k==='sty')F.sty='';else if(k==='sea')F.sea='';else F.col=F.col.filter(c=>c!==v);fSync()};
$('#f-sty').onclick=e=>{const b=e.target.closest('[data-v]');if(!b)return;F.sty=F.sty===b.dataset.v?'':b.dataset.v;fSync()};
$('#f-sea').onclick=e=>{const b=e.target.closest('[data-v]');if(!b)return;F.sea=F.sea===b.dataset.v?'':b.dataset.v;fSync()};
$('#f-col').onclick=e=>{const b=e.target.closest('[data-v]');if(!b)return;const c=b.dataset.v,k=F.col.indexOf(c);if(k>=0)F.col.splice(k,1);else if(F.col.length<2)F.col.push(c);else F.col=[F.col[1],c];fSync()};
function drawOpt(o){const chip=v=>`<button class="cc" type="button" data-v="${esc(v)}">${esc(v)}</button>`;
 $('#f-sty').innerHTML=(o.styles||[]).map(chip).join('')||'<small style="opacity:.5">No style data</small>';
 $('#f-sea').innerHTML=(o.seasons||[]).map(chip).join('')||'<small style="opacity:.5">No season data</small>';
 $('#f-col').innerHTML=(o.colors||[]).map(c=>`<button class="sw" type="button" data-v="${esc(c)}" style="--sw:${hexOf(c)}" title="${esc(c)}" aria-label="${esc(c)}" aria-pressed="false"></button>`).join('');
 fSync()}
document.addEventListener('dressme:section',async e=>{if(e.detail==='comp'&&!coLoaded){coLoaded=true;try{drawOpt(await api('complete/options'))}catch{coLoaded=false}}});
/* lancement */
$('#go2').onclick=()=>{const it=B2.get(),out=$('#cout');
 if(!it.length){out.innerHTML='<div class="err">Add at least 1 item.</div>';return}
 if(it.length+nGuess>5){out.innerHTML=`<div class="err">An outfit has 5 pieces at most: with ${it.length} you can ask for ${5-it.length} more.</div>`;return}
 out.innerHTML='<div class="spin"></div>';
 api('complete',{items:it,n_items:nGuess,want:nGuess===1?want:null,style:F.sty,season:F.sea,colors:F.col}).then(r=>{
  if(!r.items.length){out.innerHTML='<div class="nores">No suggestion matches these filters. Try removing one.</div>';return}
  const cats=(nGuess===1&&want==='auto'&&r.cats.length)?`<p class="sub">This look is calling for: ${r.cats.map(c=>`<b>${esc(WL(c[0]))}</b>`).join(' · ')}</p>`:'';
  const note=r.ignored?`<p class="sub">${r.ignored} piece(s) unknown to the model were ignored.</p>`:'';
  const card=(x,k,lab)=>`<div class="card rv" style="animation-delay:${k*.12}s" data-i="${x.i}"><img src="${img(x.k)}" alt=""><p><em>${lab}${FR[x.c]}</em><br>${esc(x.d.slice(0,46))}<br><b style="color:var(--c2)">+ Add</b></p></div>`;
  const pair=nGuess===2&&r.items.length>1;
  const body=pair?`<div class="pair"><div class="pg">${r.items.map((x,k)=>card(x,k,`Piece ${k+1} · `)).join('<span class="plus">+</span>')}</div><button class="btn" id="addall" type="button">Add both pieces</button></div>`
   :'<div class="grid">'+r.items.map((x,k)=>card(x,k,'')).join('')+'</div>';
  out.innerHTML=cats+note+body;
  const full=()=>out.insertAdjacentHTML('afterbegin','<div class="err">Remove an item first.</div>');
  $$('.card',out).forEach(c=>c.onclick=()=>{if(!B2.put(+c.dataset.i))full()});
  const all=$('#addall',out);if(all)all.onclick=()=>{if(5-B2.get().length<r.items.length)return full();r.items.forEach(x=>B2.put(x.i))}
 }).catch(e=>out.innerHTML=`<div class="err">${esc(e.message)}</div>`)};
$('#ex2').onclick=async()=>{EX=EX||await api('examples');B2.set(EX[Math.random()*EX.length|0].items.slice(0,2))};'''
sub(r"let want='auto',nGuess=1,coCols=\[\],coLoaded=false;.*?items\.slice\(0,2\)\)\};", COMP_JS, "JS Finish the Look")

shutil.copy(path, path + ".bak2")
open(path, "w", encoding="utf-8").write(out)
print(f"\nTerminé -> {path} (sauvegarde : {path}.bak2)")
