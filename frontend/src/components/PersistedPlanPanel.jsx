import { History, X } from "lucide-react";

import ReportPreview from "./ReportPreview";
import SafetyReviewGate from "./SafetyReviewGate";


function PersistedPlanPanel({
  plan,
  approval,
  audit,
  canReview,
  reviewerName,
  onApprove,
  onClose,
  onRefreshAudit,
  loadExport,
}) {
  if (!plan) {
    return null;
  }
  const gate = plan.response?.safety_gate || {
    status: plan.review_required ? "review_required" : "advisory",
    review_required: plan.review_required,
    export_allowed: plan.export_allowed,
    reasons: plan.review_required ? ["该版本需要独立安全审批。"] : [],
  };
  const exportAllowed = plan.export_allowed || Boolean(approval?.export_allowed);

  return (
    <section className="persisted-plan-workspace" aria-labelledby="persisted-plan-heading">
      <div className="panel persisted-plan-meta">
        <div>
          <p className="panel-kicker">PERSISTED PLAN VERSION</p>
          <h2 id="persisted-plan-heading">
            {plan.source === "optimize" ? "优化方案版本" : "生成方案版本"}
          </h2>
          <p>
            创建人：{plan.created_by_name || "历史数据"} ·
            内容哈希：<code>{plan.content_hash}</code>
          </p>
        </div>
        <button
          className="button button-ghost button-compact"
          type="button"
          onClick={onClose}
        >
          <X size={16} aria-hidden="true" />
          关闭
        </button>
      </div>

      <SafetyReviewGate
        gate={gate}
        approval={approval}
        reviewerName={reviewerName}
        canReview={canReview}
        onApprove={onApprove}
      />

      <section className="panel result-panel" aria-label="持久化方案导出">
        <ReportPreview
          markdown={plan.report_markdown}
          safetyNotice={plan.response?.safety_notice || "实际使用前必须完成工程复核。"}
          exportAllowed={exportAllowed}
          loadExport={loadExport}
          downloadName={`control-plan-${plan.plan_id}.md`}
        />
      </section>

      <section className="panel audit-trail" aria-labelledby="audit-trail-heading">
        <div className="panel-heading">
          <div>
            <p className="panel-kicker">TAMPER-EVIDENT AUDIT</p>
            <h2 id="audit-trail-heading">审计轨迹</h2>
          </div>
          <button
            className="button button-secondary button-compact"
            type="button"
            onClick={onRefreshAudit}
          >
            <History size={16} aria-hidden="true" />
            验证并刷新
          </button>
        </div>
        {audit ? (
          <>
            <div className={`audit-chain-status ${audit.chain_valid ? "valid" : "invalid"}`}>
              哈希链：{audit.chain_valid ? "验证通过" : "验证失败"}
            </div>
            <ol>
              {audit.events.map((event) => (
                <li key={event.event_id}>
                  <strong>{event.action}</strong>
                  <span>{event.actor_name} · {new Date(event.created_at).toLocaleString()}</span>
                  <code>{event.event_hash}</code>
                </li>
              ))}
            </ol>
          </>
        ) : (
          <p>点击“验证并刷新”读取审计轨迹。</p>
        )}
      </section>
    </section>
  );
}


export default PersistedPlanPanel;
