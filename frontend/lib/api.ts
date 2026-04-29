const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export class BackendError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function callBackend<T = unknown>(
  path: string,
  init: RequestInit | undefined,
  token: string | null,
): Promise<T> {
  if (!token) {
    throw new BackendError(401, "Not authenticated");
  }
  const res = await fetch(`${BACKEND_URL}${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      Authorization: `Bearer ${token}`,
    },
    cache: "no-store",
  });

  if (!res.ok) {
    let detail = "";
    try {
      const body = await res.json();
      const raw = body?.detail;
      if (typeof raw === "string") {
        detail = raw;
      } else if (Array.isArray(raw)) {
        // FastAPI validation errors come back as
        // [{loc: [...], msg: "...", type: "..."}, ...]. Surface the
        // first useful msg with its path; previously we passed the
        // whole array to BackendError which coerced to "[object Object]".
        detail = raw
          .map((e: unknown) => {
            if (e && typeof e === "object") {
              const obj = e as { loc?: unknown[]; msg?: string };
              const loc = Array.isArray(obj.loc)
                ? obj.loc.filter((p) => p !== "body").join(".")
                : "";
              const msg = obj.msg ?? JSON.stringify(e);
              return loc ? `${loc}: ${msg}` : msg;
            }
            return String(e);
          })
          .join("; ");
      } else if (raw && typeof raw === "object") {
        detail = JSON.stringify(raw);
      } else {
        detail = JSON.stringify(body);
      }
    } catch {
      detail = await res.text().catch(() => "");
    }
    throw new BackendError(res.status, detail || res.statusText);
  }

  if (res.status === 204) return null as T;
  const ctype = res.headers.get("content-type") ?? "";
  return (ctype.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}
