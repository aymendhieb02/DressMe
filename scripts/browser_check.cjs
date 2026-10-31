const {chromium} = require(process.env.DRESSME_PLAYWRIGHT_PATH || 'playwright');
const path = require('path');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');

const root = path.resolve(__dirname, '..');
const screenshotDir = process.env.DRESSME_SCREENSHOT_DIR || path.join(os.tmpdir(), 'dressme-integration-screenshots');
const base = (process.env.DRESSME_BASE_URL || 'http://127.0.0.1:8002').replace(/\/$/, '');
const mailCaptureDir = process.env.DRESSME_CAPTURE_PATH;
fs.mkdirSync(screenshotDir, {recursive: true});

function capturedCode() {
  if (!mailCaptureDir) throw Error('DRESSME_CAPTURE_PATH is required for the captured-email browser journey.');
  const messages = fs.readdirSync(mailCaptureDir).filter(name => name.endsWith('.eml'))
    .map(name => ({name, full: path.join(mailCaptureDir, name), time: fs.statSync(path.join(mailCaptureDir, name)).mtimeMs}))
    .sort((a, b) => b.time - a.time);
  if (!messages.length) throw Error('No local captured recovery email was produced.');
  const source = fs.readFileSync(messages[0].full, 'utf8');
  const match = source.match(/\r?\n\r?\n([0-9]{8})\r?\n/);
  if (!match) throw Error('Captured recovery email did not contain an eight-digit code.');
  return match[1];
}

async function waitForSectionMotion(page, id) {
  await page.waitForFunction(sectionId => {
    const section = document.querySelector(`main section#${sectionId}`);
    return section && section.getAnimations().every(animation => !['running', 'pending'].includes(animation.playState));
  }, id);
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.DRESSME_BROWSER_EXECUTABLE || chromium.executablePath(),
  });
  let context;
  let secondaryContext;
  let accountEmail;
  let accountPassword;
  let cleanupPassword;
  let recoveryPassword;
  let created = false;
  const errors = [];
  try {
    context = await browser.newContext({viewport: {width: 1440, height: 900}});
    const page = await context.newPage();
    page.on('pageerror', error => errors.push(error.message));
    page.on('response', response => {
      if (response.url().endsWith('/studio-api/auth/password-reset/complete') && response.status() === 204 && recoveryPassword) {
        cleanupPassword = recoveryPassword;
      }
    });
    accountEmail = `browser-${crypto.randomUUID()}@example.invalid`;
    accountPassword = 'Browser-check-' + crypto.randomBytes(12).toString('hex');
    cleanupPassword = accountPassword;

    await page.goto(base + '/#ootd');
    await page.screenshot({path: path.join(screenshotDir, 'team-ootd-desktop.png')});
    await page.setViewportSize({width: 390, height: 844});
    await page.screenshot({path: path.join(screenshotDir, 'team-ootd-mobile.png')});
    await page.setViewportSize({width: 1440, height: 900});
    for (const id of ['ootd', 'score', 'comp', 'sim', 'wardrobe']) {
      await page.evaluate(id => window.go(id), id);
      if (!(await page.locator(`main section#${id}`).isVisible())) throw Error(`${id} hidden`);
    }
    console.log('PASS all five original public sections remain navigable');

    await page.goto(base + '/#bo7-tryon');
    await page.locator('#studio-auth').waitFor({state: 'visible'});
    if (await page.locator('.studio-nav').count()) throw Error('protected Studio navigation rendered before sign-in');
    await waitForSectionMotion(page, 'bo7-tryon');
    await page.screenshot({path: path.join(screenshotDir, 'studio-login-desktop.png')});
    await page.setViewportSize({width: 360, height: 800});
    const authLayout = await page.evaluate(() => ({width: innerWidth, scroll: document.documentElement.scrollWidth}));
    if (authLayout.scroll > authLayout.width + 1) throw Error(`login page overflows at 360px: ${JSON.stringify(authLayout)}`);
    await waitForSectionMotion(page, 'bo7-tryon');
    await page.screenshot({path: path.join(screenshotDir, 'studio-login-mobile.png')});
    await page.setViewportSize({width: 1440, height: 900});
    await page.reload();
    await page.locator('#studio-auth').waitFor({state: 'visible'});
    await page.locator('#studio-auth input[name=email]').fill('missing-account@example.invalid');
    await page.locator('#studio-auth input[name=password]').fill('not-the-password');
    await page.getByRole('button', {name: 'Sign in'}).click();
    await page.locator('.studio-status[role=alert]').waitFor({state: 'visible'});
    const loginError = await page.locator('.studio-status[role=alert]').innerText();
    if (!loginError.includes('incorrect') || loginError.toLowerCase().includes('session expired')) throw Error(`invalid credentials were not explained accurately: ${loginError}`);
    const registerButton = page.getByRole('button', {name: 'Create an account'});
    await registerButton.focus();
    await page.keyboard.press('Enter');
    await page.locator('#studio-auth[data-mode="register"]').waitFor();
    if (!await page.locator('#studio-auth input[name=email]').evaluate(input => input === document.activeElement)) throw Error('register view did not move keyboard focus to its first field');
    console.log('PASS invalid credential feedback and keyboard-driven registration focus');
    await page.locator('#studio-auth input[name=email]').fill(accountEmail);
    await page.locator('#studio-auth input[name=password]').fill(accountPassword);
    await page.getByRole('button', {name: 'Create account'}).click();
    created = true;
    await page.locator('.studio-nav').waitFor({state: 'visible'});
    console.log('PASS authentication-first route, registration, and return to intended BO7 page');

    await page.reload();
    await page.locator('.studio-nav').waitFor({state: 'visible'});
    const session = await page.evaluate(() => fetch('/studio-api/auth/me').then(r => r.status));
    if (session !== 200) throw Error(`session did not persist after reload: ${session}`);
    for (const id of ['bo6-wardrobe', 'bo6-add', 'bo7-avatar', 'bo7-tryon', 'bo7-history']) {
      await page.evaluate(id => window.go(id), id);
      await page.locator(`#${id}`).waitFor({state: 'visible'});
      if (!(await page.locator(`#${id} [data-studio-page]`).count())) throw Error(`${id} Studio view was not mounted`);
      const duplicateIds = await page.evaluate(() => {
        const ids = [...document.querySelectorAll('[id]')].map(element => element.id);
        return [...new Set(ids.filter((value, index) => ids.indexOf(value) !== index))];
      });
      if (duplicateIds.length) throw Error(`duplicate IDs on ${id}: ${duplicateIds.join(', ')}`);
    }
    console.log('PASS protected Studio routing, reload, browser Back and unique IDs');
    await page.goto(base + '/#bo6-wardrobe');
    await page.reload();
    await page.locator('#studio-search').waitFor({state: 'visible'});
    await page.locator('.studio-nav a[href="#bo6-add"]').click();
    await page.locator('#studio-upload').waitFor({state: 'visible'});
    await page.goBack();
    await page.locator('#studio-search').waitFor({state: 'visible'});

    await page.goto(base + '/#bo6-add');
    await page.locator('#studio-upload').waitFor({state: 'visible'});
    const fixture = path.join(root, 'data/img/P01133864.jpg');
    await page.locator('#studio-upload input[type=file]').setInputFiles({name: 'not-an-image.txt', mimeType: 'text/plain', buffer: Buffer.from('not an image')});
    await page.waitForFunction(() => document.querySelector('[data-upload-status="garment"]')?.textContent.includes('Choose a JPEG, PNG or WebP image.'));
    if (!(await page.locator('.studio-status[role=alert]').innerText()).includes('Choose a JPEG')) throw Error('upload validation error was not announced as an alert');
    await page.locator('#studio-upload input[type=file]').setInputFiles(fixture);
    try { await page.getByAltText('Selected image preview').waitFor({state: 'visible', timeout: 7000}); }
    catch {
      const status = await page.locator('[data-upload-status="garment"]').innerText().catch(() => '(no upload status)');
      const selected = await page.locator('#studio-upload input[type=file]').evaluate(input => ({name: input.files?.[0]?.name, size: input.files?.[0]?.size, type: input.files?.[0]?.type}));
      throw Error(`garment preview did not render; input=${JSON.stringify(selected)} status=${status}; pageErrors=${errors.join(' | ')}`);
    }
    const previewName = await page.locator('[data-upload-preview="garment"] strong').innerText();
    if (!previewName.endsWith('.jpg')) throw Error('garment filename was not displayed');
    const fixtureBase64 = fs.readFileSync(fixture).toString('base64');
    await page.locator('.studio-upload-zone').evaluate((zone, base64) => {
      const bytes = Uint8Array.from(atob(base64), character => character.charCodeAt(0));
      const file = new File([bytes], 'P01133864.jpg', {type: 'image/jpeg'});
      const transfer = new DataTransfer(); transfer.items.add(file);
      zone.dispatchEvent(new DragEvent('dragover', {bubbles: true, cancelable: true, dataTransfer: transfer}));
      zone.dispatchEvent(new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: transfer}));
    }, fixtureBase64);
    await page.locator('[data-upload-status="garment"]').getByText('File selected. Check the preview before continuing.').waitFor();
    const garmentInput = page.locator('#studio-upload input[type=file]');
    await garmentInput.focus();
    await page.keyboard.press('Tab');
    await page.locator('#studio-upload button[data-action="clear-upload"]').waitFor({state: 'visible'});
    if (!await page.locator('#studio-upload button[data-action="clear-upload"]').evaluate(button => button === document.activeElement)) throw Error('upload clear control is not keyboard reachable');
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => document.querySelector('[data-upload-status="garment"]')?.textContent === 'File removed.');
    await page.locator('#studio-upload input[type=file]').setInputFiles(fixture);
    await page.getByAltText('Selected image preview').waitFor({state: 'visible'});
    console.log('PASS upload format error announcement, drag-and-drop preview and keyboard file removal');
    await page.getByRole('button', {name: '2. Analyze photo'}).click();
    await page.locator('#studio-confirm').waitFor({state: 'visible', timeout: 120000});
    if (await page.locator('#studio-confirm select[name=category]').inputValue()) throw Error('AI suggestion was silently confirmed');
    const categorySuggestion = page.locator('[data-action="suggest-category"]').first();
    const suggestedCategory = await categorySuggestion.getAttribute('data-value');
    await categorySuggestion.click();
    if (await page.locator('#studio-confirm select[name=category]').inputValue() !== suggestedCategory) throw Error('category suggestion did not fill its matching field');
    if (await categorySuggestion.getAttribute('aria-pressed') !== 'true') throw Error('selected category suggestion was not announced');
    const attributeSuggestion = page.locator('[data-action="suggest-attribute"]').first();
    if (await attributeSuggestion.count()) {
      const field = await attributeSuggestion.getAttribute('data-field');
      const value = await attributeSuggestion.getAttribute('data-value');
      await attributeSuggestion.click();
      if (await page.locator(`#studio-confirm [name="${field}"]`).inputValue() !== value) throw Error('attribute suggestion did not fill its matching field');
      if (await attributeSuggestion.getAttribute('aria-pressed') !== 'true') throw Error('selected attribute suggestion was not announced');
    }
    await page.locator('#studio-confirm select[name=garment_photo_type]').selectOption('flat-lay');
    await page.getByRole('button', {name: 'Generate description'}).click();
    await page.waitForFunction(() => document.querySelector('#studio-confirm textarea[name=description]')?.value);
    const generated = await page.locator('#studio-confirm textarea[name=description]').inputValue();
    if (!generated.toLowerCase().includes(suggestedCategory.toLowerCase())) throw Error('description did not reflect the confirmed category');
    const otherCategory = await page.locator('#studio-confirm select[name=category] option').evaluateAll((options, current) => options.map(option => option.value).find(value => value && value !== current), suggestedCategory);
    await page.locator('#studio-confirm select[name=category]').selectOption(otherCategory);
    await page.getByText('out of date').waitFor();
    if (await page.locator('#studio-confirm textarea[name=description]').inputValue() !== generated) throw Error('stale generated description was discarded');
    await page.getByRole('button', {name: 'Generate description'}).click();
    await page.waitForFunction(() => document.querySelector('#studio-description-state')?.textContent.includes('Generated from your confirmed values'));
    await page.locator('#studio-confirm select[name=category]').selectOption(suggestedCategory);
    await page.getByRole('button', {name: 'Generate description'}).click();
    await page.waitForFunction(() => document.querySelector('#studio-description-state')?.textContent.includes('Generated from your confirmed values'));
    await page.waitForFunction(() => document.querySelector('.studio')?.getAttribute('aria-busy') === 'false');
    if (await page.locator('#studio-description-state').innerText() !== 'Generated from your confirmed values. You can edit this text.') throw Error('final generated description was not current before screenshot');
    await page.screenshot({path: path.join(screenshotDir, 'bo6-review-desktop.png')});
    await page.getByRole('button', {name: 'Save garment'}).click();
    await page.locator('#studio-search').waitFor({state: 'visible'});
    await page.getByRole('button', {name: 'View details and edit'}).waitFor();
    await page.getByRole('button', {name: 'View details and edit'}).click();
    await page.locator('#studio-detail-title').waitFor({state: 'visible'});
    await page.waitForFunction(() => document.querySelector('.studio')?.getAttribute('aria-busy') === 'false', null, {timeout: 10000});
    if (!(await page.locator('#studio-detail img[alt^="Private photo"]').count())) throw Error('private image missing from garment detail');
    if (!(await page.locator('#studio-detail .studio-badge.is-auto').count())) throw Error('automatic description provenance missing');
    const savedGarmentId = await page.locator('#studio-detail form#studio-edit input[name=id]').getAttribute('value');
    await page.locator('#studio-detail button[data-action="close-detail"]').focus();
    await page.keyboard.press('Enter');
    await page.locator('#studio-detail-title').waitFor({state: 'detached'});
    if (await page.evaluate(() => document.activeElement?.dataset.id) !== savedGarmentId) throw Error('detail cancel did not return focus to its wardrobe card');
    await page.locator(`button[data-action="detail"][data-id="${savedGarmentId}"]`).click();
    await page.locator('#studio-detail-title').waitFor({state: 'visible'});
    await page.waitForFunction(() => document.querySelector('.studio')?.getAttribute('aria-busy') === 'false', null, {timeout: 10000});
    console.log('PASS detail cancel returns focus to the originating wardrobe card');
    await page.locator('#studio-edit textarea[name=description]').fill('Reviewed disposable browser garment.');
    const manualSaveResponse = page.waitForResponse(response => response.request().method() === 'PATCH' && response.url().endsWith(`/studio-api/garments/${savedGarmentId}`), {timeout: 15000});
    await page.getByRole('button', {name: 'Save changes', exact: true}).click();
    const manualResponse = await manualSaveResponse;
    if (manualResponse.status() !== 200) throw Error(`manual edit PATCH returned ${manualResponse.status()}: ${(await manualResponse.text()).slice(0, 240)}`);
    await page.waitForFunction(() => document.querySelector('.studio-status')?.textContent.includes('Garment updated.'), null, {timeout: 10000});
    await page.getByRole('button', {name: 'View details and edit'}).waitFor();
    const savedManualState = await page.evaluate(id => fetch('/studio-api/garments/' + id).then(r => r.json()), savedGarmentId);
    if (!savedManualState.description_is_manual) throw Error(`manual edit was not saved; description=${savedManualState.description}`);
    await page.getByRole('button', {name: 'View details and edit'}).click();
    await page.locator('#studio-detail-title').waitFor({state: 'visible'});
    await page.waitForFunction(() => document.querySelector('.studio')?.getAttribute('aria-busy') === 'false', null, {timeout: 10000});
    if (!(await page.locator('#studio-detail .studio-badge.is-manual').count())) throw Error('manual description provenance missing after edit');
    await page.locator('#studio-edit select[name=color]').selectOption('blue');
    await page.locator('#studio-edit textarea[name=description]').fill('Correction preserved during attribute changes.');
    const correctionResponse = page.waitForResponse(response => response.request().method() === 'PATCH' && response.url().endsWith(`/studio-api/garments/${savedGarmentId}`), {timeout: 15000});
    await page.getByRole('button', {name: 'Save changes', exact: true}).click();
    const correctionResult = await correctionResponse;
    if (correctionResult.status() !== 200) throw Error(`attribute correction PATCH returned ${correctionResult.status()}: ${(await correctionResult.text()).slice(0, 240)}`);
    await page.waitForFunction(() => document.querySelector('.studio-status')?.textContent.includes('Garment updated.'), null, {timeout: 10000});
    await page.getByRole('button', {name: 'View details and edit'}).waitFor();
    await page.reload();
    await page.getByText('Correction preserved during attribute changes.').waitFor();
    await page.waitForFunction(() => document.querySelector('.studio')?.getAttribute('aria-busy') === 'false');
    await waitForSectionMotion(page, 'bo6-wardrobe');
    for (const width of [360, 390, 768, 1440]) {
      await page.setViewportSize({width, height: 844});
      const layout = await page.evaluate(() => ({width: innerWidth, scroll: document.documentElement.scrollWidth,
        clipped: [...document.querySelectorAll('.studio-nav a')].filter(element => {const r = element.getBoundingClientRect(); return r.left < 0 || r.right > innerWidth;}).map(element => element.textContent)}));
      if (layout.scroll > width + 1 || layout.clipped.length) throw Error(`${width}px layout overflow or clipped navigation: ${JSON.stringify(layout)}`);
      if (width === 390) await page.screenshot({path: path.join(screenshotDir, 'bo6-wardrobe-mobile.png')});
    }
    await page.setViewportSize({width: 1440, height: 900});
    console.log('PASS real BO6 image analyze → suggestion confirmation → automatic description → save → detail edit → reload');
    console.log('PASS Studio layout and controls at 360, 390, 768 and 1440 CSS pixels (browser emulation)');

    await page.goto(base + '/#bo7-tryon');
    await page.locator('#studio-person').waitFor({state: 'visible'});
    await page.getByText(/Submission is disabled because the worker is unavailable/).waitFor();
    const liveSubmit = page.locator('[data-action="submit-mock"]');
    if (await liveSubmit.count() && await liveSubmit.isEnabled()) throw Error('live unavailable worker left submission enabled');
    await page.goto(base + '/#bo7-avatar');
    await page.getByText(/Avaturn is not configured for this origin/).waitFor();
    console.log('PASS live worker-unavailable and provider-unavailable explanations');

    const garmentId = await page.evaluate(async () => {
      return fetch('/studio-api/garments?page_size=1')
        .then(r => r.json()).then(data => data.items[0]?.id);
    });
    if (!garmentId) throw Error('disposable garment was not available for controlled worker UI test');
    await page.route('**/studio-api/health/try-on', route => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({status: 'available', available: true, components: {broker: true, dispatcher: true, worker: true}})}));
    await page.route('**/studio-api/person-photos', route => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify([{id: 'controlled-owned-photo', created_at: new Date().toISOString(), image_url: '/controlled-fixture.png'}])}));
    await page.goto(base + '/#bo7-tryon');
    await page.locator('#studio-garment').waitFor({state: 'visible'});
    await page.locator('#studio-garment').selectOption(garmentId);
    await page.locator('#studio-photo').selectOption('controlled-owned-photo');
    await page.getByText('A worker is available. Submissions create MOCK jobs only.').waitFor();
    if (!(await page.locator('[data-action="submit-mock"]').isEnabled())) throw Error('controlled available worker did not enable valid owned-input selection');
    await page.unrouteAll({behavior: 'wait'});
    console.log('PASS controlled worker-available UI enables submission only after both inputs are selected; no job was sent');

    await page.getByRole('button', {name: 'Sign out'}).click();
    await page.locator('#studio-auth').waitFor({state: 'visible'});
    if (await page.evaluate(() => fetch('/studio-api/auth/me').then(r => r.status)) !== 401) throw Error('protected session remained valid after logout');
    secondaryContext = await browser.newContext();
    const second = await secondaryContext.newPage();
    await second.goto(base + '/#bo6-wardrobe');
    await second.locator('#studio-auth input[name=email]').fill(accountEmail);
    await second.locator('#studio-auth input[name=password]').fill(accountPassword);
    await second.getByRole('button', {name: 'Sign in'}).click();
    await second.locator('.studio-nav').waitFor({state: 'visible'});

    await page.getByRole('button', {name: 'Forgot password?'}).click();
    await page.locator('#studio-recovery-request').waitFor({state: 'visible'});
    await page.locator('#studio-recovery-request input[name=email]').fill(accountEmail);
    await page.getByRole('button', {name: 'Send recovery code'}).click();
    await page.getByRole('heading', {name: 'Check your email'}).waitFor();
    await page.getByRole('button', {name: 'Enter recovery code'}).click();
    const code = capturedCode();
    await page.locator('#studio-recovery-complete input[name=code]').fill(code);
    const newPassword = 'Recovery-check-' + crypto.randomBytes(12).toString('hex');
    recoveryPassword = newPassword;
    await page.locator('#studio-recovery-complete input[name=new_password]').fill(newPassword);
    await page.locator('#studio-recovery-complete input[name=confirm_password]').fill(newPassword);
    await page.getByRole('button', {name: 'Reset password'}).click();
    await page.getByText('Password updated. Sign in with your new password.').waitFor();
    await second.locator('.studio-nav a[href="#bo6-add"]').click();
    await second.locator('#studio-upload').waitFor({state: 'visible'});
    await second.locator('.studio-nav a[href="#bo6-wardrobe"]').click();
    await second.locator('#studio-auth').waitFor({state: 'visible'});
    await second.locator('.studio-status').getByText('Your session expired. Sign in again to continue.').waitFor();
    const expiryMessage = await second.locator('.studio-status').innerText();
    if (!expiryMessage.includes('Your session expired')) throw Error(`revoked session did not show the login recovery message: ${expiryMessage}`);
    console.log('PASS revoked session returns to sign-in with an announced recovery message');
    const oldLogin = await page.evaluate(async ({email, password}) => fetch('/studio-api/auth/login', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({email, password}),
    }).then(r => r.status), {email: accountEmail, password: accountPassword});
    if (oldLogin !== 401) throw Error(`old password remained valid after recovery: ${oldLogin}`);
    await page.locator('#studio-auth input[name=email]').fill(accountEmail);
    await page.locator('#studio-auth input[name=password]').fill(newPassword);
    await page.getByRole('button', {name: 'Sign in'}).click();
    await page.locator('.studio-nav').waitFor({state: 'visible'});
    console.log('PASS captured-email browser recovery, old-password rejection and other-session revocation');

    if (errors.length) throw Error('browser page errors: ' + errors.join(' | '));
  } finally {
    if (created && context && cleanupPassword) {
      const cleanupPage = await context.newPage();
      try {
        await cleanupPage.goto(base + '/#bo6-wardrobe');
        const result = await cleanupPage.evaluate(async ({email, password}) => {
          const login = await fetch('/studio-api/auth/login', {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({email, password}),
          });
          if (login.status !== 200) return {status: login.status};
          const csrf = await fetch('/studio-api/auth/csrf', {method: 'POST', headers: {'X-CSRF-Bootstrap': '1'}}).then(r => r.json());
          const deleted = await fetch('/studio-api/auth/account', {method: 'DELETE', headers: {
            'Content-Type': 'application/json', 'X-CSRF-Token': csrf.csrf_token,
          }, body: JSON.stringify({password, confirmation: 'DELETE'})});
          return {status: deleted.status};
        }, {email: accountEmail, password: cleanupPassword});
        if (result.status !== 204) throw Error(`disposable browser-account cleanup returned ${result.status}`);
        console.log('PASS disposable browser account and owned records removed');
      } finally {
        await cleanupPage.close();
      }
    }
    await secondaryContext?.close();
    await context?.close();
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
