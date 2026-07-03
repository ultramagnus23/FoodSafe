// Base fetch client — ported from index.html's apiFetch/tokenStore, now typed.
// All API calls in the app must go through this layer.

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

const TOKEN_KEY = "foodsafe_token";

export const tokenStore = {
  get(): string | null {
    if (typeof window === "undefined") return null;
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set(t: string) {
    try {
      localStorage.setItem(TOKEN_KEY, t);
    } catch {
      /* ignore */
    }
  },
  clear() {
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch {
      /* ignore */
    }
  },
};

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

interface FetchOpts {
  method?: string;
  body?: unknown;
  auth?: boolean; // default true
}

export async function apiFetch<T>(path: string, opts: FetchOpts = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = tokenStore.get();
  if (opts.auth !== false && token) headers["Authorization"] = `Bearer ${token}`;

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: opts.method || "GET",
      headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
  } catch {
    throw new ApiError(`Could not reach the API at ${API_BASE}. Is the backend running?`, 0);
  }

  if (res.status === 401) {
    tokenStore.clear();
    throw new ApiError("Please sign in to view live data.", 401);
  }

  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    /* no body */
  }

  if (!res.ok) {
    const detail =
      data && typeof data === "object" && "detail" in data
        ? typeof (data as { detail: unknown }).detail === "string"
          ? (data as { detail: string }).detail
          : JSON.stringify((data as { detail: unknown }).detail)
        : null;
    throw new ApiError(detail || `Request failed (${res.status})`, res.status);
  }

  return data as T;
}

export { API_BASE };
