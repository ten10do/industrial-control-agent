from datetime import datetime
from typing import Dict, List


REQUIRED_FIELDS = {
    "control_object": "控制对象",
    "control_goal": "控制目标",
    "input_signals": "输入信号",
    "output_devices": "输出设备",
    "control_requirements": "控制要求",
    "safety_requirements": "安全保护要求",
}


def collect_user_inputs(state: dict) -> Dict[str, object]:
    return {
        "control_object": str(state.get("control_object", "")).strip(),
        "control_goal": str(state.get("control_goal", "")).strip(),
        "input_signals": str(state.get("input_signals", "")).strip(),
        "output_devices": str(state.get("output_devices", "")).strip(),
        "control_requirements": str(state.get("control_requirements", "")).strip(),
        "safety_requirements": str(state.get("safety_requirements", "")).strip(),
        "include_plc_design": bool(state.get("include_plc_design", True)),
        "include_debug_steps": bool(state.get("include_debug_steps", True)),
    }


def validate_inputs(inputs: dict) -> List[str]:
    errors = []
    for key, label in REQUIRED_FIELDS.items():
        if not inputs.get(key):
            errors.append(f"请填写：{label}")
    return errors


def build_markdown_report(inputs: dict, results: dict) -> str:
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    final_report = results.get("final_report", "")

    return f"""# 基于大模型的工业控制方案设计 Agent 报告

生成时间：{generated_at}

## 用户输入

| 字段 | 内容 |
| --- | --- |
| 控制对象 | {inputs.get("control_object", "")} |
| 控制目标 | {inputs.get("control_goal", "")} |
| 输入信号 | {inputs.get("input_signals", "")} |
| 输出设备 | {inputs.get("output_devices", "")} |
| 控制要求 | {inputs.get("control_requirements", "")} |
| 安全保护要求 | {inputs.get("safety_requirements", "")} |

---

{final_report}
"""
