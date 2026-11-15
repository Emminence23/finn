// Single typed entry point to the FINN API. Feature types are added here as endpoints land.
const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const PASSCODE_KEY = "finn.passcode";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export function getPasscode(): string {
  try {
    return localStorage.getItem(PASSCODE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setPasscode(value: string) {
  try {
    localStorage.setItem(PASSCODE_KEY, value);
  } catch {
    /* storage unavailable: passcode lasts for this page only */
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Finn-Passcode": getPasscode(),
      ...init.headers,
    },
  });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  return res.json() as Promise<T>;
}

export const fetcher = <T,>(path: string) => api<T>(path);

// ---- types ----
export type Health = { status: "ok"; counts: Record<string, number> };
