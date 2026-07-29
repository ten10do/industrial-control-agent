import { useState } from "react";
import { RefreshCw, Sparkles } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import ReportPreview from "./ReportPreview";
import SafetyReviewGate from "./SafetyReviewGate";
import ValidationPanel from "./ValidationPanel";


function OptimizationPanel({
  originalReport,
  optimization,
  approval,
  reviewerName,
  isOptimizing,
  onOptimize,
  onApprove,
  loadExport,
}) {
  const [requirement, setRequirement] = useState("");

  function handleSubmit(event) {
    event.preventDefault();
    const normalizedRequirement = requirement.trim();
    if (normalizedRequirement) {
      onOptimize(normalizedRequirement);
    }
  }

  const exportAllowed = (
    optimization?.safety_gate?.export_allowed !== false
    || Boolean(approval?.export_allowed)
  );

  return (
    <>
      <section className="panel optimization-panel" aria-labelledby="optimization-heading">
        <div className="panel-heading">
          <div>
            <p className="panel-kicker">CONTROL PLAN OPTIMIZATION</p>
            <h2 id="optimization-heading">方案优化与版本对比</h2>
          </div>
          <Sparkles size={21} aria-hidden="true" />
        </div>

        <form onSubmit={handleSubmit}>
          <label className="field-group">
            <span className="field-label">优化要求</span>
            <textarea
              value={requirement}
              onChange={(event) => setRequirement(event.target.value)}
              placeholder="例如：补充急停复位、过载保护和调试验收步骤"
              rows={3}
              maxLength={10000}
              disabled={isOptimizing}
            />
          </label>
          <button
            className="button button-secondary"
            type="submit"
            disabled={isOptimizing || !requirement.trim()}
          >
            <RefreshCw size={17} aria-hidden="true" />
            {isOptimizing ? "正在优化 / Optimizing" : "优化当前方案 / Optimize"}
          </button>
        </form>

        {optimization && (
          <>
            <div className="optimization-summary">
              <strong>变更摘要</strong>
              <p>{optimization.change_summary}</p>
            </div>
            <div className="optimization-compare" aria-label="优化前后方案对比">
              <article>
                <h3>优化前</h3>
                <div className="markdown-body">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{originalReport}</ReactMarkdown>
                </div>
              </article>
              <article>
                <h3>优化后</h3>
                <div className="markdown-body">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {optimization.optimized_report}
                  </ReactMarkdown>
                </div>
              </article>
            </div>
          </>
        )}
      </section>

      {optimization?.validation_report && (
        <ValidationPanel report={optimization.validation_report} />
      )}
      <SafetyReviewGate
        gate={optimization?.safety_gate}
        approval={approval}
        reviewerName={reviewerName}
        onApprove={onApprove}
      />
      {optimization?.optimized_report && (
        <section className="panel result-panel" aria-label="优化版本导出">
          <ReportPreview
            markdown={optimization.optimized_report}
            safetyNotice={optimization.safety_notice}
            exportAllowed={exportAllowed}
            loadExport={loadExport}
            downloadName={`control-plan-${optimization.plan_id || "optimized"}.md`}
          />
        </section>
      )}
    </>
  );
}


export default OptimizationPanel;
