import { ClipboardList, RefreshCw } from "lucide-react";


function statusLabel(plan) {
  if (!plan.review_required) {
    return "无需审批";
  }
  if (plan.export_allowed) {
    return "已批准";
  }
  if (plan.latest_decision === "rejected") {
    return "已驳回";
  }
  return "待审批";
}


function PlanInbox({ plans, isLoading, selectedPlanId, onSelect, onRefresh }) {
  return (
    <section className="panel plan-inbox" aria-labelledby="plan-inbox-heading">
      <div className="panel-heading">
        <div>
          <p className="panel-kicker">ROLE-SCOPED PLAN INBOX</p>
          <h2 id="plan-inbox-heading">方案与审批收件箱</h2>
        </div>
        <button
          className="button button-secondary button-compact"
          type="button"
          onClick={onRefresh}
          disabled={isLoading}
        >
          <RefreshCw size={16} aria-hidden="true" />
          刷新
        </button>
      </div>
      {plans.length ? (
        <div className="plan-inbox-list">
          {plans.map((plan) => (
            <button
              type="button"
              className={selectedPlanId === plan.plan_id ? "is-active" : ""}
              key={plan.plan_id}
              onClick={() => onSelect(plan.plan_id)}
            >
              <ClipboardList size={18} aria-hidden="true" />
              <span>
                <strong>{plan.source === "optimize" ? "优化版本" : "生成版本"}</strong>
                <small>
                  {plan.created_by_name || "历史方案"} · {new Date(plan.created_at).toLocaleString()}
                </small>
              </span>
              <em>{statusLabel(plan)}</em>
            </button>
          ))}
        </div>
      ) : (
        <p className="plan-inbox-empty">
          {isLoading ? "正在加载方案…" : "当前角色范围内暂无方案。"}
        </p>
      )}
    </section>
  );
}


export default PlanInbox;
