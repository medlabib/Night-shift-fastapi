/**
 * Thin client for the authenticated API.
 *
 * The studio runs in two modes. Signed out, it talks to the public
 * /schedule endpoint and keeps everything in localStorage, so the tool is
 * usable in ten seconds without an account. Signed in, everything here
 * takes over: the roster, schedules, edits and exports all live on the
 * server and belong to a department.
 */

const JSON_HEADERS = { 'Content-Type': 'application/json' };

export class ApiError extends Error {
  constructor(status, detail) {
    super(ApiError.readable(detail, status));
    this.status = status;
    this.detail = detail;
  }

  /** FastAPI details arrive as a string, a validation array, or our own object. */
  static readable(detail, status) {
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      return detail.map((d) => d.msg || JSON.stringify(d)).join('; ');
    }
    if (detail && typeof detail === 'object') {
      const reasons = detail.reasons || detail.errors;
      return [detail.message, ...(reasons || [])].filter(Boolean).join(' ');
    }
    return `Request failed (${status}).`;
  }

  get reasons() {
    const d = this.detail;
    if (d && typeof d === 'object' && !Array.isArray(d)) return d.reasons || d.errors || [];
    return [];
  }
}

async function request(path, { method = 'GET', body, base = '' } = {}) {
  const res = await fetch(`${base}${path}`, {
    method,
    headers: body === undefined ? undefined : JSON_HEADERS,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin', // the session is an HttpOnly cookie
  });

  if (res.status === 204) return null;

  let payload = null;
  const type = res.headers.get('content-type') || '';
  if (type.includes('application/json')) payload = await res.json();

  if (!res.ok) throw new ApiError(res.status, payload?.detail ?? payload);
  return payload;
}

export const api = {
  base: '',
  call: (path, opts = {}) => request(path, { ...opts, base: api.base }),

  // ── session ──
  session: () => api.call('/api/auth/session'),
  login: (email, password) =>
    api.call('/api/auth/login', { method: 'POST', body: { email, password } }),
  signup: (body) => api.call('/api/auth/signup', { method: 'POST', body }),
  logout: () => api.call('/api/auth/logout', { method: 'POST' }),
  requestReset: (email) =>
    api.call('/api/auth/password/reset-request', { method: 'POST', body: { email } }),

  // ── departments & roster ──
  departments: () => api.call('/api/departments'),
  createDepartment: (body) => api.call('/api/departments', { method: 'POST', body }),
  doctors: (dep) => api.call(`/api/departments/${dep}/doctors`),
  addDoctor: (dep, body) =>
    api.call(`/api/departments/${dep}/doctors`, { method: 'POST', body }),
  updateDoctor: (dep, id, body) =>
    api.call(`/api/departments/${dep}/doctors/${id}`, { method: 'PATCH', body }),
  removeDoctor: (dep, id) =>
    api.call(`/api/departments/${dep}/doctors/${id}`, { method: 'DELETE' }),
  setLeave: (dep, id, dates) =>
    api.call(`/api/departments/${dep}/doctors/${id}/leave`, { method: 'PUT', body: { dates } }),

  // ── schedules ──
  schedules: (dep) => api.call(`/api/departments/${dep}/schedules`),
  schedule: (dep, id) => api.call(`/api/departments/${dep}/schedules/${id}`),
  generate: (dep, body) =>
    api.call(`/api/departments/${dep}/schedules`, { method: 'POST', body }),
  deleteSchedule: (dep, id) =>
    api.call(`/api/departments/${dep}/schedules/${id}`, { method: 'DELETE' }),
  publish: (dep, id) =>
    api.call(`/api/departments/${dep}/schedules/${id}/publish`, { method: 'POST' }),

  // ── editing ──
  unassign: (dep, id, body) =>
    api.call(`/api/departments/${dep}/schedules/${id}/unassign`, { method: 'POST', body }),
  assign: (dep, id, body) =>
    api.call(`/api/departments/${dep}/schedules/${id}/assign`, { method: 'POST', body }),
  swap: (dep, id, body) =>
    api.call(`/api/departments/${dep}/schedules/${id}/swap`, { method: 'POST', body }),
  lock: (dep, id, body) =>
    api.call(`/api/departments/${dep}/schedules/${id}/lock`, { method: 'POST', body }),
  retune: (dep, id, body) =>
    api.call(`/api/departments/${dep}/schedules/${id}/retune`, { method: 'POST', body }),
  validate: (dep, id) =>
    api.call(`/api/departments/${dep}/schedules/${id}/validate`),

  // ── preferences ──
  preferences: (dep) => api.call(`/api/departments/${dep}/preferences`),
  trainPreferences: (dep) =>
    api.call(`/api/departments/${dep}/preferences/train`, { method: 'POST' }),
  clearPreferences: (dep) =>
    api.call(`/api/departments/${dep}/preferences`, { method: 'DELETE' }),

  // ── sharing ──
  shares: (dep, id) => api.call(`/api/departments/${dep}/schedules/${id}/shares`),
  createShare: (dep, id, body) =>
    api.call(`/api/departments/${dep}/schedules/${id}/shares`, { method: 'POST', body }),
  revokeShare: (dep, id, share) =>
    api.call(`/api/departments/${dep}/schedules/${id}/shares/${share}`, { method: 'DELETE' }),

  // ── files (opened, not fetched, so the browser handles the download) ──
  pdfUrl: (dep, id, layout) =>
    `${api.base}/api/departments/${dep}/schedules/${id}/pdf?layout=${layout}`,
  csvUrl: (dep, id) => `${api.base}/api/departments/${dep}/schedules/${id}/csv`,
};
