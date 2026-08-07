const BASE = "/api";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const isFormData = options.body instanceof FormData;
  const res = await fetch(`${BASE}${path}`, {
    credentials: "include",
    ...options,
    headers: isFormData ? options.headers : { "Content-Type": "application/json", ...options.headers },
  });

  if (!res.ok) {
    let message = res.statusText;
    try {
      const data = await res.json();
      message = data.detail ?? message;
    } catch {
      // тело не JSON — оставляем statusText
    }
    throw new ApiError(res.status, message);
  }

  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

// Отдельно от request<T>: тот всегда читает тело как JSON, а /voice/speak
// отдаёт audio/wav — бинарь нужно забрать как Blob, не пытаясь распарсить.
async function postForBlob(path: string, body: unknown): Promise<Blob> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let message = res.statusText;
    try {
      const data = await res.json();
      message = data.detail ?? message;
    } catch {
      // тело не JSON — оставляем statusText
    }
    throw new ApiError(res.status, message);
  }
  return res.blob();
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown, signal?: AbortSignal) =>
    request<T>(path, {
      method: "POST",
      body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
      signal,
    }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  postForBlob,
};
