const { chromium } = require(process.env.DRESSME_PLAYWRIGHT_PATH || 'playwright');
const path = require('path');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');

const root = path.resolve(__dirname, '..');
const screenshotDir = process.env.DRESSME_SCREENSHOT_DIR || path.join(os.tmpdir(), 'dressme-integration-screenshots');
fs.mkdirSync(screenshotDir, {recursive:true});
const base = 'http://127.0.0.1:8002';
(async () => {
  const browser = await chromium.launch({headless:true,executablePath:process.env.DRESSME_BROWSER_EXECUTABLE || chromium.executablePath()});
  const page = await browser.newPage({viewport:{width:1440,height:900}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const password = 'Browser-check-' + crypto.randomBytes(12).toString('hex');
  try {
    await page.goto(base + '/#ootd');
    await page.screenshot({path:path.join(screenshotDir,'team-ootd-desktop.png')});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(screenshotDir,'team-ootd-mobile.png')});
    await page.setViewportSize({width:1440,height:900});
    for (const id of ['ootd','score','comp','sim','wardrobe']) {
      await page.evaluate(id => window.go(id), id);
      if (!(await page.locator(`main section#${id}`).isVisible())) throw Error(`${id} hidden`);
    }
    console.log('PASS five original sections visible through original go()');
    await page.goto(base + '/#bo6-wardrobe');
    await page.reload();
    if (!(await page.locator('#bo6-wardrobe').isVisible())) throw Error('studio deep link did not survive reload');
    const duplicateIds=await page.evaluate(() => {const ids=[...document.querySelectorAll('[id]')].map(e=>e.id);return ids.filter((id,i)=>ids.indexOf(id)!==i)});
    if(duplicateIds.length) throw Error('duplicate DOM ids: '+duplicateIds.join(','));
    await page.locator('.studio-nav a[href="#bo6-add"]').click();
    await page.locator('#bo6-add').waitFor({state:'visible'});
    await page.goBack();
    await page.locator('#bo6-wardrobe').waitFor({state:'visible'});
    console.log('PASS studio deep link reload, sidebar navigation, back and unique IDs');
    await page.goto(base + '/#bo6-add');
    await page.locator('#studio-auth input[name=email]').fill(`browser-${crypto.randomUUID()}@example.invalid`);
    await page.locator('#studio-auth input[name=password]').fill(password);
    await page.getByRole('button',{name:'Create account'}).click();
    await page.locator('#studio-upload input[type=file]').setInputFiles(path.join(root,'data/img/P01133864.jpg'));
    await page.getByAltText('Selected garment preview').waitFor();
    await page.getByRole('button',{name:'Analyze photo'}).click();
    await page.locator('#studio-confirm select[name=category]').waitFor();
    if (await page.locator('#studio-confirm select[name=category]').inputValue()) throw Error('AI suggestion was silently confirmed');
    const categorySuggestion=page.locator('[data-action="suggest-category"]').first();
    const suggestedCategory=await categorySuggestion.getAttribute('data-value');
    await categorySuggestion.click();
    if(await page.locator('#studio-confirm select[name=category]').inputValue()!==suggestedCategory) throw Error('category suggestion did not fill the review field');
    if(await categorySuggestion.getAttribute('aria-pressed')!=='true') throw Error('selected category chip is not announced');
    const categorySuggestions=page.locator('[data-action="suggest-category"]');
    if(await categorySuggestions.count()>1){
      const secondCategory=categorySuggestions.nth(1),secondValue=await secondCategory.getAttribute('data-value');
      await secondCategory.click();
      if(await categorySuggestion.getAttribute('aria-pressed')!=='false'||await secondCategory.getAttribute('aria-pressed')!=='true') throw Error('category candidate selection is not exclusive');
      await page.locator('#studio-confirm select[name=category]').selectOption(suggestedCategory);
      if(await categorySuggestion.getAttribute('aria-pressed')!=='true'||await secondCategory.getAttribute('aria-pressed')!=='false') throw Error('manual category change did not update chip state');
      await page.locator('#studio-confirm select[name=category]').selectOption(suggestedCategory);
    }
    const attributeSuggestion=page.locator('[data-action="suggest-attribute"]').first();
    if(await attributeSuggestion.count()){
      const field=await attributeSuggestion.getAttribute('data-field'), value=await attributeSuggestion.getAttribute('data-value');
      await attributeSuggestion.click();
      if(await page.locator(`#studio-confirm [name="${field}"]`).inputValue()!==value) throw Error('attribute suggestion did not fill the review field');
      if(await attributeSuggestion.getAttribute('aria-pressed')!=='true') throw Error('selected attribute chip is not announced');
      const group=page.locator(`[data-action="suggest-attribute"][data-field="${field}"]`);
      if(await group.count()>1){
        const second=group.nth(1);await second.click();
        if(await attributeSuggestion.getAttribute('aria-pressed')!=='false'||await second.getAttribute('aria-pressed')!=='true') throw Error('attribute candidate selection is not exclusive');
        const candidates=await group.evaluateAll(nodes=>nodes.map(n=>n.dataset.value));
        const control=page.locator(`#studio-confirm [name="${field}"]`);
        const manual=await control.locator('option').evaluateAll((nodes,values)=>nodes.map(n=>n.value).find(v=>v&&!values.includes(v)),candidates);
        if(manual){await control.selectOption(manual);if(await group.evaluateAll(nodes=>nodes.some(n=>n.getAttribute('aria-pressed')==='true')))throw Error('manual attribute correction left a false selected chip')}
      }
    }
    if(['jeans','shorts','skirt','trousers'].includes(suggestedCategory)){
      if(!await page.locator('#studio-confirm select[name=sleeve_length]').isDisabled())throw Error('incompatible sleeve field remained enabled');
      if(await page.locator('[data-action="suggest-attribute"][data-field="sleeve_length"]').count())throw Error('ineligible sleeve suggestion was rendered');
    }
    await page.locator('#studio-confirm select[name=garment_photo_type]').selectOption('flat-lay');
    await page.getByRole('button',{name:'Generate description'}).click();
    await page.waitForFunction(() => document.querySelector('#studio-confirm textarea[name=description]')?.value);
    const text = await page.locator('#studio-confirm textarea[name=description]').inputValue();
    if (!text.toLowerCase().includes('trousers')) throw Error('description did not reflect category');
    if(await categorySuggestions.count()>1){
      await categorySuggestions.nth(1).click();
      await page.waitForFunction(() => document.querySelector('#studio-description-state')?.textContent.includes('out of date'));
      if(await page.locator('#studio-confirm textarea[name=description]').inputValue()!==text) throw Error('stale generated text was discarded');
      await page.getByRole('button',{name:'Generate description'}).click();
      await page.waitForFunction(() => document.querySelector('#studio-description-state')?.textContent.includes('Generated from your selected values'));
    }
    await page.screenshot({path:path.join(screenshotDir,'bo6-review-desktop.png')});
    await page.getByRole('button',{name:'Save garment'}).click();
    await page.locator('#bo6-wardrobe').waitFor({state:'visible'});
    await page.getByRole('button',{name:'View and edit'}).click();
    await page.locator('#studio-edit textarea[name=description]').fill('Reviewed catalog trousers.');
    await page.getByRole('button',{name:'Save edits'}).click();
    await page.getByRole('status').getByText('Garment updated.').waitFor();
    await page.reload();
    await page.locator('#bo6-wardrobe').waitFor({state:'visible'});
    await page.getByText('Reviewed catalog trousers.').waitFor();
    for(const width of [360,390,768,1440]){
      await page.setViewportSize({width,height:844});
      if(width===390){await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:path.join(screenshotDir,'bo6-wardrobe-mobile.png')});}
      const layout=await page.evaluate(() => {window.scrollTo(1000,scrollY);return {scrollX,clipped:[...document.querySelectorAll('.studio-nav a')].filter(e=>{const b=e.getBoundingClientRect();return b.left<0||b.right>innerWidth}).map(e=>e.textContent)}});
      if(layout.scrollX>0||layout.clipped.length) throw Error(`${width}px studio overflow or clipped links: ${JSON.stringify(layout)}`);
    }
    console.log('PASS browser BO6 analyze → confirm → describe → save → edit → reload; Studio navigation fits 360, 390, 768 and 1440px');
    await page.goto(base+'/#bo7-tryon');
    await page.getByText('MOCK · no try-on model runs in this application').waitFor();
    await page.getByRole('button',{name:'Submit MOCK job'}).waitFor();
    if (await page.getByRole('button',{name:'Submit MOCK job'}).isEnabled()) throw Error('mock submission available without worker');
    await page.goto(base+'/#bo7-avatar');
    await page.getByText(/provider session approved for this origin/).waitFor();
    const vendors=await page.evaluate(async()=>{const sdk=await import('/static/vendor/avaturn-sdk.js');await import('/static/vendor/model-viewer.min.js');return !!sdk.AvaturnSDK&&!!customElements.get('model-viewer')});
    if(!vendors)throw Error('Avaturn SDK or 3D viewer did not load');
    console.log('PASS BO7 unavailable mock runtime and provider limits shown in browser');
    if (errors.length) throw Error('page errors: '+errors.join(' | '));
  } finally {
    if (await page.locator('#studio-auth').count()===0) {
      await page.evaluate(async password => {
        const csrf=await fetch('/studio-api/auth/csrf',{method:'POST',headers:{'X-CSRF-Bootstrap':'1'}}).then(r=>r.json());
        const deleted=await fetch('/studio-api/auth/account',{method:'DELETE',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf.csrf_token},body:JSON.stringify({password,confirmation:'DELETE'})});
        if(deleted.status!==204) throw Error('disposable account cleanup '+deleted.status);
      }, password);
      console.log('PASS browser account cleanup');
    }
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode=1 });
