/** Thin API client — all calls go to the backend via the Nginx proxy. */

const BASE = process.env.NEXT_PUBLIC_API_BASE_PATH ?? "/api/v1";

export async function api<T = unknown>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const url = `${BASE}${path}`;
  const res = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export function apiPost<T = unknown>(
  path: string,
  body: unknown,
): Promise<T> {
  return api<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function apiPatch<T = unknown>(
  path: string,
  body: unknown,
): Promise<T> {
  return api<T>(path, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export function apiDelete(path: string): Promise<void> {
  const url = `${BASE}${path}`;
  return fetch(url, { method: "DELETE" }).then((res) => {
    if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  });
}
