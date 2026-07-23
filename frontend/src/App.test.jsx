import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { checkHealth, fetchExamples, generateControlPlan } from "./api";


vi.mock("./api", () => ({
  checkHealth: vi.fn(),
  fetchExamples: vi.fn(),
  generateControlPlan: vi.fn(),
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
    fetchExamples.mockResolvedValue({ examples: [EXAMPLE] });
    generateControlPlan.mockResolvedValue(LEGACY_RESPONSE);
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
