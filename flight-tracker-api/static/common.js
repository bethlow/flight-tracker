const $ = id => document.getElementById(id);
const esc = s => Object.assign(document.createElement('i'), {textContent: s ?? ''}).innerHTML;

// Shared across index.html and register.html. index.html sets window.onUnauthorized
// (to sign the user out) after defining it; register.html never has a token to expire.
window.onUnauthorized = () => {};

async function api(path, opts = {}) {
  const token = localStorage.getItem('token');
  const r = await fetch('/api' + path, {...opts, headers: {...(opts.body && !(opts.body instanceof FormData) ? {'Content-Type': 'application/json'} : {}),
    ...(token ? {Authorization: 'Bearer ' + token} : {})}});
  if (r.status === 401 && token) { window.onUnauthorized(); throw new Error('Please sign in again'); }
  if (!r.ok) {
    const e = await r.json().catch(() => ({}));
    const msg = typeof e.detail === 'string' ? e.detail
      : Array.isArray(e.detail) ? e.detail.map(d => d.msg).join('; ')
      : 'Something went wrong (' + r.status + ')';
    throw new Error(msg);
  }
  return r.status === 204 ? null : r.json();
}
const post = (p, b) => api(p, {method: 'POST', body: JSON.stringify(b)});
