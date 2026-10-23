/**
 * Where the backend lives. Empty in development: Vite proxies /api and /ws to localhost:8000.
 * Hosted (frontend on Vercel, backend on Railway), VITE_BACKEND_URL is the backend's https
 * origin, set at build time.
 */
function normalizeBackend(url: string | undefined): string {
  const trimmed = (url ?? "").trim().replace(/\/+$/, "");
  if (!trimmed) return "";
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  return `https://${trimmed}`;
}

const BACKEND = normalizeBackend(import.meta.env.VITE_BACKEND_URL);

export function apiUrl(path: string): string {
  return `${BACKEND}${path}`;
}

export function wsUrl(path: string): string {
  if (BACKEND) return `${BACKEND.replace(/^http/i, "ws")}${path}`;
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}${path}`;
}
