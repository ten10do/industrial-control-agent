import { Activity, Bot, Factory, Gauge, LogOut, UserRound } from "lucide-react";


const STATUS_LABELS = {
  checking: "Checking",
  online: "Online",
  offline: "Offline",
};


function IndustrialHeader({
  backendStatus,
  modelProvider,
  authEnabled = false,
  userName = "",
  onLogout,
}) {
  return (
    <header className="industrial-header">
      <div className="header-brand">
        <div className="header-emblem" aria-hidden="true">
          <Factory size={25} />
        </div>
        <div>
          <h1>工业控制方案设计 Agent 系统</h1>
          <p>Industrial Control Design Agent</p>
        </div>
      </div>

      <div className="header-status-grid" aria-label="系统状态">
        <div className={`header-status ${backendStatus}`}>
          <Activity size={16} aria-hidden="true" />
          <span>Backend</span>
          <strong>{STATUS_LABELS[backendStatus] || "Unknown"}</strong>
        </div>
        <div className="header-status online">
          <Bot size={16} aria-hidden="true" />
          <span>Model</span>
          <strong>{modelProvider}</strong>
        </div>
        <div className="header-status mode">
          <Gauge size={16} aria-hidden="true" />
          <span>Mode</span>
          <strong>Design Assistant</strong>
        </div>
        {authEnabled && userName && (
          <div className="header-status identity">
            <UserRound size={16} aria-hidden="true" />
            <span>Identity</span>
            <strong>{userName}</strong>
            <button type="button" onClick={onLogout} aria-label="退出登录">
              <LogOut size={15} aria-hidden="true" />
            </button>
          </div>
        )}
      </div>
    </header>
  );
}


export default IndustrialHeader;
