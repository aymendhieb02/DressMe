import {state, esc, request, message} from './core.js';

function passwordField(name, label, autocomplete, minimum = '') {
  return `<label>${label}<span class="studio-password"><input name="${name}" type="password" autocomplete="${autocomplete}" ${minimum} required><button type="button" class="btn ghost" data-auth-toggle="${name}" aria-label="Show ${label.toLowerCase()}">Show</button></span></label>`;
}

export function authForm() {
  const view = state.authView;
  const email = esc(state.authEmail);
  if (view === 'register') return `<section class="studio-auth-card" aria-labelledby="studio-auth-title"><p class="studio-eyebrow">Your private wardrobe</p><h2 id="studio-auth-title" tabindex="-1">Create your account</h2><p class="studio-muted">Your garments, photos and try-on history stay private to your account.</p><form id="studio-auth" class="studio-form" data-mode="register"><label>Email<input name="email" type="email" autocomplete="email" value="${email}" required maxlength="254"></label>${passwordField('password', 'Password', 'new-password', 'minlength="12" maxlength="128"')}<button class="btn" type="submit">Create account</button></form><p>Already have an account? <button class="studio-link" data-auth-view="login">Sign in</button></p></section>`;
  if (view === 'forgot') return `<section class="studio-auth-card" aria-labelledby="studio-auth-title"><p class="studio-eyebrow">Account recovery</p><h2 id="studio-auth-title" tabindex="-1">Forgot your password?</h2><p class="studio-muted">Enter your account email. If it is registered, we’ll send a short-lived code.</p><form id="studio-recovery-request" class="studio-form"><label>Email<input name="email" type="email" autocomplete="email" value="${email}" required maxlength="254"></label><button class="btn" type="submit">Send recovery code</button></form><button class="studio-link" data-auth-view="login">Back to sign in</button></section>`;
  if (view === 'reset') return `<section class="studio-auth-card" aria-labelledby="studio-auth-title"><p class="studio-eyebrow">Account recovery</p><h2 id="studio-auth-title" tabindex="-1">Enter your recovery code</h2><p class="studio-muted">Use the eight-digit code from your recovery email. Codes expire and work once.</p><form id="studio-recovery-complete" class="studio-form"><label>Email<input name="email" type="email" autocomplete="email" value="${email}" required maxlength="254"></label><label>Eight-digit code<input name="code" inputmode="numeric" pattern="[0-9]{8}" autocomplete="one-time-code" required maxlength="8"></label>${passwordField('new_password', 'New password', 'new-password', 'minlength="12" maxlength="128"')}<label>Confirm new password<input name="confirm_password" type="password" autocomplete="new-password" minlength="12" maxlength="128" required></label><button class="btn" type="submit">Reset password</button></form><button class="studio-link" data-auth-view="forgot">Request another code</button></section>`;
  if (view === 'recovery-sent') return `<section class="studio-auth-card" aria-labelledby="studio-auth-title"><p class="studio-eyebrow">Account recovery</p><h2 id="studio-auth-title" tabindex="-1">Check your email</h2><p class="studio-muted">If an account exists for that email, recovery instructions have been sent. The code expires shortly.</p><div class="studio-actions"><button class="btn" data-auth-view="reset">Enter recovery code</button><button class="btn ghost" data-auth-view="login">Back to sign in</button></div></section>`;
  return `<section class="studio-auth-card" aria-labelledby="studio-auth-title"><p class="studio-eyebrow">DressMe Studio</p><h2 id="studio-auth-title" tabindex="-1">Sign in to your Studio</h2><p class="studio-muted">Manage private garments, photos, avatars and try-on jobs. The original Style Engine and Shopping pages remain public.</p><form id="studio-auth" class="studio-form" data-mode="login"><label>Email<input name="email" type="email" autocomplete="username" value="${email}" required maxlength="254"></label>${passwordField('password', 'Password', 'current-password', 'maxlength="128"')}<button class="btn" type="submit">Sign in</button></form><div class="studio-actions"><button class="studio-link" data-auth-view="register">Create an account</button><button class="studio-link" data-auth-view="forgot">Forgot password?</button></div><a class="studio-link" href="#ootd">Return to the public Style Engine</a></section>`;
}

export function handleAuthView(action, render) {
  state.authView = action;
  render();
  document.querySelector('.studio-auth-card form input')?.focus();
}

export async function handleAuthSubmit(form, render) {
  const data = Object.fromEntries(new FormData(form));
  if (form.id === 'studio-auth') {
    state.authEmail = data.email;
    const mode = form.dataset.mode;
    const result = await request('/auth/' + mode, {method: 'POST', body: {email: data.email, password: data.password}});
    state.user = result.user;
    state.csrf = result.csrf_token;
    state.authView = 'login';
    render();
    message('Signed in.');
    return;
  }
  if (form.id === 'studio-recovery-request') {
    state.authEmail = data.email;
    await request('/auth/password-reset/request', {method: 'POST', body: {email: data.email}});
    state.authView = 'recovery-sent';
    render();
    message('If an account exists for that email, recovery instructions have been sent.');
    return;
  }
  if (form.id === 'studio-recovery-complete') {
    if (data.new_password !== data.confirm_password) throw new Error('The new passwords do not match.');
    state.authEmail = data.email;
    await request('/auth/password-reset/complete', {method: 'POST', body: {
      email: data.email, code: data.code, new_password: data.new_password,
    }});
    state.authView = 'login';
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
