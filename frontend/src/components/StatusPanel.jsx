import { Cable, CheckCircle2, Radar, ShieldCheck } from "lucide-react";


function StatusCard({ icon: Icon, label, value, tone = "neutral" }) {
  return (
    <div className={`metric-card ${tone}`}>
      <div className="metric-icon" aria-hidden="true">
        <Icon size={18} />
      </div>
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
    </div>
  );
}


function StatusPanel({ backendStatus, selectedExampleName, hasInput, hasResult }) {
  const apiValue = backendStatus === "online"
    ? "Online"
    : backendStatus === "checking"
      ? "Checking"
      : "Offline";

  return (
    <section className="status-panel" aria-label="任务状态概览">
      <StatusCard
        icon={Radar}
        label="API Status"
        value={apiValue}
        tone={backendStatus === "online" ? "success" : backendStatus === "offline" ? "danger" : "warning"}
      />
      <StatusCard
        icon={CheckCircle2}
        label="Scenario Loaded"
        value={selectedExampleName || "Manual Input"}
        tone={selectedExampleName ? "success" : "neutral"}
      />
      <StatusCard
        icon={Cable}
        label="I/O Mapping"
        value={hasInput ? "Configured" : "Pending"}
        tone={hasInput ? "success" : "neutral"}
      />
      <StatusCard
        icon={ShieldCheck}
        label="Safety Review"
        value={hasResult ? "Included" : "Required"}
        tone={hasResult ? "success" : "warning"}
      />
    </section>
  );
}


export default StatusPanel;
