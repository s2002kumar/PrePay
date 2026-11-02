import { ApiRequestError } from "./errors";
import { loadStatic, STATIC, staticProject } from "./static";
import type {
  ApiError,
  Health,
  Methodology,
  ModelQuality,
  PoolsResponse,
  ProjectionRequest,
  ProjectionResponse,
  ScenariosResponse,
} from "./types";

export { ApiRequestError };

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { Accept: "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    let code = "http_error";
    let message = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as ApiError;
      code = body.error.code;
      message = body.error.message;
    } catch {
      // keep the generic message: the body was not the documented error envelope
    }
    throw new ApiRequestError(response.status, code, message);
  }
  return (await response.json()) as T;
}

/** GET payloads: the live API, or the same JSON stored by the static export. */
function get<T>(name: string): Promise<T> {
  return STATIC ? loadStatic<T>(`api/${name}.json`) : call<T>(`/api/${name}`);
}

export const api = {
  health: () => get<Health>("health"),
  pools: () => get<PoolsResponse>("pools"),
  scenarios: () => get<ScenariosResponse>("scenarios"),
  methodology: () => get<Methodology>("methodology"),
  modelQuality: () => get<ModelQuality>("model-quality"),
  project: (request: ProjectionRequest, signal?: AbortSignal) =>
    STATIC
      ? staticProject(request)
      : call<ProjectionResponse>("/api/project", {
          method: "POST",
          body: JSON.stringify(request),
          headers: { "Content-Type": "application/json" },
          ...(signal ? { signal } : {}),
        }),
};
