import { afterEach, describe, expect, it, vi } from "vitest";

import {
  cancelModelJob,
  checkHealth,
  checkReadiness,
  exportPlanMarkdown,
  fetchExamples,
  generateControlPlan,
  MODEL_API_REQUEST_TIMEOUT_MS,
  optimizeControlPlan,
  reviewPlan,
  setAccessTokenProvider,
  validatePlan,
} from "./api";


const PAYLOAD = {
  control_object: "Water tank",
  input_devices: "Level sensor",
  output_devices: "Pump",
  control_requirements: "Control the pump from the level signal.",
  model_provider: "DeepSeek",
};


afterEach(() => {
  setAccessTokenProvider(() => "");
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

  it("reuses the idempotency key when the same failed mutation is retried", async () => {
    const retryPayload = { ...PAYLOAD, control_object: "Retry motor" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ code: "API_CAPACITY_EXCEEDED", message: "Busy" }),
          {
            status: 503,
            headers: { "Content-Type": "application/json" },
          },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({
          job_id: "job-1",
          status: "succeeded",
          result: { plan_id: "plan-1" },
        }), {
          status: 202,
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(generateControlPlan(retryPayload)).rejects.toMatchObject({
      status: 503,
    });
    await expect(generateControlPlan(retryPayload)).resolves.toMatchObject({
      plan_id: "plan-1",
    });

    const firstKey = fetchMock.mock.calls[0][1].headers["Idempotency-Key"];
    const secondKey = fetchMock.mock.calls[1][1].headers["Idempotency-Key"];
    expect(secondKey).toBe(firstKey);
  });
});


describe("backend readiness", () => {
  it("uses the readiness endpoint before enabling model actions", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ready", checks: {} }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(checkReadiness()).resolves.toMatchObject({ status: "ready" });
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/ready$/);
  });
});


describe("durable model jobs", () => {
  it("polls queued work until the persisted result succeeds", async () => {
    vi.useFakeTimers();
    const statuses = [];
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({
          job_id: "job-1",
          status: "queued",
          progress: 0,
          attempts: 0,
          max_attempts: 3,
        }), { status: 202, headers: { "Content-Type": "application/json" } }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({
          job_id: "job-1",
          status: "running",
          progress: 10,
          attempts: 1,
          max_attempts: 3,
        }), { status: 200, headers: { "Content-Type": "application/json" } }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({
          job_id: "job-1",
          status: "succeeded",
          progress: 100,
          attempts: 1,
          max_attempts: 3,
          result: { plan_id: "plan-1" },
        }), { status: 200, headers: { "Content-Type": "application/json" } }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const pending = generateControlPlan(PAYLOAD, {
      onStatus: (job) => statuses.push(job.status),
    });
    await vi.advanceTimersByTimeAsync(1000);
    await vi.advanceTimersByTimeAsync(1000);

    await expect(pending).resolves.toEqual({ plan_id: "plan-1" });
    expect(statuses).toEqual(["queued", "running", "succeeded"]);
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/jobs\/generate$/);
    expect(fetchMock.mock.calls[1][0]).toMatch(/\/jobs\/job-1$/);
  });

  it("sends cancellation to the persisted job endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ job_id: "job/1", status: "cancel_requested" }), {
        status: 202,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(cancelModelJob("job/1")).resolves.toMatchObject({
      status: "cancel_requested",
    });
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/jobs\/job%2F1\/cancel$/);
    expect(fetchMock.mock.calls[0][1].method).toBe("POST");
  });

  it("keeps the idempotency key when polling is interrupted", async () => {
    vi.useFakeTimers();
    const retryPayload = { ...PAYLOAD, control_object: "Recoverable motor" };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({
          job_id: "job-recover",
          status: "queued",
        }), { status: 202, headers: { "Content-Type": "application/json" } }),
      )
      .mockRejectedValueOnce(new TypeError("network unavailable"))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({
          job_id: "job-recover",
          status: "succeeded",
          result: { plan_id: "plan-recover" },
        }), { status: 202, headers: { "Content-Type": "application/json" } }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const interrupted = generateControlPlan(retryPayload);
    const interruptedResult = expect(interrupted).rejects.toMatchObject({
      name: "ApiRequestError",
    });
    await vi.advanceTimersByTimeAsync(1000);
    await interruptedResult;
    await expect(generateControlPlan(retryPayload)).resolves.toEqual({
      plan_id: "plan-recover",
    });

    const firstKey = fetchMock.mock.calls[0][1].headers["Idempotency-Key"];
    const retryKey = fetchMock.mock.calls[2][1].headers["Idempotency-Key"];
    expect(retryKey).toBe(firstKey);
  });
});


describe("persisted plan review and export", () => {
  it("sends the OIDC access token in the authorization header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ decision: "approved" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    setAccessTokenProvider(() => "oidc-access-token");

    await reviewPlan(
      "plan/1",
      { decision: "approved", comment: "" },
    );

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toMatch(/\/plans\/plan%2F1\/reviews$/);
    expect(options.headers.Authorization).toBe("Bearer oidc-access-token");
    expect(options.headers["Idempotency-Key"]).toMatch(/^[A-Za-z0-9._:-]{8,128}$/);
    expect(options.body).not.toContain("oidc-access-token");
  });

  it("returns Markdown text from the controlled export endpoint", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("# Approved plan", {
          status: 200,
          headers: { "Content-Type": "text/markdown" },
        }),
      ),
    );

    await expect(exportPlanMarkdown("plan-1")).resolves.toBe("# Approved plan");
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
      new Response(JSON.stringify({
        job_id: "job-1",
        status: "succeeded",
        result: { ok: true },
      }), {
        status: 202,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(generateControlPlan(PAYLOAD)).resolves.toEqual({ ok: true });

    expect(vi.getTimerCount()).toBe(0);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});


describe("health, examples, and model-free validation APIs", () => {
  it("returns health data without retrying after a successful request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        status: "ok",
        version: "1.0.0",
        model: "deepseek-chat",
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(checkHealth({ maxRetries: 0 })).resolves.toMatchObject({ status: "ok" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("returns backend examples", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ examples: [{ name: "test" }] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(fetchExamples()).resolves.toEqual({ examples: [{ name: "test" }] });
  });

  it("posts an existing plan to the model-free validation endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({
        validation_report: { total_rules: 14, risk_level: "low", risk_score: 0 },
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(validatePlan({ plan_text: "test" })).resolves.toMatchObject({
      validation_report: { total_rules: 14 },
    });
    expect(fetchMock.mock.calls[0][0]).toMatch(/\/validate$/);
  });
});
