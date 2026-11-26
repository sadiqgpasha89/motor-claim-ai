export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface ApiError {
  error_code: string;
  message: string;
  correlation_id?: string;
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  token?: string | null
): Promise<T> {
  const headers = new Headers(options.headers || {});
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (!(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    cache: "no-store",
  });

  if (!res.ok) {
    let errBody: ApiError = {
      error_code: "DEPENDENCY_UNAVAILABLE",
      message: `HTTP ${res.status} error`,
    };
    try {
      errBody = await res.json();
    } catch {
      // keep default
    }
    const msg = errBody.correlation_id
      ? `${errBody.error_code}: ${errBody.message} (Correlation ID: ${errBody.correlation_id})`
      : `${errBody.error_code}: ${errBody.message}`;
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}
