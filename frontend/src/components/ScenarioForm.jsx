import { Eraser, FileInput, Play } from "lucide-react";


const FIELDS = [
  {
    id: "01",
    key: "control_object",
    label: "控制对象",
    type: "input",
    placeholder: "例如：水塔补水泵、自动门、电机正反转回路",
  },
  {
    id: "02",
    key: "input_devices",
    label: "输入设备",
    placeholder: "传感器、按钮、限位开关、急停、故障反馈等",
  },
  {
    id: "03",
    key: "output_devices",
    label: "输出设备",
    placeholder: "电机、接触器、电磁阀、指示灯、报警器等",
  },
  {
    id: "04",
    key: "control_requirements",
    label: "控制要求",
    placeholder: "描述启停条件、顺序控制、安全联锁、异常处理和调试要求",
  },
];


function ScenarioForm({
  formData,
  onFieldChange,
  onSubmit,
  onClear,
  onUseExample,
  selectedExampleName,
  isLoading,
}) {
  return (
    <section className="panel form-panel" aria-labelledby="form-heading">
      <div className="panel-heading">
        <div>
          <p className="panel-kicker">CONTROL TASK CONFIGURATION</p>
          <h2 id="form-heading">控制任务配置面板</h2>
        </div>
        <span className="required-hint">所有字段均为必填项</span>
      </div>

      <form onSubmit={onSubmit}>
        <div className="form-grid">
          {FIELDS.map((field) => (
            <label className="field-group" key={field.key}>
              <span className="field-label">
                <b>{field.id}</b>
                {field.label}
              </span>
              {field.type === "input" ? (
                <input
                  type="text"
                  value={formData[field.key]}
                  onChange={(event) => onFieldChange(field.key, event.target.value)}
                  placeholder={field.placeholder}
                  disabled={isLoading}
                />
              ) : (
                <textarea
                  value={formData[field.key]}
                  onChange={(event) => onFieldChange(field.key, event.target.value)}
                  placeholder={field.placeholder}
                  rows={4}
                  disabled={isLoading}
                />
              )}
            </label>
          ))}
        </div>

        <div className="form-actions">
          <button className="button button-primary" type="submit" disabled={isLoading}>
            <Play size={17} fill="currentColor" aria-hidden="true" />
            {isLoading ? "正在生成 / Running" : "生成控制方案 / Generate Control Plan"}
          </button>
          <button
            className="button button-secondary"
            type="button"
            onClick={onUseExample}
            disabled={isLoading || !selectedExampleName}
          >
            <FileInput size={17} aria-hidden="true" />
            使用示例场景
          </button>
          <button
            className="button button-ghost"
            type="button"
            onClick={onClear}
            disabled={isLoading}
          >
            <Eraser size={17} aria-hidden="true" />
            清空输入
          </button>
        </div>
      </form>
    </section>
  );
}


export default ScenarioForm;
