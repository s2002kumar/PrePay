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

export class ApiRequestError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

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

export const api = {
  health: () => call<Health>("/api/health"),
  pools: () => call<PoolsResponse>("/api/pools"),
  scenarios: () => call<ScenariosResponse>("/api/scenarios"),
  methodology: () => call<Methodology>("/api/methodology"),
  modelQuality: () => call<ModelQuality>("/api/model-quality"),
  project: (request: ProjectionRequest, signal?: AbortSignal) =>
    call<ProjectionResponse>("/api/project", {
      method: "POST",
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
      ...(signal ? { signal } : {}),
    }),
};
