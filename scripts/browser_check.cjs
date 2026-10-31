const {chromium} = require(process.env.DRESSME_PLAYWRIGHT_PATH || 'playwright');
const path = require('path');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');

const root = path.resolve(__dirname, '..');
const screenshotDir = process.env.DRESSME_SCREENSHOT_DIR || path.join(os.tmpdir(), 'dressme-integration-screenshots');
const responsiveScreenshotDir = path.join(screenshotDir, 'responsive-after');
const base = (process.env.DRESSME_BASE_URL || 'http://127.0.0.1:8002').replace(/\/$/, '');
const mailCaptureDir = process.env.DRESSME_CAPTURE_PATH;
fs.mkdirSync(screenshotDir, {recursive: true});
fs.mkdirSync(responsiveScreenshotDir, {recursive: true});

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

const RESPONSIVE_VIEWPORTS = [
  {width: 320, height: 780, name: '320px'}, {width: 360, height: 800, name: '360px'},
  {width: 390, height: 844, name: '390px'}, {width: 768, height: 900, name: '768px'},
  {width: 1024, height: 900, name: '1024px'}, {width: 1440, height: 900, name: '1440px'},
  {width: 568, height: 320, name: 'short-landscape'},
];

async function settleVisuals(page) {
  await page.evaluate(async () => {
    if (document.fonts?.ready) await document.fonts.ready;
    await Promise.all([...document.images].map(image => image.decode().catch(() => {})));
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
}

async function auditResponsiveLayout(page, label) {
  await settleVisuals(page);
  const layout = await page.evaluate(() => {
    const visible = element => {
      if (!element.getClientRects().length) return false;
      for (let current = element; current && current !== document.documentElement; current = current.parentElement) {
        const style = getComputedStyle(current);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
      }
      return true;
    };
    const interactive = [...document.querySelectorAll('a[href],button,input:not([type="hidden"]),select,textarea,summary,[tabindex]:not([tabindex="-1"])')]
      .filter(element => visible(element) && !(element.matches('input[type="file"]')
        && (getComputedStyle(element).opacity === '0' || element.classList.contains('file-input'))));
    const outside = interactive.map(element => {
      const rect = element.getBoundingClientRect();
      return {name: element.getAttribute('aria-label') || element.innerText || element.name || element.tagName,
        left: Math.round(rect.left), right: Math.round(rect.right)};
    }).filter(rect => rect.left < -1 || rect.right > innerWidth + 1);
    const clipped = interactive.map(element => {
      const rect = element.getBoundingClientRect();
      for (let parent = element.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
        const style = getComputedStyle(parent);
        if (!['hidden', 'clip'].includes(style.overflowX)) continue;
        const bounds = parent.getBoundingClientRect();
        if (rect.left < bounds.left - 1 || rect.right > bounds.right + 1) {
          return {name: element.getAttribute('aria-label') || element.innerText || element.name || element.tagName,
            ancestor: parent.className || parent.id || parent.tagName};
        }
      }
      return null;
    }).filter(Boolean);
    return {width: innerWidth, height: innerHeight, scrollWidth: document.documentElement.scrollWidth,
      bodyWidth: document.body.scrollWidth, outside, clipped};
  });
  if (layout.scrollWidth > layout.width + 1 || layout.bodyWidth > layout.width + 1 || layout.outside.length || layout.clipped.length) {
    throw Error(`${label} responsive audit failed: ${JSON.stringify(layout)}`);
  }
  return layout;
}

async function assertHitTarget(page, locator, label) {
  const result = await locator.evaluate(element => {
    const rect = element.getBoundingClientRect();
    const x = rect.left + rect.width / 2, y = rect.top + rect.height / 2;
    const hit = document.elementFromPoint(x, y);
    return {width: rect.width, height: rect.height, hit: !!hit && (element === hit || element.contains(hit))};
  });
  if (result.width < 40 || result.height < 40 || !result.hit) throw Error(`${label} has an undersized or obstructed target: ${JSON.stringify(result)}`);
}

async function assertVisibleFocus(locator, label) {
  const result = await locator.evaluate(element => {
    const style = getComputedStyle(element);
    return {active: element === document.activeElement, outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth};
  });
  if (!result.active || result.outlineStyle === 'none' || parseFloat(result.outlineWidth) < 2) throw Error(`${label} has no visible keyboard focus: ${JSON.stringify(result)}`);
}

async function verifyHeaderNavigation(page, screenshotDir) {
  const expected = [['Style Engine', 3], ['Shopping', 2], ['My Studio', 5]];
  for (const viewport of RESPONSIVE_VIEWPORTS) {
    await page.setViewportSize({width: viewport.width, height: viewport.height});
    const layout = await auditResponsiveLayout(page, `public header at ${viewport.name}`);
    const mobile = viewport.width <= 860;
    const toggle = page.locator('#menuToggle');
    const nav = page.locator('#menu');
    if (mobile) {
      if (!await toggle.isVisible() || !await nav.evaluate(element => element.hidden)) throw Error(`mobile menu state is incorrect at ${viewport.name}`);
      await assertHitTarget(page, toggle, `Menu toggle at ${viewport.name}`);
      await toggle.click();
      if (await toggle.getAttribute('aria-expanded') !== 'true' || !await nav.isVisible()) throw Error(`Menu did not open at ${viewport.name}`);
    } else if (await toggle.isVisible() || !await nav.isVisible()) throw Error(`desktop menu state is incorrect at ${viewport.name}`);

    for (const [label, itemCount] of expected) {
      const button = nav.getByRole('button', {name: label, exact: true});
      await button.scrollIntoViewIfNeeded();
      await button.click();
      if (await button.getAttribute('aria-expanded') !== 'true') throw Error(`${label} group did not announce open at ${viewport.name}`);
      const panelId = await button.getAttribute('aria-controls');
      await page.waitForFunction(id => {
        const panel = document.getElementById(id);
        const style = panel && getComputedStyle(panel);
        return style?.visibility === 'visible' && Number(style.opacity) >= 0.99;
      }, panelId);
      const group = button.locator('..');
      const items = group.locator('.mi');
      if (await items.count() !== itemCount) throw Error(`${label} has the wrong number of destinations at ${viewport.name}`);
      for (let index = 0; index < itemCount; index++) {
        const item = items.nth(index);
        await item.evaluate(element => element.scrollIntoView({block: 'center', inline: 'nearest'}));
        await assertHitTarget(page, item, `${label} destination ${index + 1} at ${viewport.name}`);
        const bounds = await item.evaluate(element => {
          const rect = element.getBoundingClientRect();
          return {left: rect.left, right: rect.right, width: rect.width};
        });
        if (bounds.left < -1 || bounds.right > viewport.width + 1 || bounds.width < 40) throw Error(`${label} destination clipped at ${viewport.name}: ${JSON.stringify(bounds)}`);
      }
      if (mobile) await button.click();
      else {
        await page.keyboard.press('Escape');
        if (await button.getAttribute('aria-expanded') !== 'false' || !await button.evaluate(element => element === document.activeElement)) throw Error(`${label} Escape did not close and return focus at ${viewport.name}`);
        await assertVisibleFocus(button, `${label} group button`);
      }
    }

    if (mobile) {
      if (viewport.width === 390) {
        const studioGroup = nav.locator('.group-toggle').nth(2);
        if (await nav.evaluate(element => element.hidden)) await toggle.click();
        await page.evaluate(() => window.scrollTo(0, 0));
        await studioGroup.evaluate(element => element.click());
        await page.screenshot({path: path.join(screenshotDir, 'public-menu-open-390-viewport.png')});
        await page.screenshot({path: path.join(screenshotDir, 'public-menu-open-390-full.png'), fullPage: true});
      }
      if (await nav.evaluate(element => element.hidden)) await toggle.click();
      await nav.getByRole('button', {name: 'Style Engine', exact: true}).focus();
      await page.keyboard.press('Enter');
      if (await nav.getByRole('button', {name: 'Style Engine', exact: true}).getAttribute('aria-expanded') !== 'true') throw Error(`keyboard could not open menu group at ${viewport.name}`);
      await page.keyboard.press('Escape');
      const styleButton = nav.getByRole('button', {name: 'Style Engine', exact: true});
      if (await styleButton.getAttribute('aria-expanded') !== 'false' || !await styleButton.evaluate(element => element === document.activeElement)) throw Error(`first Escape did not close group and return focus at ${viewport.name}`);
      await assertVisibleFocus(styleButton, 'Mobile menu group button');
      await page.keyboard.press('Escape');
      if (!await nav.evaluate(element => element.hidden) || !await toggle.evaluate(element => element === document.activeElement)) throw Error(`second Escape did not close menu and return focus at ${viewport.name}`);
      await assertVisibleFocus(toggle, 'Mobile menu toggle');
      await toggle.click();
      await page.locator('.hero h1').click();
      if (!await nav.evaluate(element => element.hidden)) throw Error(`outside click did not close the mobile menu at ${viewport.name}`);
    }
    if (viewport.width === 390) {
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({path: path.join(screenshotDir, 'public-390-full.png'), fullPage: true});
      await page.screenshot({path: path.join(screenshotDir, 'public-390-viewport.png')});
    }
    console.log(`PASS public header groups, touch targets, bounds and ${mobile ? 'mobile disclosure' : 'desktop navigation'} at ${viewport.name}`);
    await auditResponsiveLayout(page, `public content at ${viewport.name}`);
  }

  await page.setViewportSize({width: 390, height: 844});
  const toggle = page.locator('#menuToggle');
  const nav = page.locator('#menu');
  const destinations = ['ootd', 'score', 'comp', 'sim', 'wardrobe', 'bo6-wardrobe', 'bo6-add', 'bo7-avatar', 'bo7-tryon', 'bo7-history'];
  for (const id of destinations) {
    await toggle.click();
    const item = nav.locator(`.mi[data-t="${id}"]`);
    const groupIndex = ['ootd', 'score', 'comp'].includes(id) ? 0 : ['sim', 'wardrobe'].includes(id) ? 1 : 2;
    await nav.locator('.group-toggle').nth(groupIndex).click();
    await item.evaluate(element => element.scrollIntoView({block: 'center', inline: 'nearest'}));
    await item.click();
    if (await page.evaluate(() => location.hash.slice(1)) !== id || !await page.locator(`main section#${id}`).isVisible()) throw Error(`navigation destination ${id} did not render`);
    if (!await nav.evaluate(element => element.hidden)) throw Error(`destination ${id} left mobile navigation open`);
  }
  await page.evaluate(() => window.go('ootd'));
  await page.setViewportSize({width: 390, height: 844});
  await toggle.click();
  await nav.getByRole('button', {name: 'Style Engine', exact: true}).click();
  await page.setViewportSize({width: 1440, height: 900});
  await page.waitForFunction(() => document.querySelector('#menuToggle').getAttribute('aria-expanded') === 'false'
    && [...document.querySelectorAll('.group-toggle')].every(button => button.getAttribute('aria-expanded') === 'false'));
  if (!await nav.isVisible() || await toggle.isVisible()) throw Error('mobile-to-desktop resize did not reset the menu state');
  await page.setViewportSize({width: 390, height: 844});
  if (!await nav.evaluate(element => element.hidden) || await toggle.getAttribute('aria-expanded') !== 'false') throw Error('desktop-to-mobile resize did not reset the menu state');
  await page.evaluate(() => window.go('ootd'));
  console.log('PASS all public and Studio destinations, resize reset and click-outside behavior');
}

async function verifyStudioResponsive(page, id, screenshotDir) {
  const title = ({'bo6-wardrobe': 'My Wardrobe', 'bo6-add': 'Add Garment', 'bo7-avatar': 'My Avatar',
    'bo7-tryon': 'Virtual Try-On', 'bo7-history': 'Try-On History'})[id];
  for (const viewport of RESPONSIVE_VIEWPORTS) {
    await page.setViewportSize({width: viewport.width, height: viewport.height});
    await auditResponsiveLayout(page, `${title} at ${viewport.name}`);
    const compact = viewport.width <= 760;
    if (compact) {
      const disclosure = page.locator('.studio-nav-mobile');
      if (!await disclosure.isVisible() || await page.locator('.studio-nav').isVisible()) throw Error(`compact Studio navigation is incorrect on ${title} at ${viewport.name}`);
      const summary = disclosure.locator('summary');
      if (!(await summary.innerText()).includes(title)) throw Error(`current Studio section is not identified on ${title} at ${viewport.name}`);
      if (id === 'bo6-wardrobe') {
        await summary.focus();
        await page.keyboard.press('Enter');
        if (!await disclosure.evaluate(element => element.open)) throw Error(`Studio disclosure did not open by keyboard at ${viewport.name}`);
        await assertVisibleFocus(summary, 'Studio section summary');
        const links = disclosure.locator('nav a');
        if (await links.count() !== 5 || await disclosure.locator(`nav a[aria-current="page"][href="#${id}"]`).count() !== 1) throw Error(`Studio disclosure did not contain all five destinations at ${viewport.name}`);
        for (let index = 0; index < await links.count(); index++) {
          const link = links.nth(index);
          await link.evaluate(element => element.scrollIntoView({block: 'center', inline: 'nearest'}));
          await assertHitTarget(page, link, `${title} navigation item at ${viewport.name}`);
        }
        if (await disclosure.locator('a[aria-current="page"]').getAttribute('href') !== `#${id}`) throw Error(`current section is not announced in compact navigation at ${viewport.name}`);
        await summary.focus();
        await page.keyboard.press('Enter');
        if (await disclosure.evaluate(element => element.open)) throw Error(`Studio disclosure did not close by keyboard at ${viewport.name}`);
      }
    } else if (!await page.locator('.studio-nav').isVisible() || await page.locator('.studio-nav-mobile').isVisible()) {
      throw Error(`desktop Studio navigation is incorrect on ${title} at ${viewport.name}`);
    }
    const email = page.locator('.studio-account span');
    if (await email.count()) {
      const fit = await email.evaluate(element => {
        const rect = element.getBoundingClientRect();
        return {left: rect.left, right: rect.right, scrollWidth: element.scrollWidth, clientWidth: element.clientWidth,
          overflowWrap: getComputedStyle(element).overflowWrap};
      });
      if (fit.left < -1 || fit.right > viewport.width + 1 || fit.scrollWidth > fit.clientWidth + 1) throw Error(`account email does not fit on ${title} at ${viewport.name}: ${JSON.stringify(fit)}`);
    }
    if (viewport.width === 390) {
      await page.evaluate(() => window.scrollTo(0, 0));
      await settleVisuals(page);
      await page.screenshot({path: path.join(screenshotDir, `studio-${id}-390-full.png`), fullPage: true});
      await page.screenshot({path: path.join(screenshotDir, `studio-${id}-390-viewport.png`)});
    }
  }
  console.log(`PASS ${title} layout at 320, 360, 390, 768, 1024, 1440 CSS pixels and 568×320 landscape (browser emulation)`);
}

async function verifyReviewColumns(page, label, expectedColumns) {
  const result = await page.evaluate(() => {
    const shell = document.querySelector('.studio-review-shell');
    const body = document.querySelector('.studio-body');
    const columns = getComputedStyle(shell).gridTemplateColumns.trim().split(/\s+/).length;
    const previewName = document.querySelector('[data-upload-preview="garment"] strong');
    const description = document.querySelector('#studio-confirm textarea[name=description]');
    const suggestions = document.querySelector('.studio-review-photo-panel');
    const fields = document.querySelector('.studio-review-fields');
    const suggestionsRect = suggestions?.getBoundingClientRect();
    const fieldsRect = fields?.getBoundingClientRect();
    return {columns, containerWidth: body.clientWidth,
      filename: previewName ? {scrollWidth: previewName.scrollWidth, clientWidth: previewName.clientWidth, wrap: getComputedStyle(previewName).overflowWrap} : null,
      duplicatePreviewCount: document.querySelectorAll('.studio-review-image').length,
      descriptionWidth: description?.getBoundingClientRect().width,
      reviewOrder: suggestionsRect && fieldsRect ? {suggestionsTop: suggestionsRect.top, fieldsTop: fieldsRect.top, sameColumn: Math.abs(suggestionsRect.left - fieldsRect.left) < 2} : null};
  });
  if (result.columns !== expectedColumns) throw Error(`${label} Add Garment grid has ${result.columns} columns; expected ${expectedColumns}: ${JSON.stringify(result)}`);
  if (result.filename && result.filename.scrollWidth > result.filename.clientWidth + 1) throw Error(`${label} long filename is clipped: ${JSON.stringify(result.filename)}`);
  if (result.duplicatePreviewCount) throw Error(`${label} review panel repeats the upload preview`);
  if (result.descriptionWidth && result.descriptionWidth < 190) throw Error(`${label} description field is too narrow: ${JSON.stringify(result)}`);
  if (result.reviewOrder && (!result.reviewOrder.sameColumn || result.reviewOrder.fieldsTop < result.reviewOrder.suggestionsTop)) throw Error(`${label} review content is nested in cramped columns: ${JSON.stringify(result.reviewOrder)}`);
  return result;
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
    const localPart = ('browser' + crypto.randomUUID().replaceAll('-', '')).padEnd(64, 'x').slice(0, 64);
    accountEmail = `${localPart}@${'a'.repeat(58)}.${'b'.repeat(58)}.${'c'.repeat(58)}.invalid`;
    accountPassword = 'Browser-check-' + crypto.randomBytes(12).toString('hex');
    cleanupPassword = accountPassword;

    await page.goto(base + '/#ootd');
    await verifyHeaderNavigation(page, responsiveScreenshotDir);
    await page.setViewportSize({width: 1440, height: 900});
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
    if (await page.locator('main>.hero').isVisible()) throw Error('repeated public hero remains visible on the authentication route');
    for (const viewport of RESPONSIVE_VIEWPORTS) {
      await page.setViewportSize({width: viewport.width, height: viewport.height});
      await auditResponsiveLayout(page, `login at ${viewport.name}`);
      if (!await page.locator('#studio-auth').isVisible()) throw Error(`login form was not available at ${viewport.name}`);
      if (viewport.width === 390) {
        await page.evaluate(() => window.scrollTo(0, 0));
        await settleVisuals(page);
        await page.screenshot({path: path.join(responsiveScreenshotDir, 'auth-login-390-full.png'), fullPage: true});
        await page.screenshot({path: path.join(responsiveScreenshotDir, 'auth-login-390-viewport.png')});
      }
    }
    await page.getByRole('button', {name: 'Forgot password?'}).click();
    await page.locator('#studio-recovery-request').waitFor({state: 'visible'});
    for (const viewport of RESPONSIVE_VIEWPORTS) {
      await page.setViewportSize({width: viewport.width, height: viewport.height});
      await auditResponsiveLayout(page, `recovery request at ${viewport.name}`);
      if (!await page.locator('#studio-recovery-request').isVisible()) throw Error(`recovery request form missing at ${viewport.name}`);
      if (viewport.width === 390) {
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.screenshot({path: path.join(responsiveScreenshotDir, 'auth-recovery-request-390-full.png'), fullPage: true});
      }
    }
    await page.locator('#studio-recovery-request input[name=email]').fill(accountEmail);
    await page.getByRole('button', {name: 'Send recovery code'}).click();
    await page.getByRole('heading', {name: 'Check your email'}).waitFor();
    await page.getByRole('button', {name: 'Enter recovery code'}).click();
    await page.locator('#studio-recovery-complete').waitFor({state: 'visible'});
    for (const viewport of RESPONSIVE_VIEWPORTS) {
      await page.setViewportSize({width: viewport.width, height: viewport.height});
      await auditResponsiveLayout(page, `recovery code at ${viewport.name}`);
      if (!await page.locator('#studio-recovery-complete').isVisible()) throw Error(`recovery code form missing at ${viewport.name}`);
      if (viewport.width === 390) {
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.screenshot({path: path.join(responsiveScreenshotDir, 'auth-recovery-code-390-full.png'), fullPage: true});
      }
    }
    await page.getByRole('button', {name: 'Request another code'}).click();
    await page.getByRole('button', {name: 'Back to sign in'}).click();
    await page.locator('#studio-auth[data-mode="login"]').waitFor({state: 'visible'});
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
    await page.locator('#studio-auth input[name=email]').fill(accountEmail);
    for (const viewport of RESPONSIVE_VIEWPORTS) {
      await page.setViewportSize({width: viewport.width, height: viewport.height});
      await auditResponsiveLayout(page, `registration at ${viewport.name}`);
      if (!await page.locator('#studio-auth[data-mode="register"]').isVisible()) throw Error(`registration form missing at ${viewport.name}`);
      if (viewport.width === 390) {
        await page.evaluate(() => window.scrollTo(0, 0));
        await page.screenshot({path: path.join(responsiveScreenshotDir, 'auth-registration-long-email-390-full.png'), fullPage: true});
      }
    }
    console.log('PASS invalid credential feedback and keyboard-driven registration focus');
    await page.setViewportSize({width: 1440, height: 900});
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
      await verifyStudioResponsive(page, id, responsiveScreenshotDir);
    }
    console.log('PASS protected Studio routing, reload, browser Back and unique IDs');
    await page.goto(base + '/#bo6-wardrobe');
    await page.reload();
    await page.locator('#studio-search').waitFor({state: 'visible'});
    await page.setViewportSize({width: 1440, height: 900});
    await page.locator('.studio-nav a[href="#bo6-add"]').click();
    await page.locator('#studio-upload').waitFor({state: 'visible'});
    await page.goBack();
    await page.locator('#studio-search').waitFor({state: 'visible'});

    await page.goto(base + '/#bo6-add');
    await page.locator('#studio-upload').waitFor({state: 'visible'});
    await verifyStudioResponsive(page, 'bo6-add', responsiveScreenshotDir);
    const fixture = path.join(root, 'data/img/P01133864.jpg');
    await page.locator('#studio-upload input[type=file]').setInputFiles({name: 'not-an-image.txt', mimeType: 'text/plain', buffer: Buffer.from('not an image')});
    await page.waitForFunction(() => document.querySelector('[data-upload-status="garment"]')?.textContent.includes('Choose a JPEG, PNG or WebP image.'));
    if (!(await page.locator('.studio-status[role=alert]').innerText()).includes('Choose a JPEG')) throw Error('upload validation error was not announced as an alert');
    const fixtureBytes = fs.readFileSync(fixture);
    const longFilename = `spring-${'garment-photo-'.repeat(12)}.jpg`;
    await page.locator('#studio-upload input[type=file]').setInputFiles({name: longFilename, mimeType: 'image/jpeg', buffer: fixtureBytes});
    try { await page.getByAltText('Selected image preview').waitFor({state: 'visible', timeout: 7000}); }
    catch {
      const status = await page.locator('[data-upload-status="garment"]').innerText().catch(() => '(no upload status)');
      const selected = await page.locator('#studio-upload input[type=file]').evaluate(input => ({name: input.files?.[0]?.name, size: input.files?.[0]?.size, type: input.files?.[0]?.type}));
      throw Error(`garment preview did not render; input=${JSON.stringify(selected)} status=${status}; pageErrors=${errors.join(' | ')}`);
    }
    const previewName = await page.locator('[data-upload-preview="garment"] strong').innerText();
    if (previewName !== longFilename) throw Error('long garment filename was not displayed in full');
    for (const viewport of RESPONSIVE_VIEWPORTS) {
      await page.setViewportSize({width: viewport.width, height: viewport.height});
      await auditResponsiveLayout(page, `Add Garment before analysis at ${viewport.name}`);
      const bodyWidth = await page.locator('.studio-body').evaluate(element => element.clientWidth);
      const grid = await verifyReviewColumns(page, `Add Garment before analysis at ${viewport.name}`, bodyWidth >= 760 ? 2 : 1);
      if (grid.filename?.wrap !== 'anywhere' && viewport.width <= 420) throw Error(`long garment filename is not configured to wrap at ${viewport.name}`);
    }
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
    await page.setViewportSize({width: 1440, height: 900});
    console.log('PASS upload format error announcement, drag-and-drop preview and keyboard file removal');
    await page.getByRole('button', {name: '2. Analyze photo'}).click();
    await page.locator('#studio-confirm').waitFor({state: 'visible', timeout: 120000});
    for (const viewport of RESPONSIVE_VIEWPORTS) {
      await page.setViewportSize({width: viewport.width, height: viewport.height});
      await auditResponsiveLayout(page, `Add Garment after analysis at ${viewport.name}`);
      const bodyWidth = await page.locator('.studio-body').evaluate(element => element.clientWidth);
      await verifyReviewColumns(page, `Add Garment after analysis at ${viewport.name}`, bodyWidth >= 760 ? 2 : 1);
      if (viewport.width === 390) {
        await page.evaluate(() => window.scrollTo(0, 0));
        await settleVisuals(page);
        await page.screenshot({path: path.join(responsiveScreenshotDir, 'bo6-review-390-full.png'), fullPage: true});
        await page.screenshot({path: path.join(responsiveScreenshotDir, 'bo6-review-390-viewport.png')});
      }
    }
    await page.setViewportSize({width: 1440, height: 900});
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
    await page.evaluate(() => window.scrollTo(0, 0));
    await settleVisuals(page);
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
    await verifyStudioResponsive(page, 'bo6-wardrobe', responsiveScreenshotDir);
    console.log('PASS real BO6 image analyze → suggestion confirmation → automatic description → save → detail edit → reload');

    await page.goto(base + '/#bo7-tryon');
    await page.locator('#studio-person').waitFor({state: 'visible'});
    await page.getByText(/Submission is disabled because the worker is unavailable/).waitFor();
    const liveSubmit = page.locator('[data-action="submit-mock"]');
    if (await liveSubmit.count() && await liveSubmit.isEnabled()) throw Error('live unavailable worker left submission enabled');
    await verifyStudioResponsive(page, 'bo7-tryon', responsiveScreenshotDir);
    await page.goto(base + '/#bo7-avatar');
    await page.getByText(/Avaturn is not configured for this origin/).waitFor();
    await verifyStudioResponsive(page, 'bo7-avatar', responsiveScreenshotDir);
    await page.goto(base + '/#bo7-history');
    await page.locator('#bo7-history').waitFor({state: 'visible'});
    await verifyStudioResponsive(page, 'bo7-history', responsiveScreenshotDir);
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
    await page.setViewportSize({width: 1440, height: 900});
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
