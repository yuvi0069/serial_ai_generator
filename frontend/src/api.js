// Thin fetch client for the FastAPI backend. Every call sends the JWT; a 401 logs the user out.
const BASE = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");
const KEY = "serial.token";

export const tokenStore = {
  get: () => localStorage.getItem(KEY),
  set: (t) => localStorage.setItem(KEY, t),
  clear: () => localStorage.removeItem(KEY),
};

async function request(path, { method = "GET", body, raw = false } = {}) {
  const headers = { "Content-Type": "application/json" };
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  let res;
  try {
    res = await fetch(BASE + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  } catch {
    throw new Error(`Can't reach the server at ${BASE}. Check that the backend is running.`);
  }
  if (res.status === 401 && token) {
    tokenStore.clear();
    window.dispatchEvent(new Event("auth:expired"));
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : j.detail?.[0]?.msg || msg;
    } catch { /* non-JSON error body */ }
    throw new Error(msg);
  }
  if (res.status === 204) return null;
  return raw ? res.text() : res.json();
}

export const api = {
  register: (email, password) => request("/auth/register", { method: "POST", body: { email, password } }),
  login: (email, password) => request("/auth/login", { method: "POST", body: { email, password } }),
  me: () => request("/auth/me"),
  stories: () => request("/stories"),
  createStory: (premise, target_episodes) => request("/stories", { method: "POST", body: { premise, target_episodes } }),
  rename: (id, title) => request(`/stories/${id}`, { method: "PATCH", body: { title } }),
  remove: (id) => request(`/stories/${id}`, { method: "DELETE" }),
  state: (id) => request(`/stories/${id}/state`),
  messages: (id) => request(`/stories/${id}/messages`),
  act: (id, body) => request(`/stories/${id}/act`, { method: "POST", body }),
  retry: (id) => request(`/stories/${id}/retry`, { method: "POST" }),
  plan: (id) => request(`/stories/${id}/plan`),
  memory: (id) => request(`/stories/${id}/memory`),
  toggleDirective: (id, did) => request(`/stories/${id}/directives/${did}`, { method: "PATCH" }),
  logs: (id) => request(`/stories/${id}/logs`),
  editEpisode: (id, n, content, title) => request(`/stories/${id}/episodes/${n}`, { method: "PUT", body: { content, title } }),
  exportMd: (id) => request(`/stories/${id}/export`, { raw: true }),
};
