// HTTP readiness probe for the Agent OS verify harness.
//
// SSO readiness rule: the host 302-redirects ALL unauthenticated requests to the IdP.
// That redirect MEANS THE APP IS UP. So:
//   HEALTH_EXPECT="redirect:/loginsso"  => a 3xx whose Location contains "/loginsso" is HEALTHY.
//   HEALTH_EXPECT="status:200"          => exactly that status is HEALTHY.
// Connection-refused / 502 / 504 / timeout => NOT ready.
//
// MUST use redirect:'manual' so we can read the 302 Location instead of following it.

/**
 * Parse a HEALTH_EXPECT string into a matcher descriptor.
 * Supported: "redirect:/path", "status:NNN".
 */
export function parseExpect(expect) {
  const raw = (expect || '').trim();
  if (raw.startsWith('redirect:')) {
    return { kind: 'redirect', value: raw.slice('redirect:'.length).trim() };
  }
  if (raw.startsWith('status:')) {
    return { kind: 'status', value: parseInt(raw.slice('status:'.length).trim(), 10) };
  }
  // Default: treat as a status code if numeric, else unknown.
  const n = parseInt(raw, 10);
  if (!Number.isNaN(n)) return { kind: 'status', value: n };
  return { kind: 'unknown', value: raw };
}

/**
 * Probe a URL against an expectation.
 * Returns { ok, status, location, expect, observed, error }.
 * Never throws on network failure — returns ok:false with an error string.
 */
export async function probe(url, expect, { timeoutMs = 10000 } = {}) {
  const matcher = parseExpect(expect);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  let status = null;
  let location = null;

  try {
    const res = await fetch(url, {
      method: 'GET',
      redirect: 'manual', // critical: do NOT follow the SSO 302; read its Location.
      signal: controller.signal,
      headers: { 'User-Agent': 'agent-os-verify/1.0' },
    });
    status = res.status;
    location = res.headers.get('location');
  } catch (err) {
    clearTimeout(timer);
    return {
      ok: false,
      status: null,
      location: null,
      expect: matcher,
      observed: 'no-response',
      error: err && err.name === 'AbortError' ? 'timeout' : (err && err.message) || String(err),
    };
  }
  clearTimeout(timer);

  const is3xx = status >= 300 && status < 400;

  if (matcher.kind === 'redirect') {
    const ok = is3xx && typeof location === 'string' && location.includes(matcher.value);
    return {
      ok,
      status,
      location,
      expect: matcher,
      observed: is3xx ? `${status} -> ${location || '(no location)'}` : `status ${status}`,
      error: null,
    };
  }

  if (matcher.kind === 'status') {
    const ok = status === matcher.value;
    return {
      ok,
      status,
      location,
      expect: matcher,
      observed: `status ${status}`,
      error: null,
    };
  }

  return {
    ok: false,
    status,
    location,
    expect: matcher,
    observed: `status ${status}`,
    error: `unknown HEALTH_EXPECT format: ${matcher.value}`,
  };
}
