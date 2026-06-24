import {
  Bot,
  CheckCircle2,
  CircleAlert,
  ClipboardList,
  Database,
  RefreshCw,
  Server,
} from "lucide-react";


const STATUS_META = {
  checking: { label: "正在检查", className: "status-checking" },
  online: { label: "连接正常", className: "status-online" },
  offline: { label: "未连接", className: "status-offline" },
};


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
          <Bot size={23} aria-hidden="true" />
        </div>
        <div>
          <strong>Control Agent</strong>
          <span>方案设计工作台</span>
        </div>
      </div>

      <section className="sidebar-section" aria-labelledby="scenario-heading">
        <div className="section-label" id="scenario-heading">
          <Database size={16} aria-hidden="true" />
          示例场景
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
            <p className="sidebar-empty">连接后端后加载示例</p>
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

      <section className="sidebar-section steps-section">
        <div className="section-label">
          <ClipboardList size={16} aria-hidden="true" />
          使用步骤
        </div>
        <ol className="steps-list">
          <li><span>1</span>选择示例或填写参数</li>
          <li><span>2</span>提交生成任务</li>
          <li><span>3</span>检查并复制方案报告</li>
        </ol>
      </section>

      <section className="backend-card" aria-label="后端连接状态">
        <div className="backend-card-title">
          <Server size={17} aria-hidden="true" />
          FastAPI 后端
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
            title="重新检查后端连接"
            aria-label="重新检查后端连接"
          >
            <RefreshCw size={15} aria-hidden="true" />
          </button>
        </div>
      </section>
    </aside>
  );
}


export default Sidebar;
