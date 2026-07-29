import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import {
  checkHealth,
  checkReadiness,
  fetchCurrentUser,
  fetchExamples,
  fetchPlan,
  fetchPlanAudit,
  fetchPlans,
  reviewPlan,
} from "./api";


vi.mock("./auth", () => {
  const authState = {
    enabled: true,
    ready: true,
    user: {
      access_token: "oidc-token",
      profile: { sub: "reviewer-1", name: "Reviewer One" },
    },
    error: "",
    login: vi.fn(),
    logout: vi.fn(),
  };
  return { useAuth: () => authState };
});

vi.mock("./api", () => ({
  checkHealth: vi.fn(),
  checkReadiness: vi.fn(),
  exportPlanMarkdown: vi.fn(),
  fetchCurrentUser: vi.fn(),
  fetchExamples: vi.fn(),
  fetchPlan: vi.fn(),
  fetchPlanAudit: vi.fn(),
  fetchPlans: vi.fn(),
  generateControlPlan: vi.fn(),
  optimizeControlPlan: vi.fn(),
  reviewPlan: vi.fn(),
}));


const PLAN = {
  plan_id: "plan-1",
  parent_plan_id: null,
  source: "generate",
  content_hash: "abc123",
  report_markdown: "# Pending plan",
  response: {
    safety_notice: "Requires an independent review.",
    safety_gate: {
      status: "review_required",
      review_required: true,
      export_allowed: false,
      reasons: ["Critical risk requires review."],
    },
  },
  review_required: true,
  export_allowed: false,
  created_by: "designer-1",
  created_by_name: "Designer One",
  latest_review: null,
  created_at: "2026-07-28T08:00:00Z",
};


describe("App RBAC review workspace", () => {
  beforeEach(() => {
    checkHealth.mockResolvedValue({ status: "ok" });
    checkReadiness.mockResolvedValue({ status: "ready", checks: {} });
    fetchExamples.mockResolvedValue({ examples: [] });
    fetchCurrentUser.mockResolvedValue({
      subject: "reviewer-1",
      display_name: "Reviewer One",
      roles: ["reviewer"],
    });
    fetchPlans.mockResolvedValue({
      plans: [{
        ...PLAN,
        latest_decision: null,
      }],
    });
    fetchPlan.mockResolvedValue(PLAN);
    fetchPlanAudit.mockResolvedValue({
      chain_valid: true,
      events: [{
        event_id: "event-1",
        actor_sub: "designer-1",
        actor_name: "Designer One",
        action: "plan.created",
        resource_type: "plan",
        resource_id: "plan-1",
        plan_hash: "abc123",
        request_id: "request-1",
        details: {},
        previous_hash: "",
        event_hash: "hash-1",
        created_at: "2026-07-28T08:00:00Z",
      }],
    });
    reviewPlan.mockResolvedValue({
      review_id: "review-1",
      plan_id: "plan-1",
      decision: "approved",
      reviewer_sub: "reviewer-1",
      reviewer: "Reviewer One",
      comment: "",
      content_hash: "abc123",
      reviewed_at: "2026-07-28T08:05:00Z",
      export_allowed: true,
    });
  });

  it("shows a role-scoped inbox and approves with verified identity", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "方案与审批收件箱" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "控制任务配置面板" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /生成版本/ }));

    expect(await screen.findByRole("heading", { name: "审计轨迹" })).toBeInTheDocument();
    expect(screen.getByLabelText("已验证审批身份")).toHaveTextContent("Reviewer One");
    await user.click(screen.getByLabelText("我已独立复核风险项；审批身份由登录凭证验证。"));
    await user.click(screen.getByRole("button", { name: "提交独立审批并解锁导出" }));

    await waitFor(() => expect(reviewPlan).toHaveBeenCalledWith(
      "plan-1",
      { decision: "approved", comment: "" },
    ));
    expect(await screen.findByText("后端安全审批已记录")).toBeInTheDocument();
  });
});
