const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim();
const developmentBaseUrl = import.meta.env.DEV ? "http://localhost:8000" : "";

export const API_BASE_URL = (configuredBaseUrl || developmentBaseUrl).replace(/\/$/, "");


class ApiRequestError extends Error {
  constructor(message, status = null, requestId = "") {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.requestId = requestId;
  }
}


function errorMessageForStatus(status) {
  if (status === 422) {
    return "输入信息不完整或格式不正确，请检查后重试。";
  }
  if (status === 502 || status === 503 || status === 504) {
    return "模型服务暂时不可用，请稍后重试。";
  }
  if (status === 401 || status === 403) {
    return "后端服务认证失败，请联系系统管理员。";
  }
  return "后端服务处理失败，请稍后重试。";
}


async function request(path, options = {}) {
  const { timeoutMs = 110000, ...fetchOptions } = options;
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
      throw new ApiRequestError(
        payload?.message || errorMessageForStatus(response.status),
        response.status,
        requestId,
      );
    }

    return await response.json();
  } catch (error) {
    if (error instanceof ApiRequestError) {
      throw error;
    }
    if (error.name === "AbortError") {
      throw new ApiRequestError("请求超时，请稍后重试。", 408);
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
  });
}


export function optimizeControlPlan(payload) {
  return request("/optimize", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
export function validatePlan(payload) {
  return request("/validate", {
    method: "POST",
    body: JSON.stringify(payload),
    timeoutMs: 30000,
  });
}
