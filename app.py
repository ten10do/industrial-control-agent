from openai import APIConnectionError, APIError, AuthenticationError, OpenAIError, RateLimitError
import streamlit as st
from dotenv import load_dotenv

from examples import CONTROL_EXAMPLES
from workflow import ControlDesignWorkflow, WorkflowStepError
from utils import build_markdown_report, collect_user_inputs, validate_inputs


load_dotenv()


EXAMPLE_PLACEHOLDER = "请选择示例场景"


STEP_TITLES = [
    ("requirements_analysis", "第一步：控制需求结构化分析"),
    ("io_table", "第二步：PLC I/O 点表"),
    ("control_logic", "第三步：控制逻辑说明"),
    ("safety_logic", "第四步：安全保护逻辑"),
    ("plc_design", "第五步：PLC 梯形图设计思路"),
    ("debug_steps", "第六步：调试步骤"),
]


def apply_example(name: str) -> None:
    example = CONTROL_EXAMPLES.get(name)
    if not example:
        return

    for key, value in example.items():
        st.session_state[key] = value


def apply_selected_example() -> None:
    apply_example(st.session_state.selected_example)


def init_state() -> None:
    defaults = {
        "control_object": "",
        "control_goal": "",
        "input_signals": "",
        "output_devices": "",
        "control_requirements": "",
        "safety_requirements": "",
        "include_plc_design": True,
        "include_debug_steps": True,
        "workflow_result": None,
        "last_inputs": None,
        "selected_example": EXAMPLE_PLACEHOLDER,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def render_header() -> None:
    st.title("工业控制方案设计 Agent")
    st.markdown(
        """
        面向自动化控制系统初步设计场景，输入控制对象、I/O 信号、控制要求和安全要求后，
        系统会调用 DeepSeek API，按工程设计流程生成控制需求分析、PLC I/O 点表、控制逻辑、
        安全保护逻辑、PLC 梯形图设计思路、调试步骤和完整 Markdown 方案报告。
        """
    )

    col1, col2, col3 = st.columns(3)
    col1.info("1. 选择示例或填写控制项目信息")
    col2.info("2. 点击“生成控制方案”启动 Agent 工作流")
    col3.info("3. 查看分步结果并下载 Markdown 报告")


def render_inputs() -> dict:
    st.subheader("项目输入")

    example_options = [EXAMPLE_PLACEHOLDER, *CONTROL_EXAMPLES.keys()]
    st.selectbox(
        "示例场景",
        example_options,
        key="selected_example",
        on_change=apply_selected_example,
        help="选择示例后会自动填充下方表单，也可以继续手动修改。",
    )

    with st.form("control_design_form", clear_on_submit=False):
        left, right = st.columns(2)
        with left:
            st.text_input("控制对象", key="control_object", placeholder="例如：三相异步电机")
            st.text_area("控制目标", key="control_goal", height=110)
            st.text_area("输入信号", key="input_signals", height=150)
        with right:
            st.text_area("输出设备", key="output_devices", height=110)
            st.text_area("控制要求", key="control_requirements", height=150)
            st.text_area("安全保护要求", key="safety_requirements", height=150)

        option_col1, option_col2 = st.columns(2)
        with option_col1:
            st.checkbox("生成 PLC 设计思路", key="include_plc_design")
        with option_col2:
            st.checkbox("生成调试步骤", key="include_debug_steps")

        generate = st.form_submit_button("生成控制方案", type="primary", use_container_width=True)

    inputs = collect_user_inputs(st.session_state)
    inputs["generate"] = generate
    return inputs


def render_step_results(results: dict) -> None:
    st.subheader("分步生成结果")
    for key, title in STEP_TITLES:
        content = results.get(key)
        if not content:
            continue
        with st.expander(title, expanded=False):
            st.markdown(content)


def render_final_report(inputs: dict, results: dict) -> None:
    st.subheader("完整方案报告")
    final_report = results.get("final_report", "")
    st.markdown(final_report)

    markdown_report = build_markdown_report(inputs, results)
    st.download_button(
        label="下载 Markdown 报告",
        data=markdown_report,
        file_name="industrial_control_design_report.md",
        mime="text/markdown",
        use_container_width=True,
    )


def render_input_errors(errors: list[str]) -> None:
    st.error("输入信息不完整，请补充后再生成方案。")
    for error in errors:
        st.warning(error)


def render_generation_error(exc: Exception) -> None:
    if isinstance(exc, WorkflowStepError):
        st.error(f"Agent 工作流执行失败：{exc.step_name}。")
        render_generation_error(exc.original_error)
        return
    if isinstance(exc, ValueError) and "DEEPSEEK_API_KEY" in str(exc):
        st.error("API Key 缺失：请在项目根目录 `.env` 文件中配置 `DEEPSEEK_API_KEY`。")
        return
    if isinstance(exc, AuthenticationError):
        st.error("API Key 认证失败：请检查 `.env` 中的 `DEEPSEEK_API_KEY` 是否正确。")
        return
    if isinstance(exc, APIConnectionError):
        st.error("网络请求失败：无法连接 DeepSeek API，请检查网络连接或代理配置。")
        return
    if isinstance(exc, RateLimitError):
        st.error("请求频率受限：DeepSeek API 返回限流，请稍后重试。")
        return
    if isinstance(exc, APIError):
        st.error(f"DeepSeek API 请求失败：{exc}")
        return
    if isinstance(exc, OpenAIError):
        st.error(f"模型服务调用失败：{exc}")
        return
    st.error(f"生成失败：{exc}")


def main() -> None:
    st.set_page_config(page_title="工业控制方案设计 Agent", page_icon="⚙️", layout="wide")
    init_state()
    render_header()

    with st.container(border=True):
        inputs = render_inputs()

    if inputs["generate"]:
        errors = validate_inputs(inputs)
        if errors:
            render_input_errors(errors)
        else:
            with st.status("Agent 正在生成控制方案...", expanded=True) as status:
                try:
                    workflow = ControlDesignWorkflow()
                    results = workflow.run(inputs, status_writer=st.write)
                    st.session_state.workflow_result = results
                    st.session_state.last_inputs = inputs.copy()
                    status.update(label="控制方案生成完成", state="complete")
                except Exception as exc:
                    status.update(label="控制方案生成失败", state="error")
                    render_generation_error(exc)

    results = st.session_state.workflow_result
    if results:
        report_inputs = st.session_state.last_inputs or inputs
        render_final_report(report_inputs, results)
        render_step_results(results)
    else:
        st.info("请填写项目信息，或在示例场景下拉框中选择一个内置示例。")


if __name__ == "__main__":
    main()
