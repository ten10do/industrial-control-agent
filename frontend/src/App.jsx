import { useCallback, useEffect, useMemo, useState } from "react";
import { ShieldAlert } from "lucide-react";

import { checkHealth, fetchExamples, generateControlPlan } from "./api";
import ErrorMessage from "./components/ErrorMessage";
import IndustrialHeader from "./components/IndustrialHeader";
import LoadingState from "./components/LoadingState";
import ResultTabs from "./components/ResultTabs";
import ScenarioForm from "./components/ScenarioForm";
import Sidebar from "./components/Sidebar";
import StatusPanel from "./components/StatusPanel";


const EMPTY_FORM = {
  control_object: "",
  input_devices: "",
  output_devices: "",
  control_requirements: "",
};

const SAFETY_NOTICE = "方案仅供课程设计和工程参考，实际工程需由专业工程师复核。";


function App() {
  const [formData, setFormData] = useState(EMPTY_FORM);
  const [examples, setExamples] = useState([]);
  const [selectedExampleName, setSelectedExampleName] = useState("");
  const [modelProvider, setModelProvider] = useState("DeepSeek");
  const [backendStatus, setBackendStatus] = useState("checking");
  const [result, setResult] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const selectedExample = useMemo(
    () => examples.find((example) => example.name === selectedExampleName) ?? null,
    [examples, selectedExampleName],
  );

  const hasInput = useMemo(
    () => Object.values(formData).some((value) => value.trim()),
    [formData],
  );

  const refreshBackend = useCallback(async () => {
    setBackendStatus("checking");
    try {
      const health = await checkHealth();
      if (health.status !== "ok") {
        throw new Error("Backend unavailable");
      }
      setBackendStatus("online");

      try {
        const exampleResponse = await fetchExamples();
        const nextExamples = Array.isArray(exampleResponse.examples)
          ? exampleResponse.examples
          : [];
        setExamples(nextExamples);
        setSelectedExampleName((current) => current || nextExamples[0]?.name || "");
      } catch {
        setExamples([]);
      }
    } catch {
      setBackendStatus("offline");
    }
  }, []);

  useEffect(() => {
    refreshBackend();
  }, [refreshBackend]);

  function updateField(field, value) {
    setFormData((current) => ({ ...current, [field]: value }));
  }

  function applySelectedExample() {
    if (!selectedExample) {
      setErrorMessage("请先选择一个示例场景。");
      return;
    }
    const { control_object, input_devices, output_devices, control_requirements } = selectedExample;
    setFormData({ control_object, input_devices, output_devices, control_requirements });
    setErrorMessage("");
  }

  function clearForm() {
    setFormData(EMPTY_FORM);
    setResult(null);
    setErrorMessage("");
  }

  async function handleGenerate(event) {
    event.preventDefault();
    const hasEmptyField = Object.values(formData).some((value) => !value.trim());
    if (hasEmptyField) {
      setErrorMessage("请完整填写控制对象、输入设备、输出设备和控制要求。");
      return;
    }
    if (backendStatus !== "online") {
      setErrorMessage("后端服务未连接，请确认 FastAPI 后端可访问后重试。");
      return;
    }

    setIsLoading(true);
    setErrorMessage("");
    try {
      const response = await generateControlPlan({
        ...formData,
        model_provider: modelProvider,
      });
      setResult(response);
    } catch (error) {
      setErrorMessage(error.message || "控制方案生成失败，请稍后重试。");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="app-shell">
      <IndustrialHeader backendStatus={backendStatus} modelProvider={modelProvider} />

      <div className="workbench-layout">
        <Sidebar
          examples={examples}
          selectedExampleName={selectedExampleName}
          onSelectExample={setSelectedExampleName}
          modelProvider={modelProvider}
          onModelProviderChange={setModelProvider}
          backendStatus={backendStatus}
          onRefreshBackend={refreshBackend}
        />

        <main className="main-content">
          <section className="hero-panel">
            <div>
              <p className="eyebrow">SCADA DESIGN WORKBENCH</p>
              <h1>工业控制方案设计 Agent 系统</h1>
              <p className="page-description">
                面向 PLC 初步设计场景，将控制对象、I/O 设备和控制要求转换为需求分析、I/O 点表、联锁逻辑与工程方案报告。
              </p>
            </div>
            <div className="hero-schematic" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
          </section>

          <div className="safety-banner" role="note">
            <ShieldAlert size={19} aria-hidden="true" />
            <span>安全提示：{result?.safety_notice || SAFETY_NOTICE}</span>
          </div>

          <StatusPanel
            backendStatus={backendStatus}
            selectedExampleName={selectedExampleName}
            hasInput={hasInput}
            hasResult={Boolean(result)}
          />

          {errorMessage && (
            <ErrorMessage message={errorMessage} onDismiss={() => setErrorMessage("")} />
          )}

          <ScenarioForm
            formData={formData}
            onFieldChange={updateField}
            onSubmit={handleGenerate}
            onClear={clearForm}
            onUseExample={applySelectedExample}
            selectedExampleName={selectedExampleName}
            isLoading={isLoading}
          />

          {isLoading ? <LoadingState /> : <ResultTabs result={result} />}
        </main>
      </div>
    </div>
  );
}


export default App;
