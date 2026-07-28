from typing import Callable, Dict, Optional

from llm_client import DeepSeekClient
from prompts import (
    SYSTEM_PROMPT,
    control_logic_prompt,
    debug_steps_prompt,
    final_report_prompt,
    io_table_prompt,
    plc_design_prompt,
    requirements_analysis_prompt,
    safety_logic_prompt,
)


StatusWriter = Optional[Callable[[str], None]]


class WorkflowStepError(RuntimeError):
    def __init__(self, step_name: str, original_error: Exception) -> None:
        self.step_name = step_name
        self.original_error = original_error
        super().__init__(f"{step_name}失败：{original_error}")


class ControlDesignWorkflow:
    """Seven-step Agent workflow for industrial control scheme design."""

    def __init__(self, llm_client: Optional[DeepSeekClient] = None) -> None:
        self.llm = llm_client or DeepSeekClient()

    def _call_llm(self, step_name: str, prompt: str, status_writer: StatusWriter = None) -> str:
        if status_writer:
            status_writer(step_name)

        try:
            content = self.llm.chat(prompt=prompt, system_prompt=SYSTEM_PROMPT).strip()
        except Exception as exc:
            raise WorkflowStepError(step_name, exc) from exc

        if not content:
            raise WorkflowStepError(step_name, ValueError("模型返回内容为空"))
        return content

    def analyze_requirement(self, inputs: dict, status_writer: StatusWriter = None) -> str:
        return self._call_llm(
            "第一步：控制需求结构化分析",
            requirements_analysis_prompt(inputs),
            status_writer,
        )

    def generate_io_table(
        self,
        inputs: dict,
        requirements_analysis: str,
        status_writer: StatusWriter = None,
    ) -> str:
        return self._call_llm(
            "第二步：生成 PLC I/O 点表",
            io_table_prompt(inputs, requirements_analysis),
            status_writer,
        )

    def generate_control_logic(
        self,
        inputs: dict,
        requirements_analysis: str,
        io_table: str,
        status_writer: StatusWriter = None,
    ) -> str:
        return self._call_llm(
            "第三步：生成控制逻辑说明",
            control_logic_prompt(inputs, requirements_analysis, io_table),
            status_writer,
        )

    def generate_safety_logic(
        self,
        inputs: dict,
        requirements_analysis: str,
        io_table: str,
        control_logic: str,
        status_writer: StatusWriter = None,
    ) -> str:
        return self._call_llm(
            "第四步：生成安全保护逻辑",
            safety_logic_prompt(inputs, requirements_analysis, io_table, control_logic),
            status_writer,
        )

    def generate_plc_design_idea(
        self,
        inputs: dict,
        previous_results: Dict[str, str],
        status_writer: StatusWriter = None,
    ) -> str:
        if not inputs.get("include_plc_design", True):
            return "用户选择不生成 PLC 梯形图设计思路。"

        return self._call_llm(
            "第五步：生成 PLC 梯形图设计思路",
            plc_design_prompt(inputs, previous_results),
            status_writer,
        )

    def generate_debug_steps(
        self,
        inputs: dict,
        previous_results: Dict[str, str],
        status_writer: StatusWriter = None,
    ) -> str:
        if not inputs.get("include_debug_steps", True):
            return "用户选择不生成调试步骤。"

        return self._call_llm(
            "第六步：生成调试步骤",
            debug_steps_prompt(inputs, previous_results),
            status_writer,
        )

    def generate_final_report(
        self,
        inputs: dict,
        previous_results: Dict[str, str],
        status_writer: StatusWriter = None,
    ) -> str:
        return self._call_llm(
            "第七步：汇总完整控制方案报告",
            final_report_prompt(inputs, previous_results),
            status_writer,
        )

    def run(self, inputs: dict, status_writer: StatusWriter = None) -> Dict[str, str]:
        results: Dict[str, str] = {}

        results["requirements_analysis"] = self.analyze_requirement(inputs, status_writer)

        results["io_table"] = self.generate_io_table(
            inputs,
            results["requirements_analysis"],
            status_writer,
        )

        results["control_logic"] = self.generate_control_logic(
            inputs,
            results["requirements_analysis"],
            results["io_table"],
            status_writer,
        )

        results["safety_logic"] = self.generate_safety_logic(
            inputs,
            results["requirements_analysis"],
            results["io_table"],
            results["control_logic"],
            status_writer,
        )

        results["plc_design"] = self.generate_plc_design_idea(inputs, results, status_writer)
        results["debug_steps"] = self.generate_debug_steps(inputs, results, status_writer)
        results["final_report"] = self.generate_final_report(inputs, results, status_writer)

        return results
