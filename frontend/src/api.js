const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim();
const developmentBaseUrl = import.meta.env.DEV ? "http://localhost:8000" : "";

export const API_BASE_URL = (configuredBaseUrl || developmentBaseUrl).replace(/\/$/, "");
export const MODEL_API_REQUEST_TIMEOUT_MS = 120000;
const MAPPED_ERROR_STATUSES = new Set([401, 403, 422, 429, 502, 503, 504]);


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
  const { timeoutMs = 120000, ...fetchOptions } = options;
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      ...fetchOptions,
      headers: {
        ...(fetchOptions.body ? { "Content-Type": "application/json" } : {}),
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

    return await response.json();
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


export function fetchExamples() {
  return request("/examples", { timeoutMs: 10000 });
}


export function generateControlPlan(payload) {
  return request("/generate", {
    method: "POST",
    body: JSON.stringify(payload),
    timeoutMs: MODEL_API_REQUEST_TIMEOUT_MS,
  });
}


export function optimizeControlPlan(payload) {
  return request("/optimize", {
    method: "POST",
    body: JSON.stringify(payload),
    timeoutMs: MODEL_API_REQUEST_TIMEOUT_MS,
  });
}
