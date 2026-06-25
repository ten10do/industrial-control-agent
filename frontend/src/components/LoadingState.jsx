import { Cpu } from "lucide-react";


function LoadingState() {
  return (
    <section className="panel loading-state" aria-live="polite" aria-busy="true">
      <div className="loading-icon">
        <Cpu size={28} aria-hidden="true" />
      </div>
      <div>
        <h2>Agent 正在生成控制方案</h2>
        <p>正在分析控制需求、规划 PLC I/O 点位、整理安全联锁与梯形图设计思路，请稍候。</p>
        <div className="loading-track"><span /></div>
      </div>
    </section>
  );
}


export default LoadingState;
