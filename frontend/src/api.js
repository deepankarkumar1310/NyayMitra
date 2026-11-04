// Base URL of the backend. Empty string = same origin (uses the Vite dev proxy).
const BASE = import.meta.env.VITE_API_URL || "";

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(`${BASE}${path}`, options);
  } catch {
    throw new Error("network");
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof body.detail === "string" ? body.detail : `HTTP ${res.status}`;
    throw new Error(detail);
  }
  return body;
}

export function transcribe(blob, language) {
  const form = new FormData();
  const ext = blob.type.includes("ogg") ? "ogg" : blob.type.includes("mp4") ? "m4a" : "webm";
  form.append("audio", blob, `recording.${ext}`);
  form.append("language", language);
  return request("/api/transcribe", { method: "POST", body: form });
}

export function ask({ text, language, file }) {
  const form = new FormData();
  form.append("text", text);
  form.append("language", language);
  if (file) form.append("file", file);
  return request("/api/ask", { method: "POST", body: form });
}

export const listCases = () => request("/api/cases");
export const getCase = (id) => request(`/api/cases/${id}`);
