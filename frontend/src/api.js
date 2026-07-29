const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim();
const developmentBaseUrl = import.meta.env.DEV ? "http://localhost:8000" : "";

export const API_BASE_URL = (configuredBaseUrl || developmentBaseUrl).replace(/\/$/, "");
export const MODEL_API_REQUEST_TIMEOUT_MS = 120000;
export const MODEL_JOB_POLL_INTERVAL_MS = 1000;
export const MODEL_JOB_WAIT_TIMEOUT_MS = 10 * 60 * 1000;
const MAPPED_ERROR_STATUSES = new Set([401, 403, 409, 422, 429, 502, 503, 504]);
let accessTokenProvider = () => "";
const pendingIdempotencyKeys = new Map();


export function setAccessTokenProvider(provider) {
  accessTokenProvider = typeof provider === "function" ? provider : () => "";
}


class ApiRequestError extends Error {
  constructor(
    message,
    status = null,
    requestId = "",
    code = "",
    retryAfterSeconds = null,
  ) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.requestId = requestId;
    this.code = code;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}


function errorMessageForStatus(status, retryAfterSeconds = null) {
  if (status === 422) {
    return "输入信息不完整或格式不正确，请检查后重试。";
  }
  if (status === 409) {
    return "请求正在处理或数据版本已变化，请稍后重试或刷新方案。";
  }
  if (status === 429) {
    return retryAfterSeconds
      ? `请求过于频繁，请在 ${retryAfterSeconds} 秒后重试。`
      : "请求过于频繁，请稍后重试。";
  }
  if (status === 503) {
    return retryAfterSeconds
      ? `服务当前繁忙，请在 ${retryAfterSeconds} 秒后重试。`
      : "服务当前繁忙，请稍后重试。";
  }
  if (status === 502 || status === 504) {
    return "模型服务暂时不可用，请稍后重试。";
  }
  if (status === 401) {
    return "此功能需要有效访问凭证，当前请求未获授权。";
  }
  if (status === 403) {
    return "当前访问凭证无权执行此操作。";
  }
  return "后端服务处理失败，请稍后重试。";
}


function parseRetryAfter(response) {
  const rawValue = response.headers.get("Retry-After");
  if (!rawValue) {
    return null;
  }
  const seconds = Number(rawValue);
  return Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds) : null;
}


async function request(path, options = {}) {
  const { timeoutMs = 120000, responseType = "json", ...fetchOptions } = options;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const accessToken = accessTokenProvider();
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...fetchOptions,
      headers: {
        ...(fetchOptions.body ? { "Content-Type": "application/json" } : {}),
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        ...fetchOptions.headers,
      },
      signal: controller.signal,
    });

    if (!response.ok) {
      let payload = null;
      try {
        payload = await response.json();
      } catch {
        payload = null;
      }
      const requestId = payload?.request_id || response.headers.get("X-Request-ID") || "";
      const retryAfterSeconds = parseRetryAfter(response);
      const message = MAPPED_ERROR_STATUSES.has(response.status)
        ? errorMessageForStatus(response.status, retryAfterSeconds)
        : payload?.message || errorMessageForStatus(response.status, retryAfterSeconds);
      throw new ApiRequestError(
        message,
        response.status,
        requestId,
        payload?.code || "",
        retryAfterSeconds,
      );
    }

    return responseType === "text" ? await response.text() : await response.json();
  } catch (error) {
    if (error instanceof ApiRequestError) {
      throw error;
    }
    if (error.name === "AbortError") {
      throw new ApiRequestError("请求超时，请稍后重试。", 408, "", "CLIENT_TIMEOUT");
    }
    throw new ApiRequestError("无法连接后端服务，请确认 FastAPI 已启动。");
  } finally {
    window.clearTimeout(timeoutId);
  }
}


export function checkHealth() {
  return request("/health", { timeoutMs: 5000 });
}


function newIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID();
  }
  return `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}


async function idempotentRequest(path, payload, options = {}) {
  const { retainKeyOnSuccess = false, ...requestOptions } = options;
  const serializedPayload = JSON.stringify(payload);
  const attemptKey = `${path}:${serializedPayload}`;
  const idempotencyKey = pendingIdempotencyKeys.get(attemptKey) || newIdempotencyKey();
  pendingIdempotencyKeys.set(attemptKey, idempotencyKey);
  try {
    const response = await request(path, {
      ...requestOptions,
      method: "POST",
      body: serializedPayload,
      headers: {
        "Idempotency-Key": idempotencyKey,
        ...requestOptions.headers,
      },
    });
    if (!retainKeyOnSuccess) {
      pendingIdempotencyKeys.delete(attemptKey);
    }
    return response;
  } catch (error) {
    if (error instanceof ApiRequestError && error.code === "IDEMPOTENCY_CONFLICT") {
      pendingIdempotencyKeys.delete(attemptKey);
    }
    if (
      error instanceof ApiRequestError
      && error.status !== null
      && error.status < 500
      && error.status !== 408
      && error.status !== 409
      && error.status !== 429
    ) {
      pendingIdempotencyKeys.delete(attemptKey);
    }
    throw error;
  }
}


function releaseIdempotencyKey(path, payload) {
  pendingIdempotencyKeys.delete(`${path}:${JSON.stringify(payload)}`);
}


export function checkReadiness() {
  return request("/ready", { timeoutMs: 5000 });
}


export function fetchExamples() {
  return request("/examples", { timeoutMs: 10000 });
}


export function fetchCurrentUser(accessToken = "") {
  return request("/auth/me", {
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    timeoutMs: 10000,
  });
}


export function fetchModelJob(jobId) {
  return request(`/jobs/${encodeURIComponent(jobId)}`, { timeoutMs: 10000 });
}


export function cancelModelJob(jobId) {
  return request(`/jobs/${encodeURIComponent(jobId)}/cancel`, {
    method: "POST",
    timeoutMs: 10000,
  });
}


async function waitForModelJob(initialJob, onStatus) {
  const startedAt = Date.now();
  let job = initialJob;
  while (true) {
    onStatus?.(job);
    if (job.status === "succeeded") {
      return job.result;
    }
    if (job.status === "failed" || job.status === "cancelled") {
      const error = new ApiRequestError(
        job.error_message
          || (job.status === "cancelled" ? "模型任务已取消。" : "模型任务执行失败，请稍后重试。"),
        null,
        "",
        job.error_code || `MODEL_JOB_${job.status.toUpperCase()}`,
      );
      error.modelJobTerminal = true;
      throw error;
    }
    if (Date.now() - startedAt >= MODEL_JOB_WAIT_TIMEOUT_MS) {
      throw new ApiRequestError(
        "模型任务仍在后台执行，可稍后从任务状态继续查看。",
        408,
        "",
        "MODEL_JOB_WAIT_TIMEOUT",
      );
    }
    await new Promise((resolve) => window.setTimeout(resolve, MODEL_JOB_POLL_INTERVAL_MS));
    job = await fetchModelJob(job.job_id);
  }
}


export async function generateControlPlan(payload, { onStatus } = {}) {
  const path = "/jobs/generate";
  try {
    const job = await idempotentRequest(path, payload, {
      timeoutMs: MODEL_API_REQUEST_TIMEOUT_MS,
      retainKeyOnSuccess: true,
    });
    const result = await waitForModelJob(job, onStatus);
    releaseIdempotencyKey(path, payload);
    return result;
  } catch (error) {
    if (error?.modelJobTerminal) {
      releaseIdempotencyKey(path, payload);
    }
    throw error;
  }
}


export async function optimizeControlPlan(payload, { onStatus } = {}) {
  const path = "/jobs/optimize";
  try {
    const job = await idempotentRequest(path, payload, {
      timeoutMs: MODEL_API_REQUEST_TIMEOUT_MS,
      retainKeyOnSuccess: true,
    });
    const result = await waitForModelJob(job, onStatus);
    releaseIdempotencyKey(path, payload);
    return result;
  } catch (error) {
    if (error?.modelJobTerminal) {
      releaseIdempotencyKey(path, payload);
    }
    throw error;
  }
}


export function fetchPlan(planId) {
  return request(`/plans/${encodeURIComponent(planId)}`, { timeoutMs: 10000 });
}


export function fetchPlans(accessToken = "") {
  return request("/plans", {
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    timeoutMs: 10000,
  });
}


export function fetchPlanAudit(planId) {
  return request(`/plans/${encodeURIComponent(planId)}/audit`, { timeoutMs: 10000 });
}


export function reviewPlan(planId, payload) {
  return idempotentRequest(`/plans/${encodeURIComponent(planId)}/reviews`, payload, {
    timeoutMs: 15000,
  });
}


export function exportPlanMarkdown(planId) {
  return request(`/plans/${encodeURIComponent(planId)}/export`, {
    responseType: "text",
    timeoutMs: 15000,
  });
}
