import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { checkHealth, fetchExamples, generateControlPlan, validatePlan } from "./api";

const MOCK_BASE = "http://localhost:8000";

describe("checkHealth", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns health data on success", async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ status: "ok", version: "1.0.0", model: "deepseek-chat" }),
      headers: new Headers(),
    });
    const result = await checkHealth({ maxRetries: 0 });
    expect(result.status).toBe("ok");
  });




});

describe("fetchExamples", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns examples array", async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ examples: [{ name: "test", control_object: "obj" }] }),
      headers: new Headers(),
    });
    const result = await fetchExamples();
    expect(result.examples).toHaveLength(1);
  });
});

describe("generateControlPlan", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("handles 422 validation error", async () => {
    fetch.mockResolvedValueOnce({
      ok: false,
      status: 422,
      json: async () => ({ code: "VALIDATION_ERROR", message: "invalid" }),
      headers: new Headers(),
    });
    await expect(generateControlPlan({})).rejects.toThrow();
  });

  it("handles 502 backend error", async () => {
    fetch.mockResolvedValueOnce({
      ok: false,
      status: 502,
      json: async () => ({ code: "API_SERVICE_ERROR" }),
      headers: new Headers(),
    });
    await expect(generateControlPlan({ control_object: "test" })).rejects.toThrow();
  });

  it("handles non-JSON response gracefully", async () => {
    fetch.mockResolvedValueOnce({
      ok: false,
      status: 502,
      json: async () => { throw new Error("not json"); },
      headers: new Headers(),
    });
    await expect(generateControlPlan({ control_object: "test" })).rejects.toThrow();
  });
});

describe("validatePlan", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns validation report", async () => {
    fetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        validation_report: {
          total_rules: 14,
          risk_level: "low",
          risk_score: 0,
          issues: [],
        },
      }),
      headers: new Headers(),
    });
    const result = await validatePlan({ plan_text: "test" });
    expect(result.validation_report.total_rules).toBe(14);
  });
});
