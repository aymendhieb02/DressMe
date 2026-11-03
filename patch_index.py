"""Applique les changements à static/index.html.
Usage :  python patch_index.py static/index.html      (une sauvegarde index.html.bak est créée)
Chaque remplacement est vérifié : si un bloc n'est pas trouvé, le script s'arrête sans rien écrire.
"""
import re, shutil, sys

path = sys.argv[1] if len(sys.argv) > 1 else "static/index.html"
src = open(path, encoding="utf-8").read()
out = src

def sub(pattern, new, label):
    global out
    out, n = re.subn(pattern, lambda m: new, out, count=1, flags=re.S)
    if n != 1:
        sys.exit(f"[ERREUR] bloc introuvable : {label} (rien n'a été modifié)")
    print("OK ", label)

# ------------------------------------------------------------------ 1) CSS du styliste : avatar + bulle à côté (comme l'assistant Daily Edit)
VD_CSS = r'''/* ---------- Verdict : styliste (avatar + bulle à côté, comme l'assistant du Daily Edit) ---------- */
.vd{position:fixed;left:14px;bottom:0;z-index:7;display:flex;align-items:flex-end;gap:12px;max-width:min(94vw,540px);pointer-events:none}
.vd[hidden]{display:none}.vd>*{pointer-events:auto}
.vd-av{width:150px;height:128px;flex:none;overflow:hidden;cursor:pointer;border:0;padding:0;background:none;border-radius:75px 75px 0 0;
 filter:drop-shadow(0 10px 20px #17283a40);transform:translateY(105%);transition:transform .8s cubic-bezier(.2,1.25,.3,1)}
.vd-av img{width:150px;height:150px;object-fit:cover;display:block}
.vd.show .vd-av{transform:none}
.vd-bub{position:relative;margin-bottom:34px;background:#fff;border-radius:22px;padding:14px 34px 12px 18px;max-width:360px;box-shadow:0 14px 34px #17283a30;
 opacity:0;transform:translateY(14px) scale(.96);transition:opacity .4s .55s,transform .4s .55s}
.vd-bub::before{content:"";position:absolute;left:-7px;bottom:26px;width:16px;height:16px;background:#fff;transform:rotate(45deg);border-radius:0 0 0 5px}
.vd.show .vd-bub{opacity:1;transform:none}
.vd.mini .vd-bub{display:none}
.vd-x{position:absolute;top:8px;right:10px;border:0;background:none;font-size:1.2rem;line-height:1;cursor:pointer;color:var(--ink);opacity:.5}
.vd-x:hover{opacity:1}
.vd-text{position:relative;font:400 .9rem/1.5 Inter,sans-serif;min-width:110px;min-height:24px}
.vd-text .ghost{visibility:hidden}.vd-text .typed{position:absolute;left:0;top:0;right:0}
.dots{display:inline-flex;align-items:center;height:24px}
.dots i{width:9px;height:9px;margin:0 5px;border-radius:50%;background:#c9ced3;animation:dotp 1.2s infinite}
.dots i:nth-child(2){animation-delay:.2s}.dots i:nth-child(3){animation-delay:.4s}
@keyframes dotp{0%,70%,100%{background:#c9ced3;transform:none}35%{background:var(--c2);transform:translateY(-4px)}}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
@media(max-width:520px){.vd{left:8px}.vd-av{width:96px;height:82px;border-radius:48px 48px 0 0}.vd-av img{width:96px;height:96px}.vd-bub{margin-bottom:18px;padding:11px 30px 11px 14px;max-width:calc(100vw - 130px)}}
'''
sub(r"/\* ---------- Verdict : styliste.*?(?=</style>)", VD_CSS, "CSS styliste")

# ------------------------------------------------------------------ 2) HTML du styliste
VD_HTML = '''<aside id="vd" class="vd" hidden aria-live="polite">
  <button class="vd-av" id="vd-av" type="button" aria-label="Show or hide the stylist's comment"><img src="/static/avatar.png" alt="Your stylist"></button>
  <div class="vd-bub">
    <button class="vd-x" id="vd-x" type="button" aria-label="Hide">&times;</button>
    <div class="vd-text" id="vd-text"></div>
  </div>
  <span class="sr" id="vd-sr" role="status"></span>
</aside>'''
sub(r'<aside id="vd" class="vd" hidden>.*?</aside>', VD_HTML, "HTML styliste")

# ------------------------------------------------------------------ 3) JS du styliste : on enlève le nuage (cloudify / ResizeObserver)
VD_JS = '''const vdEl=$('#vd'),vdText=$('#vd-text');
let vdTok=0,vdT=null,vdLast='';'''
sub(r"const vdEl=\$\('#vd'\).*?new ResizeObserver\(cloudify\)\.observe\(vdCloud\);", VD_JS, "JS styliste")

# ------------------------------------------------------------------ 4) Finish the Look : 5 pièces, 1 ou 2 à deviner, style / saison / couleurs
COMP_JS = r'''let want='auto',nGuess=1,coCols=[],coLoaded=false;const B2=Builder($('#b2'),5,()=>{});
const WANTS=['auto','top','bottom','dress','outer','shoes','bag','accessory'];
const WL=c=>c==='auto'?'Auto':c==='accessory'?'Accessory':(FR[c]||c);
$('#want').insertAdjacentHTML('beforebegin',`<div class="chips" id="nn2"><span style="align-self:center;font-size:.8rem;opacity:.6">Pieces to guess</span><button class="cc on" data-n2="1">1</button><button class="cc" data-n2="2">2</button></div><div id="copt" style="display:none"></div>`);
function drawWant(){$('#want').innerHTML=nGuess===1?WANTS.map(c=>`<button class="cc ${c===want?'on':''}" data-w="${c}">${WL(c)}</button>`).join(''):'<span style="font-size:.85rem;opacity:.7">With 2 pieces, the model picks the missing categories itself.</span>'}
drawWant();
$('#want').onclick=e=>{const b=e.target.closest('[data-w]');if(!b)return;want=b.dataset.w;drawWant()};
$('#nn2').onclick=e=>{const b=e.target.closest('[data-n2]');if(!b)return;nGuess=+b.dataset.n2;$$('#nn2 .cc').forEach(x=>x.classList.toggle('on',x===b));drawWant()};
function drawOpt(o){if(!o||!o.styles||!o.styles.length)return;
 const sel=(id,label,L)=>`<label style="font-size:.85rem;margin-right:12px">${label} <select id="${id}"><option value="">Any</option>${L.map(v=>`<option>${esc(v)}</option>`).join('')}</select></label>`;
 $('#copt').innerHTML=sel('c-sty','Style',o.styles)+sel('c-sea','Season',o.seasons)+`<div class="chips"><span style="align-self:center;font-size:.8rem;opacity:.6">Colours (max 2)</span>${o.colors.map(c=>`<button class="cc" data-col="${esc(c)}">${esc(c)}</button>`).join('')}</div>`;
 $('#copt').style.display=''}
$('#copt').onclick=e=>{const b=e.target.closest('[data-col]');if(!b)return;const c=b.dataset.col,k=coCols.indexOf(c);
 if(k>=0)coCols.splice(k,1);else if(coCols.length<2)coCols.push(c);else return;b.classList.toggle('on',coCols.includes(c))};
document.addEventListener('dressme:section',async e=>{if(e.detail==='comp'&&!coLoaded){coLoaded=true;try{drawOpt(await api('complete/options'))}catch{coLoaded=false}}});
$('#go2').onclick=()=>{const it=B2.get(),out=$('#cout');
 if(!it.length){out.innerHTML='<div class="err">Add at least 1 item.</div>';return}
 if(it.length+nGuess>5){out.innerHTML=`<div class="err">An outfit has 5 pieces at most: with ${it.length} you can ask for ${5-it.length} more.</div>`;return}
 out.innerHTML='<div class="spin"></div>';
 api('complete',{items:it,n_items:nGuess,want:nGuess===1?want:null,style:$('#c-sty')?.value||'',season:$('#c-sea')?.value||'',colors:coCols}).then(r=>{
  const cats=(nGuess===1&&want==='auto'&&r.cats.length)?`<p class="sub">This look is calling for: ${r.cats.map(c=>`<b>${esc(WL(c[0]))}</b>`).join(' · ')}</p>`:'';
  const note=r.ignored?`<p class="sub">${r.ignored} piece(s) unknown to the model were ignored.</p>`:'';
  const both=nGuess===2&&r.items.length>1?'<p><button class="btn" id="addall">Add both pieces</button></p>':'';
  out.innerHTML=cats+note+both+'<div class="grid">'+r.items.map((x,k)=>`<div class="card" style="animation-delay:${k*.08}s" data-i="${x.i}"><img src="${img(x.k)}"><p><em>${nGuess===2?`Piece ${k+1} · `:''}${FR[x.c]}</em><br>${esc(x.d.slice(0,46))}<br><b style="color:var(--c2)">+ Add</b></p></div>`).join('')+'</div>';
  const full=()=>out.insertAdjacentHTML('afterbegin','<div class="err">Remove an item first.</div>');
  $$('.card',out).forEach(c=>c.onclick=()=>{if(!B2.put(+c.dataset.i))full()});
  const all=$('#addall',out);if(all)all.onclick=()=>{if(5-B2.get().length<r.items.length)return full();r.items.forEach(x=>B2.put(x.i))}
 }).catch(e=>out.innerHTML=`<div class="err">${esc(e.message)}</div>`)};
$('#ex2').onclick=async()=>{EX=EX||await api('examples');B2.set(EX[Math.random()*EX.length|0].items.slice(0,2))};'''
sub(r"let want='auto';.*?items\.slice\(0,2\)\)\};", COMP_JS, "JS Finish the Look")

shutil.copy(path, path + ".bak")
open(path, "w", encoding="utf-8").write(out)
print(f"\nTerminé -> {path} (sauvegarde : {path}.bak)")
