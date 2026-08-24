import { Cpu } from "lucide-react";


const STATUS_LABELS = {
  queued: "已进入队列",
  running: "模型正在执行",
  cancel_requested: "正在取消",
};


function LoadingState({ job = null, onCancel, title = "Agent 正在生成控制方案" }) {
  const canCancel = job && ["queued", "running"].includes(job.status);
  return (
    <section className="panel loading-state" aria-live="polite" aria-busy="true">
      <div className="loading-icon">
        <Cpu size={28} aria-hidden="true" />
      </div>
      <div>
        <h2>{title}</h2>
        <p>
          {job
            ? `${STATUS_LABELS[job.status] || job.status} · 第 ${job.attempts}/${job.max_attempts} 次尝试 · ${job.progress}%`
            : "正在创建可恢复的后台任务，请稍候。"}
        </p>
        <div className="loading-track"><span /></div>
        {canCancel && (
          <button className="button button-secondary job-cancel" type="button" onClick={onCancel}>
            取消任务
          </button>
        )}
      </div>
    </section>
  );
}


export default LoadingState;
