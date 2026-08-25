import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import {
  checkHealth,
  checkReadiness,
  exportPlanMarkdown,
  fetchCurrentUser,
  fetchExamples,
  fetchPlan,
  fetchPlanAudit,
  fetchPlans,
  generateControlPlan,
  optimizeControlPlan,
  reviewPlan,
} from "./api";


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


const EXAMPLE = {
  name: "兼容性测试场景",
  control_object: "测试电机",
  input_devices: "启动按钮、停止按钮",
  output_devices: "电机接触器",
  control_requirements: "启动和停止电机",
};

const LEGACY_RESPONSE = {
  requirement_analysis: "旧响应需求分析",
  io_table: [],
  control_logic: "旧响应控制逻辑",
  safety_design: "旧响应安全设计",
  ladder_idea: "旧响应梯形图",
  report_markdown: "# 旧响应报告",
  safety_notice: "旧响应安全提示",
};


describe("App response compatibility", () => {
  beforeEach(() => {
    checkHealth.mockResolvedValue({ status: "ok" });
    checkReadiness.mockResolvedValue({ status: "ready", checks: {} });
    fetchExamples.mockResolvedValue({ examples: [EXAMPLE] });
    generateControlPlan.mockResolvedValue(LEGACY_RESPONSE);
    optimizeControlPlan.mockResolvedValue({
      optimized_report: "# 优化后报告\n\n已增加急停复位逻辑。",
      change_summary: "增加急停复位逻辑。",
      safety_notice: "需要专业工程师复核。",
      validation_report: null,
    });
    reviewPlan.mockResolvedValue({
      review_id: "review-1",
      plan_id: "plan-1",
      decision: "approved",
      reviewer: "工程师 A",
      comment: "",
      content_hash: "abc",
      reviewed_at: "2026-07-28T08:00:00Z",
      export_allowed: true,
    });
    exportPlanMarkdown.mockResolvedValue("# 已审批报告");
  });

  it("optimizes a generated report and renders the comparison", async () => {
    const user = userEvent.setup();
    render(<App />);

    await waitFor(() => expect(screen.getByRole("button", { name: "使用示例场景" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "使用示例场景" }));
    await user.click(screen.getByRole("button", { name: "生成控制方案 / Generate Control Plan" }));
    await user.type(screen.getByLabelText("优化要求"), "增加急停复位逻辑");
    await user.click(screen.getByRole("button", { name: "优化当前方案 / Optimize" }));

    expect(await screen.findByText("增加急停复位逻辑。")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "优化前" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "优化后" })).toBeInTheDocument();
    expect(optimizeControlPlan).toHaveBeenCalledWith({
      original_report: "# 旧响应报告",
      optimize_requirement: "增加急停复位逻辑",
      model_provider: "Ox Alpha",
    }, expect.objectContaining({ onStatus: expect.any(Function) }));
  });

  it("blocks report copying until a critical plan is manually reviewed", async () => {
    generateControlPlan.mockResolvedValueOnce({
      ...LEGACY_RESPONSE,
      plan_id: "plan-1",
      content_hash: "abc",
      safety_gate: {
        status: "review_required",
        review_required: true,
        export_allowed: false,
        reasons: ["方案包含 Critical 风险。"],
      },
    });
    const user = userEvent.setup();
    render(<App />);

    await waitFor(() => expect(screen.getByRole("button", { name: "使用示例场景" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "使用示例场景" }));
    await user.click(screen.getByRole("button", { name: "生成控制方案 / Generate Control Plan" }));

    expect(await screen.findByRole("heading", { name: "后端安全审批" })).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "方案报告" }));
    const copyButton = screen.getByRole("button", { name: "复制 Markdown" });
    expect(copyButton).toBeDisabled();

    expect(screen.getByLabelText("已验证审批身份")).toHaveTextContent("当前登录用户");
    await user.click(screen.getByLabelText("我已独立复核风险项；审批身份由登录凭证验证。"));
    await user.click(screen.getByRole("button", { name: "提交独立审批并解锁导出" }));

    expect(await screen.findByText("后端安全审批已记录")).toBeInTheDocument();
    expect(copyButton).toBeEnabled();
    expect(reviewPlan).toHaveBeenCalledWith(
      "plan-1",
      {
        decision: "approved",
        comment: "",
      },
    );
  });

  it("renders a legacy response without validation_report", async () => {
    const user = userEvent.setup();
    render(<App />);

    await waitFor(() => expect(screen.getByRole("button", { name: "使用示例场景" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "使用示例场景" }));
    await user.click(screen.getByRole("button", { name: "生成控制方案 / Generate Control Plan" }));

    expect(await screen.findByText("旧响应需求分析")).toBeInTheDocument();
    expect(screen.getByText("工程报告面板")).toBeInTheDocument();
    expect(screen.queryByText("规则校验与风险评估")).not.toBeInTheDocument();
  });
});
