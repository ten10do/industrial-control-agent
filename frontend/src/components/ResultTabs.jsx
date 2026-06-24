import { useEffect, useState } from "react";
import {
  Binary,
  FileText,
  ListChecks,
  Network,
  ShieldAlert,
  Table2,
} from "lucide-react";

import ReportPreview from "./ReportPreview";


const TABS = [
  { key: "requirement_analysis", label: "需求分析", icon: ListChecks },
  { key: "io_table", label: "PLC I/O 点表", icon: Table2 },
  { key: "control_logic", label: "控制逻辑", icon: Network },
  { key: "safety_design", label: "安全保护", icon: ShieldAlert },
  { key: "ladder_idea", label: "梯形图思路", icon: Binary },
  { key: "report_markdown", label: "完整报告", icon: FileText },
];


function IOTable({ rows }) {
  return (
    <div className="table-scroll">
      <table className="io-table">
        <thead>
          <tr>
            <th>地址</th>
            <th>信号名称</th>
            <th>类型</th>
            <th>设备</th>
            <th>功能说明</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={`${row.address}-${row.signal_name}-${index}`}>
              <td><code>{row.address}</code></td>
              <td>{row.signal_name}</td>
              <td><span className="signal-type">{row.signal_type}</span></td>
              <td>{row.device}</td>
              <td>{row.description}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}


function ResultTabs({ result }) {
  const [activeTab, setActiveTab] = useState(TABS[0].key);

  useEffect(() => {
    if (result) {
      setActiveTab(TABS[0].key);
    }
  }, [result]);

  if (!result) {
    return (
      <section className="panel empty-result" aria-label="控制方案结果">
        <div className="empty-result-icon"><FileText size={27} aria-hidden="true" /></div>
        <h2>等待生成控制方案</h2>
        <p>完成参数输入后，Agent 生成的需求分析、I/O 点表和完整报告将在这里展示。</p>
      </section>
    );
  }

  return (
    <section className="panel result-panel" aria-labelledby="result-heading">
      <div className="panel-heading result-heading">
        <div>
          <p className="panel-kicker">AGENT OUTPUT</p>
          <h2 id="result-heading">控制方案生成结果</h2>
        </div>
        <span className="result-status">生成完成</span>
      </div>

      <div className="tabs" role="tablist" aria-label="控制方案结果分类">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            type="button"
            role="tab"
            aria-selected={activeTab === key}
            className={`tab-button ${activeTab === key ? "is-active" : ""}`}
            key={key}
            onClick={() => setActiveTab(key)}
          >
            <Icon size={16} aria-hidden="true" />
            {label}
          </button>
        ))}
      </div>

      <div className="tab-content" role="tabpanel">
        {activeTab === "io_table" && <IOTable rows={result.io_table ?? []} />}
        {activeTab === "report_markdown" && (
          <ReportPreview
            markdown={result.report_markdown}
            safetyNotice={result.safety_notice}
          />
        )}
        {activeTab !== "io_table" && activeTab !== "report_markdown" && (
          <div className="text-result">{result[activeTab]}</div>
        )}
      </div>
    </section>
  );
}


export default ResultTabs;
