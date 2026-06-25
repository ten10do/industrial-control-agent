import {
  Bot,
  CheckCircle2,
  CircleAlert,
  ClipboardList,
  Cpu,
  Database,
  RefreshCw,
  Route,
  Server,
  ShieldCheck,
} from "lucide-react";


const STATUS_META = {
  checking: { label: "正在检测", className: "status-checking" },
  online: { label: "连接正常", className: "status-online" },
  offline: { label: "未连接", className: "status-offline" },
};

const NAV_ITEMS = [
  { label: "场景模板", icon: Database },
  { label: "控制对象", icon: Cpu },
  { label: "I/O 设备", icon: Route },
  { label: "控制要求", icon: ClipboardList },
  { label: "生成方案", icon: Bot },
  { label: "安全复核", icon: ShieldCheck },
];


function Sidebar({
  examples,
  selectedExampleName,
  onSelectExample,
  modelProvider,
  onModelProviderChange,
  backendStatus,
  onRefreshBackend,
}) {
  const status = STATUS_META[backendStatus];

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="sidebar-brand-icon">
          <Cpu size={23} aria-hidden="true" />
        </div>
        <div>
          <strong>PLC Workstation</strong>
          <span>控制方案配置台</span>
        </div>
      </div>

      <section className="sidebar-section compact-nav" aria-label="工控导航面板">
        {NAV_ITEMS.map(({ label, icon: Icon }) => (
          <div className="nav-node" key={label}>
            <Icon size={15} aria-hidden="true" />
            <span>{label}</span>
          </div>
        ))}
      </section>

      <section className="sidebar-section" aria-labelledby="scenario-heading">
        <div className="section-label" id="scenario-heading">
          <Database size={16} aria-hidden="true" />
          场景模板
        </div>
        <div className="scenario-list">
          {examples.length > 0 ? (
            examples.map((example) => (
              <button
                type="button"
                className={`scenario-item ${
                  example.name === selectedExampleName ? "is-selected" : ""
                }`}
                key={example.name}
                onClick={() => onSelectExample(example.name)}
              >
                <span>{example.name}</span>
                {example.name === selectedExampleName && (
                  <CheckCircle2 size={16} aria-hidden="true" />
                )}
              </button>
            ))
          ) : (
            <p className="sidebar-empty">连接后端后加载示例场景</p>
          )}
        </div>
      </section>

      <section className="sidebar-section">
        <label className="section-label" htmlFor="model-provider">
          <Bot size={16} aria-hidden="true" />
          模型服务
        </label>
        <select
          id="model-provider"
          className="sidebar-select"
          value={modelProvider}
          onChange={(event) => onModelProviderChange(event.target.value)}
        >
          <option value="DeepSeek">DeepSeek</option>
        </select>
      </section>

      <section className="backend-card" aria-label="后端连接状态">
        <div className="backend-card-title">
          <Server size={17} aria-hidden="true" />
          FastAPI Backend
        </div>
        <div className={`backend-status ${status.className}`}>
          {backendStatus === "offline" ? (
            <CircleAlert size={16} aria-hidden="true" />
          ) : (
            <span className="status-dot" aria-hidden="true" />
          )}
          <span>{status.label}</span>
          <button
            className="icon-button"
            type="button"
            onClick={onRefreshBackend}
            title="重新检测后端连接"
            aria-label="重新检测后端连接"
          >
            <RefreshCw size={15} aria-hidden="true" />
          </button>
        </div>
      </section>
    </aside>
  );
}


export default Sidebar;
