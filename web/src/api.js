const TOKEN_KEY = "vitals-session";
let token = null;

try {
  token = localStorage.getItem(TOKEN_KEY);
  if (!token || token.length < 16) token = null;
} catch (_) {
  token = null;
}

export function getToken() {
  return token;
}

export function setToken(value) {
  token = value || null;
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch (_) {}
}

export function authHeaders() {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export async function request(path, options = {}) {
  const headers = { ...authHeaders(), ...(options.headers || {}) };
  if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const response = await fetch(path, { cache: "no-store", ...options, headers });
  let payload = null;
  try {
    payload = await response.json();
  } catch (_) {
    payload = null;
  }
  if (response.status === 401) {
    const error = new Error("unauthorized");
    error.status = 401;
    throw error;
  }
  if (!response.ok) {
    const error = new Error(payload?.error || `HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

export const api = {
  session: () => request("/api/session"),
  login: (username, password) =>
    request("/api/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  logout: () => request("/api/logout", { method: "POST" }),
  status: () => request("/api/status"),
  overview: () => request("/api/overview"),
  history: (minutes) => request(`/api/history?minutes=${minutes}`),
  events: (limit = 30, before = null) =>
    request(`/api/events?limit=${limit}${before ? `&before=${before}` : ""}`),
  processes: (limit = 0) => request(`/api/processes${limit ? `?limit=${limit}` : ""}`),
};
