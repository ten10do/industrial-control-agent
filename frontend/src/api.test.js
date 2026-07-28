import { afterEach, describe, expect, it, vi } from "vitest";

import {
  generateControlPlan,
  MODEL_API_REQUEST_TIMEOUT_MS,
  optimizeControlPlan,
} from "./api";


const PAYLOAD = {
  control_object: "Water tank",
  input_devices: "Level sensor",
  output_devices: "Pump",
  control_requirements: "Control the pump from the level signal.",
  model_provider: "DeepSeek",
};


afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});


describe("model API traffic guard errors", () => {
  it("shows retry timing for a rate-limited request without retrying automatically", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          code: "API_RATE_LIMIT_EXCEEDED",
          message: "Too many requests",
          request_id: "rate-limit-1",
        }),
        {
          status: 429,
          headers: {
            "Content-Type": "application/json",
            "Retry-After": "17",
            "X-Request-ID": "rate-limit-1",
          },
        },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(generateControlPlan(PAYLOAD)).rejects.toMatchObject({
      name: "ApiRequestError",
      status: 429,
      code: "API_RATE_LIMIT_EXCEEDED",
      requestId: "rate-limit-1",
      retryAfterSeconds: 17,
      message: "请求过于频繁，请在 17 秒后重试。",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([
    [401, "API_ACCESS_DENIED", null, "此功能需要有效访问凭证，当前请求未获授权。"],
    [503, "API_CAPACITY_EXCEEDED", "1", "服务当前繁忙，请在 1 秒后重试。"],
  ])("maps protected route status %s to a stable message", async (
    status,
    code,
    retryAfter,
    message,
  ) => {
    const headers = { "Content-Type": "application/json" };
    if (retryAfter) {
      headers["Retry-After"] = retryAfter;
    }
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ code, message: "backend message" }),
          {
            status,
            headers,
          },
        ),
      ),
    );

    await expect(generateControlPlan(PAYLOAD)).rejects.toMatchObject({
      status,
      code,
      message,
      retryAfterSeconds: retryAfter ? Number(retryAfter) : null,
    });
  });
});


describe("model API timeout budget", () => {
  it.each([
    ["generate", generateControlPlan],
    ["optimize", optimizeControlPlan],
  ])("aborts %s once at the explicit model timeout", async (_, invoke) => {
    expect(MODEL_API_REQUEST_TIMEOUT_MS).toBe(120000);
    vi.useFakeTimers();
    let requestSignal;
    const fetchMock = vi.fn().mockImplementation((_url, options) => {
      requestSignal = options.signal;
      return new Promise((_resolve, reject) => {
        requestSignal.addEventListener("abort", () => {
          reject(new DOMException("Aborted", "AbortError"));
        });
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    const requestPromise = invoke(PAYLOAD);
    const rejection = expect(requestPromise).rejects.toMatchObject({
      name: "ApiRequestError",
      status: 408,
      code: "CLIENT_TIMEOUT",
    });

    await vi.advanceTimersByTimeAsync(MODEL_API_REQUEST_TIMEOUT_MS - 1);
    expect(requestSignal.aborted).toBe(false);

    await vi.advanceTimersByTimeAsync(1);
    await rejection;

    expect(requestSignal.aborted).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("clears the model timeout after a successful response", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(generateControlPlan(PAYLOAD)).resolves.toEqual({ ok: true });

    expect(vi.getTimerCount()).toBe(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
