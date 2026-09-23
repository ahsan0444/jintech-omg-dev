// Session liveness check shared by auth.mjs, design-check.mjs, snapshot.mjs.
// `req` is any Playwright request context (BrowserContext.request or APIRequestContext).
// NEVER logs cookie values.

export function authProbe(repo) {
  const auth = repo.auth || {};
  return {
    probePath: auth.auth_probe_path || '/jobs',
    expirySignal: (auth.storage_state && auth.storage_state.expiry_signal_redirect) || '/loginsso',
  };
}

/** True when a response is the SSO bounce (3xx to the expiry signal). */
export function isExpiredResponse(res, expirySignal) {
  const status = res.status();
  const location = res.headers()['location'] || '';
  return status >= 300 && status < 400 && location.includes(expirySignal);
}

/** Probe the auth path without following redirects. Returns { expired, status, probePath }. */
export async function checkSession(req, repo) {
  const { probePath, expirySignal } = authProbe(repo);
  const res = await req.get(new URL(probePath, repo.env.BASE_URL).toString(), { maxRedirects: 0 });
  return { expired: isExpiredResponse(res, expirySignal), status: res.status(), probePath };
}
