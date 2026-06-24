import { Eraser, FileInput, Play } from "lucide-react";


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
          <p className="panel-kicker">DESIGN INPUT</p>
          <h2 id="form-heading">控制系统参数</h2>
        </div>
        <span className="required-hint">所有字段均为必填项</span>
      </div>

      <form onSubmit={onSubmit}>
        <div className="form-grid">
          <label className="field-group">
            <span>控制对象</span>
            <input
              type="text"
              value={formData.control_object}
              onChange={(event) => onFieldChange("control_object", event.target.value)}
              placeholder="例如：水塔及补水泵"
              disabled={isLoading}
            />
          </label>

          <label className="field-group">
            <span>输入设备</span>
            <textarea
              value={formData.input_devices}
              onChange={(event) => onFieldChange("input_devices", event.target.value)}
              placeholder="传感器、按钮、限位开关、故障反馈等"
              rows={4}
              disabled={isLoading}
            />
          </label>

          <label className="field-group">
            <span>输出设备</span>
            <textarea
              value={formData.output_devices}
              onChange={(event) => onFieldChange("output_devices", event.target.value)}
              placeholder="电机、接触器、电磁阀、指示灯、报警器等"
              rows={4}
              disabled={isLoading}
            />
          </label>

          <label className="field-group">
            <span>控制要求</span>
            <textarea
              value={formData.control_requirements}
              onChange={(event) => onFieldChange("control_requirements", event.target.value)}
              placeholder="描述启停条件、顺序控制、安全联锁和异常处理要求"
              rows={4}
              disabled={isLoading}
            />
          </label>
        </div>

        <div className="form-actions">
          <button className="button button-primary" type="submit" disabled={isLoading}>
            <Play size={17} fill="currentColor" aria-hidden="true" />
            {isLoading ? "正在生成" : "生成控制方案"}
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
