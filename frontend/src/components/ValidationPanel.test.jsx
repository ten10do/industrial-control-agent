import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import ValidationPanel from "./ValidationPanel";


function buildRule({
  ruleId,
  ruleName,
  severity,
  category,
  status = "failed",
}) {
  return {
    rule_id: ruleId,
    rule_name: ruleName,
    severity,
    category,
    status,
    message: `${ruleName}问题`,
    evidence: `${ruleName}证据`,
    recommendation: `${ruleName}建议`,
    related_items: [],
  };
}


function buildReport() {
  const criticalRule = buildRule({
    ruleId: "CRITICAL_RULE",
    ruleName: "Critical 规则",
    severity: "critical",
    category: "安全联锁",
  });
  const highRule = buildRule({
    ruleId: "HIGH_RULE",
    ruleName: "High 规则",
    severity: "high",
    category: "设备保护",
    status: "warning",
  });
  const mediumRule = buildRule({
    ruleId: "MEDIUM_RULE",
    ruleName: "Medium 规则",
    severity: "medium",
    category: "安全联锁",
  });
  const notApplicableRule = buildRule({
    ruleId: "NA_RULE",
    ruleName: "不适用规则",
    severity: "high",
    category: "设备保护",
    status: "not_applicable",
  });

  return {
    request_id: "frontend-test",
    validation_status: "complete",
    risk_score: 53,
    risk_level: "critical",
    total_rules: 4,
    passed_rules: 0,
    warning_rules: 1,
    failed_rules: 2,
    not_applicable_rules: 1,
    critical_count: 1,
    high_count: 1,
    issues: [mediumRule, highRule, criticalRule],
    rule_results: [mediumRule, highRule, criticalRule, notApplicableRule],
  };
}


describe("ValidationPanel", () => {
  it("shows the not-applicable count while hiding N/A details by default", async () => {
    const user = userEvent.setup();
    render(<ValidationPanel report={buildReport()} />);

    const summary = screen.getByLabelText("风险评估汇总");
    expect(within(summary).getByText("不适用").parentElement).toHaveTextContent("1");
    expect(screen.queryByText("NA_RULE")).not.toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "显示不适用规则" }));

    expect(screen.getByText("NA_RULE")).toBeInTheDocument();
  });

  it("sorts issues by severity and supports severity and category filters", async () => {
    const user = userEvent.setup();
    render(<ValidationPanel report={buildReport()} />);

    expect(screen.getAllByRole("article").map((article) => (
      within(article).getByText(/_RULE$/).textContent
    ))).toEqual(["CRITICAL_RULE", "HIGH_RULE", "MEDIUM_RULE"]);

    await user.selectOptions(screen.getByRole("combobox", { name: "严重程度" }), "high");
    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(screen.getByText("HIGH_RULE")).toBeInTheDocument();

    await user.selectOptions(screen.getByRole("combobox", { name: "严重程度" }), "all");
    await user.selectOptions(screen.getByRole("combobox", { name: "类别" }), "安全联锁");
    expect(screen.getAllByRole("article").map((article) => (
      within(article).getByText(/_RULE$/).textContent
    ))).toEqual(["CRITICAL_RULE", "MEDIUM_RULE"]);
  });

  it("shows an unavailable validation as not evaluated", () => {
    render(
      <ValidationPanel
        report={{
          validation_status: "unavailable",
          risk_level: "unknown",
          risk_score: 0,
          total_rules: 0,
          passed_rules: 0,
          warning_rules: 0,
          failed_rules: 0,
          not_applicable_rules: 0,
          critical_count: 0,
          high_count: 0,
          issues: [],
          rule_results: [],
        }}
      />,
    );

    expect(screen.getAllByText("未评估")).toHaveLength(2);
    expect(screen.getByText("规则校验未完整执行")).toBeInTheDocument();
  });
});
