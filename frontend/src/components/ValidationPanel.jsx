import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, ShieldCheck } from "lucide-react";


const SEVERITY_ORDER = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
  info: 4,
};

const SEVERITY_LABELS = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
  info: "Info",
};

const STATUS_LABELS = {
  failed: "失败",
  warning: "警告",
  passed: "通过",
  not_applicable: "不适用",
};


function normalizedValue(value) {
  return typeof value === "string" ? value.trim().toLowerCase() : "";
}


function displayText(value, fallback = "—") {
  if (typeof value === "string" && value.trim()) {
    return value.trim();
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  if (Array.isArray(value)) {
    const text = value
      .filter((item) => typeof item === "string" || typeof item === "number")
      .map((item) => String(item).trim())
      .filter(Boolean)
      .join("；");
    return text || fallback;
  }
  return fallback;
}


function numericValue(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}


function relatedItems(value) {
  const values = Array.isArray(value) ? value : [value];
  return values
    .filter((item) => typeof item === "string" || typeof item === "number")
    .map((item) => String(item).trim())
    .filter(Boolean);
}


function isRuleResult(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}


function ValidationPanel({ report }) {
  const [severityFilter, setSeverityFilter] = useState("all");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [showNotApplicable, setShowNotApplicable] = useState(false);

  const ruleResults = useMemo(
    () => (Array.isArray(report?.rule_results) ? report.rule_results.filter(isRuleResult) : []),
    [report],
  );

  const issues = useMemo(() => {
    if (Array.isArray(report?.issues)) {
      return report.issues.filter(isRuleResult);
    }
    return ruleResults.filter((rule) => {
      const status = normalizedValue(rule.status);
      return status === "failed" || status === "warning";
    });
  }, [report, ruleResults]);

  const notApplicableRules = useMemo(
    () => ruleResults.filter((rule) => normalizedValue(rule.status) === "not_applicable"),
    [ruleResults],
  );

  const availableRules = useMemo(() => {
    const rules = [...issues];
    if (showNotApplicable) {
      const existingRuleIds = new Set(rules.map((rule) => displayText(rule.rule_id, "")));
      notApplicableRules.forEach((rule) => {
        const ruleId = displayText(rule.rule_id, "");
        if (!ruleId || !existingRuleIds.has(ruleId)) {
          rules.push(rule);
        }
      });
    }
    return rules.filter(
      (rule) => showNotApplicable || normalizedValue(rule.status) !== "not_applicable",
    );
  }, [issues, notApplicableRules, showNotApplicable]);

  const categories = useMemo(
    () => Array.from(
      new Set(
        [...issues, ...notApplicableRules]
          .map((rule) => displayText(rule.category, ""))
          .filter(Boolean),
      ),
    ).sort((left, right) => left.localeCompare(right)),
    [issues, notApplicableRules],
  );

  const effectiveCategory = categoryFilter === "all" || categories.includes(categoryFilter)
    ? categoryFilter
    : "all";

  const visibleRules = useMemo(
    () => availableRules
      .map((rule, index) => ({ rule, index }))
      .filter(({ rule }) => {
        const severityMatches = severityFilter === "all"
          || normalizedValue(rule.severity) === severityFilter;
        const categoryMatches = effectiveCategory === "all"
          || displayText(rule.category, "") === effectiveCategory;
        return severityMatches && categoryMatches;
      })
      .sort((left, right) => {
        const leftRank = SEVERITY_ORDER[normalizedValue(left.rule.severity)] ?? 99;
        const rightRank = SEVERITY_ORDER[normalizedValue(right.rule.severity)] ?? 99;
        return leftRank - rightRank || left.index - right.index;
      })
      .map(({ rule }) => rule),
    [availableRules, effectiveCategory, severityFilter],
  );

  const riskLevel = normalizedValue(report?.risk_level) || "unknown";
  const validationStatus = normalizedValue(report?.validation_status) || "complete";
  const validationIncomplete = validationStatus !== "complete";
  const riskTone = riskLevel === "low"
    ? validationIncomplete ? "warning" : "success"
    : riskLevel === "medium"
      ? "warning"
      : "danger";
  const hasIssues = issues.some((rule) => {
    const status = normalizedValue(rule.status);
    return status === "failed" || status === "warning";
  });

  const summaryItems = [
    { label: "风险等级", value: riskLevel.toUpperCase(), tone: riskTone },
    { label: "风险分数", value: numericValue(report?.risk_score), tone: riskTone },
    { label: "总规则", value: numericValue(report?.total_rules) },
    { label: "通过", value: numericValue(report?.passed_rules), tone: "success" },
    { label: "警告", value: numericValue(report?.warning_rules), tone: "warning" },
    { label: "失败", value: numericValue(report?.failed_rules), tone: "danger" },
    { label: "Critical", value: numericValue(report?.critical_count), tone: "danger" },
    { label: "High", value: numericValue(report?.high_count), tone: "warning" },
  ];

  return (
    <section className="panel validation-panel" aria-labelledby="validation-heading">
      <div className="panel-heading validation-heading">
        <div>
          <p className="panel-kicker">DETERMINISTIC RULE VALIDATION</p>
          <h2 id="validation-heading">规则校验与风险评估</h2>
        </div>
        <span className={`validation-risk-badge ${riskTone}`}>
          <ShieldCheck size={16} aria-hidden="true" />
          {riskLevel.toUpperCase()}
        </span>
      </div>

      <div className="validation-summary" aria-label="风险评估汇总">
        {summaryItems.map((item) => (
          <div className={`validation-metric ${item.tone || ""}`} key={item.label}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        ))}
      </div>

      <div className="validation-controls">
        <label>
          严重程度
          <select
            value={severityFilter}
            onChange={(event) => setSeverityFilter(event.target.value)}
          >
            <option value="all">全部</option>
            {Object.entries(SEVERITY_LABELS).map(([value, label]) => (
              <option value={value} key={value}>{label}</option>
            ))}
          </select>
        </label>

        <label>
          类别
          <select
            value={effectiveCategory}
            onChange={(event) => setCategoryFilter(event.target.value)}
          >
            <option value="all">全部</option>
            {categories.map((category) => (
              <option value={category} key={category}>{category}</option>
            ))}
          </select>
        </label>

        <label className="validation-checkbox">
          <input
            type="checkbox"
            checked={showNotApplicable}
            onChange={(event) => setShowNotApplicable(event.target.checked)}
          />
          显示不适用规则
        </label>
      </div>

      {validationIncomplete && (
        <div className="validation-empty" role="status">
          <AlertTriangle size={20} aria-hidden="true" />
          <div>
            <strong>规则校验未完整执行</strong>
            <span>
              当前状态：{validationStatus}。请结合下方结果进行人工复核。
            </span>
          </div>
        </div>
      )}

      {!hasIssues && !validationIncomplete && (
        <div className="validation-empty success" role="status">
          <CheckCircle2 size={20} aria-hidden="true" />
          <div>
            <strong>规则校验通过</strong>
            <span>未发现需要处理的警告或失败规则。</span>
          </div>
        </div>
      )}

      {hasIssues && visibleRules.length === 0 && (
        <div className="validation-empty" role="status">
          <AlertTriangle size={20} aria-hidden="true" />
          <div>
            <strong>当前筛选条件下无匹配问题</strong>
            <span>可调整严重程度、类别或不适用规则选项。</span>
          </div>
        </div>
      )}

      {visibleRules.length > 0 && (
        <div className="validation-rule-list">
          {visibleRules.map((rule, index) => {
            const severity = normalizedValue(rule.severity);
            const status = normalizedValue(rule.status);
            const severityClass = Object.hasOwn(SEVERITY_ORDER, severity) ? severity : "info";
            const items = relatedItems(rule.related_items);

            return (
              <article
                className={`validation-rule severity-${severityClass}`}
                key={`${displayText(rule.rule_id, "rule")}-${index}`}
              >
                <div className="validation-rule-heading">
                  <div>
                    <strong>{displayText(rule.rule_name, "未命名规则")}</strong>
                    <code>{displayText(rule.rule_id, "UNKNOWN_RULE")}</code>
                  </div>
                  <div className="validation-badges">
                    <span className={`severity-badge ${severityClass}`}>
                      {SEVERITY_LABELS[severity] || "Info"}
                    </span>
                    <span className={`status-badge ${status || "unknown"}`}>
                      {STATUS_LABELS[status] || "未知"}
                    </span>
                  </div>
                </div>

                <dl className="validation-rule-details">
                  <div>
                    <dt>类别</dt>
                    <dd>{displayText(rule.category)}</dd>
                  </div>
                  <div>
                    <dt>问题描述</dt>
                    <dd>{displayText(rule.message)}</dd>
                  </div>
                  <div>
                    <dt>证据</dt>
                    <dd>{displayText(rule.evidence)}</dd>
                  </div>
                  <div>
                    <dt>修改建议</dt>
                    <dd>{displayText(rule.recommendation)}</dd>
                  </div>
                </dl>

                {items.length > 0 && (
                  <div className="validation-related">
                    <span>相关设备或点位</span>
                    <div>
                      {items.map((item) => <code key={item}>{item}</code>)}
                    </div>
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}

      {displayText(report?.request_id, "") && (
        <small className="validation-request-id">
          Request ID: {displayText(report.request_id)}
        </small>
      )}
    </section>
  );
}


export default ValidationPanel;
