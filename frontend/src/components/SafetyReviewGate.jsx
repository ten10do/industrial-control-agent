import { useState } from "react";
import { LockKeyhole, ShieldCheck, UserCheck } from "lucide-react";


function SafetyReviewGate({
  gate,
  approval,
  reviewerName = "当前登录用户",
  canReview = true,
  onApprove,
}) {
  const [comment, setComment] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  if (!gate?.review_required) {
    return null;
  }

  if (approval?.decision === "approved" && approval?.export_allowed) {
    return (
      <section className="panel safety-review-gate approved" role="status">
        <ShieldCheck size={21} aria-hidden="true" />
        <div>
          <strong>后端安全审批已记录</strong>
          <span>{approval.reviewer} · {new Date(approval.reviewed_at).toLocaleString()}</span>
        </div>
      </section>
    );
  }

  if (!canReview) {
    return (
      <section className="panel safety-review-gate" role="status">
        <div className="safety-review-title">
          <LockKeyhole size={21} aria-hidden="true" />
          <div>
            <h2>等待独立审批</h2>
            <p>当前账号没有 reviewer/admin 角色，不能审批此方案。</p>
          </div>
        </div>
      </section>
    );
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (!confirmed) {
      return;
    }
    setIsSubmitting(true);
    try {
      await onApprove({ comment: comment.trim() });
    } catch {
      // App owns the sanitized API error message and request ID.
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <section className="panel safety-review-gate" aria-labelledby="safety-review-heading">
      <div className="safety-review-title">
        <LockKeyhole size={21} aria-hidden="true" />
        <div>
          <h2 id="safety-review-heading">后端安全审批</h2>
          <p>当前版本在独立审批人批准前不能通过复制或下载接口导出。</p>
        </div>
      </div>
      <ul>
        {(gate.reasons || []).map((reason) => <li key={reason}>{reason}</li>)}
      </ul>
      <form onSubmit={handleSubmit}>
        <div className="verified-reviewer" aria-label="已验证审批身份">
          <UserCheck size={18} aria-hidden="true" />
          <span>已验证身份</span>
          <strong>{reviewerName}</strong>
        </div>
        <label>
          审批意见（可选）
          <textarea
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            maxLength={2000}
            rows={2}
            disabled={isSubmitting}
          />
        </label>
        <label className="safety-review-confirm">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
            disabled={isSubmitting}
          />
          我已独立复核风险项；审批身份由登录凭证验证。
        </label>
        <button
          className="button button-secondary"
          type="submit"
          disabled={isSubmitting || !confirmed}
        >
          {isSubmitting ? "正在提交审批" : "提交独立审批并解锁导出"}
        </button>
      </form>
    </section>
  );
}


export default SafetyReviewGate;
