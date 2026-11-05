import {state, esc, request, message} from './core.js?v=bo6g2l1';

function passwordField(name, label, autocomplete, minimum = '') {
  return `<label>${label}<span class="studio-password"><input name="${name}" type="password" autocomplete="${autocomplete}" ${minimum} required><button type="button" class="btn ghost" data-auth-toggle="${name}" aria-label="Show ${label.toLowerCase()}">Show</button></span></label>`;
}
const card = (eyebrow, title, intro, inner) => `<section class="studio-auth-card" aria-labelledby="studio-auth-title"><p class="studio-eyebrow">${eyebrow}</p><h2 id="studio-auth-title" tabindex="-1">${title}</h2><p class="studio-muted">${intro}</p>${inner}</section>`;
const emailInput = email => `<label>Email<input name="email" type="email" autocomplete="email" value="${email}" required maxlength="254"></label>`;
const back = '<button class="studio-link" data-auth-view="login">Back to sign in</button>';
const genderInput = '<label>Genre des tenues<select name="gender" required><option value="women">Femme</option><option value="men">Homme</option></select><small>Utilisé par défaut dans le chat. Une demande explicite reste prioritaire.</small></label>';

export function authForm() {
  const email = esc(state.authEmail);
  const localCapture = state.publicConfig?.recovery_delivery_mode === 'capture';
  const deliveryNote = localCapture
    ? '<p class="studio-muted">This local preview does not send email. Recovery messages are saved in the local developer mailbox.</p>' : '';
  if (state.authView === 'register') return card('Join DressMe', 'Create your account', 'Your daily edit, style tools, and private wardrobe in one place.', `<form id="studio-auth" class="studio-form" data-mode="register">${emailInput(email)}${genderInput}${passwordField('password', 'Password', 'new-password', 'minlength="12" maxlength="128"')}<button class="btn" type="submit">Create account</button></form><p>Already have an account? ${back}</p>`);
  if (state.authView === 'forgot') return card('Account recovery', 'Forgot your password?', 'Enter your account email. If it exists, you’ll receive recovery instructions.', `${deliveryNote}<form id="studio-recovery-request" class="studio-form">${emailInput(email)}<button class="btn" type="submit">Send recovery code</button></form>${back}`);
  if (state.authView === 'recovery-sent') return card('Account recovery', localCapture ? 'Check the local mailbox' : 'Check your email', localCapture ? 'If an account exists for that email, its recovery message is available in the local mailbox below.' : 'If an account exists for that email, you’ll receive recovery instructions. The code expires shortly.', `${deliveryNote}<p class="studio-muted">The code expires shortly. You can request another after one minute.</p><div class="studio-actions">${localCapture ? '<button class="btn ghost" data-action="show-local-recovery">Show local recovery code</button>' : ''}<button class="btn" data-auth-view="reset">Enter recovery code</button><button class="btn ghost" data-auth-view="forgot">Resend code</button>${back}</div>`);
  if (state.authView === 'reset') return card('Account recovery', 'Enter your recovery code', 'Use the eight-digit code from your recovery email.', `<form id="studio-recovery-verify" class="studio-form">${emailInput(email)}<label>Eight-digit code<input name="code" inputmode="numeric" pattern="[0-9]{8}" autocomplete="one-time-code" required maxlength="8"></label><button class="btn" type="submit">Verify code</button></form><button class="studio-link" data-auth-view="forgot">Request another code</button>`);
  if (state.authView === 'new-password') return card('Account recovery', 'Choose a new password', 'Your code is verified. Finish resetting your password.', `<form id="studio-recovery-complete" class="studio-form">${passwordField('new_password', 'New password', 'new-password', 'minlength="12" maxlength="128"')}${passwordField('confirm_password', 'Confirm new password', 'new-password', 'minlength="12" maxlength="128"')}<button class="btn" type="submit">Reset password</button></form><button class="studio-link" data-auth-view="reset">Back to code</button>`);
  if (state.authView === 'reset-success') return card('Account recovery', 'Password updated', 'You can now sign in with your new password.', `<div class="studio-actions">${back}</div>`);
  return card('Welcome to DressMe', 'Sign in to DressMe', 'Open your daily edit, style tools, and private wardrobe.', `<form id="studio-auth" class="studio-form" data-mode="login">${emailInput(email)}${passwordField('password', 'Password', 'current-password', 'maxlength="128"')}<button class="btn" type="submit">Sign in</button></form><div class="studio-actions"><button class="studio-link" data-auth-view="register">Create an account</button><button class="studio-link" data-auth-view="forgot">Forgot password?</button></div>`);
}

export function handleAuthView(action, render) {
  state.authView = action;
  render();
  document.querySelector('.studio-auth-card form input')?.focus();
}

export function safeDestination() {
  const raw = new URLSearchParams(location.search).get('next') || '/app#ootd';
  try {
    const url = new URL(raw, location.origin);
    const valid = ['ootd','score','comp','sim','wardrobe','assistant','reco','style','bubble','bo3','bo6-wardrobe','bo6-add','bo7-avatar','bo7-tryon','bo7-history'];
    return url.origin === location.origin && url.pathname === '/app' && (!url.hash || valid.includes(url.hash.slice(1))) ? url.pathname + url.hash : '/app#ootd';
  } catch { return '/app#ootd'; }
}

export async function handleAuthSubmit(form, render) {
  const data = Object.fromEntries(new FormData(form));
  if (form.id === 'studio-auth') {
    state.authEmail = data.email;
    const body = {email: data.email, password: data.password};
    if (form.dataset.mode === 'register') body.gender = data.gender;
    const result = await request('/auth/' + form.dataset.mode, {method: 'POST', body});
    state.user = result.user;
    state.csrf = result.csrf_token;
    location.replace(safeDestination());
    return;
  }
  if (form.id === 'studio-recovery-request') {
    state.authEmail = data.email;
    await request('/auth/password-reset/request', {method: 'POST', body: {email: data.email}});
    state.authView = 'recovery-sent';
    render();
    message('If an account exists for that email, you’ll receive recovery instructions.');
    return;
  }
  if (form.id === 'studio-recovery-verify') {
    state.authEmail = data.email;
    await request('/auth/password-reset/verify', {method: 'POST', body: {email: data.email, code: data.code}});
    state.recoveryCode = data.code;
    state.authView = 'new-password';
    render();
    document.querySelector('[name="new_password"]')?.focus();
    return;
  }
  if (form.id === 'studio-recovery-complete') {
    if (data.new_password !== data.confirm_password) throw new Error('The new passwords do not match.');
    await request('/auth/password-reset/complete', {method: 'POST', body: {
      email: state.authEmail, code: state.recoveryCode, new_password: data.new_password,
    }});
    state.recoveryCode = null;
    state.authView = 'reset-success';
    render();
    message('Password updated. Sign in with your new password.');
  }
}

export function handlePasswordVisibility(button) {
  const field = button.closest('label')?.querySelector('input');
  if (!field) return;
  const visible = field.type === 'password';
  field.type = visible ? 'text' : 'password';
  button.textContent = visible ? 'Hide' : 'Show';
  button.setAttribute('aria-label', `${visible ? 'Hide' : 'Show'} ${field.name.replaceAll('_', ' ')}`);
  field.focus();
}
