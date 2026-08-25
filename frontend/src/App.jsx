import { useCallback, useEffect, useMemo, useState } from "react";
import { ShieldAlert } from "lucide-react";

import {
  cancelModelJob,
  checkHealth,
  checkReadiness,
  exportPlanMarkdown,
  fetchCurrentUser,
  fetchExamples,
  fetchPlan,
  fetchPlanAudit,
  fetchPlans,
  generateControlPlan,
  optimizeControlPlan,
  reviewPlan,
} from "./api";
import { useAuth } from "./auth";
import ErrorMessage from "./components/ErrorMessage";
import IndustrialHeader from "./components/IndustrialHeader";
import LoginPanel from "./components/LoginPanel";
import LoadingState from "./components/LoadingState";
import OptimizationPanel from "./components/OptimizationPanel";
import PersistedPlanPanel from "./components/PersistedPlanPanel";
import PlanInbox from "./components/PlanInbox";
import ResultTabs from "./components/ResultTabs";
import ScenarioForm from "./components/ScenarioForm";
import SafetyReviewGate from "./components/SafetyReviewGate";
import Sidebar from "./components/Sidebar";
import StatusPanel from "./components/StatusPanel";
import ValidationPanel from "./components/ValidationPanel";


const EMPTY_FORM = {
  control_object: "",
  input_devices: "",
  output_devices: "",
  control_requirements: "",
};

const SAFETY_NOTICE = "方案仅供课程设计和工程参考，实际工程需由专业工程师复核。";


function App() {
  const auth = useAuth();
  const [formData, setFormData] = useState(EMPTY_FORM);
  const [examples, setExamples] = useState([]);
  const [selectedExampleName, setSelectedExampleName] = useState("");
  const [modelProvider, setModelProvider] = useState("Ox Alpha");
  const [backendStatus, setBackendStatus] = useState("checking");
  const [result, setResult] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isOptimizing, setIsOptimizing] = useState(false);
  const [activeJob, setActiveJob] = useState(null);
  const [optimization, setOptimization] = useState(null);
  const [safetyApproval, setSafetyApproval] = useState(null);
  const [optimizationApproval, setOptimizationApproval] = useState(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [errorRequestId, setErrorRequestId] = useState("");
  const [principal, setPrincipal] = useState(null);
  const [plans, setPlans] = useState([]);
  const [isLoadingPlans, setIsLoadingPlans] = useState(false);
  const [selectedPersistedPlan, setSelectedPersistedPlan] = useState(null);
  const [persistedApproval, setPersistedApproval] = useState(null);
  const [planAudit, setPlanAudit] = useState(null);

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
      const readiness = await checkReadiness();
      if (readiness.status !== "ready") {
        throw new Error("Backend not ready");
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
    } catch (err) {
      if (err.name === "ApiRequestError" && err.status === 408) {
        setBackendStatus("warming_up");
      } else {
        setBackendStatus("offline");
      }
    }
  }, []);

  useEffect(() => {
    refreshBackend();
  }, [refreshBackend]);

  const refreshPlans = useCallback(async (accessToken = "") => {
    if (!auth.enabled) {
      return;
    }
    setIsLoadingPlans(true);
    try {
      const response = await fetchPlans(accessToken);
      setPlans(Array.isArray(response.plans) ? response.plans : []);
    } catch (error) {
      setErrorMessage(error.message || "方案收件箱加载失败。");
      setErrorRequestId(error.requestId || "");
    } finally {
      setIsLoadingPlans(false);
    }
  }, [auth.enabled]);

  useEffect(() => {
    if (!auth.enabled || !auth.user?.access_token) {
      setPrincipal(null);
      setPlans([]);
      return undefined;
    }
    let active = true;
    async function loadIdentity() {
      try {
        const verifiedUser = await fetchCurrentUser(auth.user.access_token);
        if (active) {
          setPrincipal(verifiedUser);
        }
        await refreshPlans(auth.user.access_token);
      } catch (error) {
        if (active) {
          setErrorMessage(error.message || "无法验证当前用户权限。");
          setErrorRequestId(error.requestId || "");
        }
      }
    }
    loadIdentity();
    return () => {
      active = false;
    };
  }, [auth.enabled, auth.user, refreshPlans]);

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
    setErrorRequestId("");
  }

  function clearForm() {
    setFormData(EMPTY_FORM);
    setResult(null);
    setOptimization(null);
    setSafetyApproval(null);
    setOptimizationApproval(null);
    setErrorMessage("");
    setErrorRequestId("");
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

    setResult(null);
    setOptimization(null);
    setSafetyApproval(null);
    setOptimizationApproval(null);
    setIsLoading(true);
    setErrorMessage("");
    setErrorRequestId("");
    try {
      const response = await generateControlPlan(
        {
          ...formData,
          model_provider: modelProvider,
        },
        { onStatus: setActiveJob },
      );
      setResult(response);
      await refreshPlans();
    } catch (error) {
      setErrorMessage(error.message || "控制方案生成失败，请稍后重试。");
      setErrorRequestId(error.requestId || "");
    } finally {
      setIsLoading(false);
      setActiveJob(null);
    }
  }

  async function handleOptimize(optimizeRequirement) {
    if (!result?.report_markdown) {
      return;
    }
    setIsOptimizing(true);
    setOptimization(null);
    setOptimizationApproval(null);
    setErrorMessage("");
    setErrorRequestId("");
    try {
      const response = await optimizeControlPlan(
        {
          original_report: result.report_markdown,
          optimize_requirement: optimizeRequirement,
          model_provider: modelProvider,
          ...(result.plan_id ? { plan_id: result.plan_id } : {}),
        },
        { onStatus: setActiveJob },
      );
      setOptimization(response);
      await refreshPlans();
    } catch (error) {
      setErrorMessage(error.message || "控制方案优化失败，请稍后重试。");
      setErrorRequestId(error.requestId || "");
    } finally {
      setIsOptimizing(false);
      setActiveJob(null);
    }
  }

  async function handleCancelJob() {
    if (!activeJob?.job_id) {
      return;
    }
    try {
      const job = await cancelModelJob(activeJob.job_id);
      setActiveJob(job);
    } catch (error) {
      setErrorMessage(error.message || "取消模型任务失败，请稍后重试。");
      setErrorRequestId(error.requestId || "");
    }
  }

  async function submitReview(planId, review, setApproval) {
    if (!planId) {
      const error = new Error("当前方案缺少持久化 ID，请重新生成方案。");
      setErrorMessage(error.message);
      throw error;
    }
    setErrorMessage("");
    setErrorRequestId("");
    try {
      const approval = await reviewPlan(
        planId,
        {
          decision: "approved",
          comment: review.comment,
        },
      );
      setApproval(approval);
      await refreshPlans();
      return approval;
    } catch (error) {
      setErrorMessage(error.message || "后端审批失败，请检查角色权限后重试。");
      setErrorRequestId(error.requestId || "");
      throw error;
    }
  }

  async function loadControlledExport(planId, fallbackMarkdown) {
    if (!planId) {
      return fallbackMarkdown;
    }
    try {
      return await exportPlanMarkdown(planId);
    } catch (error) {
      setErrorMessage(error.message || "方案导出失败，请检查审批状态后重试。");
      setErrorRequestId(error.requestId || "");
      throw error;
    }
  }

  async function openPersistedPlan(planId) {
    setErrorMessage("");
    setErrorRequestId("");
    try {
      const [plan, audit] = await Promise.all([
        fetchPlan(planId),
        fetchPlanAudit(planId),
      ]);
      setSelectedPersistedPlan(plan);
      setPlanAudit(audit);
      setPersistedApproval(
        plan.latest_review
          ? {
              ...plan.latest_review,
              plan_id: plan.plan_id,
              export_allowed: plan.export_allowed,
            }
          : null,
      );
    } catch (error) {
      setErrorMessage(error.message || "方案加载失败。");
      setErrorRequestId(error.requestId || "");
    }
  }

  async function refreshSelectedAudit() {
    if (!selectedPersistedPlan?.plan_id) {
      return;
    }
    try {
      setPlanAudit(await fetchPlanAudit(selectedPersistedPlan.plan_id));
    } catch (error) {
      setErrorMessage(error.message || "审计轨迹加载失败。");
      setErrorRequestId(error.requestId || "");
    }
  }

  async function approvePersistedPlan(review) {
    const approval = await submitReview(
      selectedPersistedPlan?.plan_id,
      review,
      setPersistedApproval,
    );
    setSelectedPersistedPlan((current) => (
      current ? { ...current, export_allowed: approval.export_allowed } : current
    ));
    await refreshSelectedAudit();
  }

  const authenticatedName = (
    principal?.display_name
    || auth.user?.profile?.name
    || auth.user?.profile?.preferred_username
    || auth.user?.profile?.sub
    || "当前登录用户"
  );
  const roles = new Set(principal?.roles || []);
  const canDesign = !auth.enabled || roles.has("designer") || roles.has("admin");
  const canReview = !auth.enabled || roles.has("reviewer") || roles.has("admin");

  if (auth.enabled && (!auth.ready || !auth.user)) {
    return (
      <div className="app-shell">
        <IndustrialHeader
          backendStatus={backendStatus}
          modelProvider={modelProvider}
          authEnabled
        />
        <LoginPanel
          isReady={auth.ready}
          error={auth.error}
          onLogin={auth.login}
        />
      </div>
    );
  }

  if (auth.enabled && !principal) {
    return (
      <div className="app-shell">
        <IndustrialHeader
          backendStatus={backendStatus}
          modelProvider={modelProvider}
          authEnabled
          userName={authenticatedName}
          onLogout={auth.logout}
        />
        <LoginPanel isReady={false} error={errorMessage} onLogin={auth.login} />
      </div>
    );
  }

  return (
    <div className="app-shell">
      <IndustrialHeader
        backendStatus={backendStatus}
        modelProvider={modelProvider}
        authEnabled={auth.enabled}
        userName={auth.enabled ? authenticatedName : ""}
        onLogout={auth.logout}
      />

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
            <ErrorMessage
              message={errorMessage}
              requestId={errorRequestId}
              onDismiss={() => {
                setErrorMessage("");
                setErrorRequestId("");
              }}
            />
          )}

          {auth.enabled && (
            <PlanInbox
              plans={plans}
              isLoading={isLoadingPlans}
              selectedPlanId={selectedPersistedPlan?.plan_id || ""}
              onSelect={openPersistedPlan}
              onRefresh={() => refreshPlans()}
            />
          )}

          {selectedPersistedPlan && (
            <PersistedPlanPanel
              plan={selectedPersistedPlan}
              approval={persistedApproval}
              audit={planAudit}
              canReview={
                canReview && selectedPersistedPlan.created_by !== principal?.subject
              }
              reviewerName={authenticatedName}
              onApprove={approvePersistedPlan}
              onClose={() => {
                setSelectedPersistedPlan(null);
                setPersistedApproval(null);
                setPlanAudit(null);
              }}
              onRefreshAudit={refreshSelectedAudit}
              loadExport={() => (
                loadControlledExport(
                  selectedPersistedPlan.plan_id,
                  selectedPersistedPlan.report_markdown,
                )
              )}
            />
          )}

          {canDesign ? (
            <ScenarioForm
              formData={formData}
              onFieldChange={updateField}
              onSubmit={handleGenerate}
              onClear={clearForm}
              onUseExample={applySelectedExample}
              selectedExampleName={selectedExampleName}
              isLoading={isLoading}
            />
          ) : (
            <section className="panel role-workspace-note" role="note">
              当前账号为审批角色。请从方案收件箱打开待审批版本。
            </section>
          )}

          {isLoading ? (
            <LoadingState job={activeJob} onCancel={handleCancelJob} />
          ) : (
            <>
              {result?.validation_report && (
                <ValidationPanel report={result.validation_report} />
              )}
              <SafetyReviewGate
                gate={result?.safety_gate}
                approval={safetyApproval}
                reviewerName={authenticatedName}
                canReview={!auth.enabled && canReview}
                onApprove={(review) => submitReview(result?.plan_id, review, setSafetyApproval)}
              />
              <ResultTabs
                result={result}
                exportAllowed={
                  result?.safety_gate?.export_allowed !== false
                  || Boolean(safetyApproval?.export_allowed)
                }
                loadExport={() => loadControlledExport(result?.plan_id, result?.report_markdown)}
              />
              {result?.report_markdown && (
                <>
                  {isOptimizing && (
                    <LoadingState
                      job={activeJob}
                      onCancel={handleCancelJob}
                      title="Agent 正在优化控制方案"
                    />
                  )}
                  <OptimizationPanel
                    originalReport={result.report_markdown}
                    optimization={optimization}
                    approval={optimizationApproval}
                    reviewerName={authenticatedName}
                    canReview={!auth.enabled && canReview}
                    isOptimizing={isOptimizing}
                    onOptimize={handleOptimize}
                    onApprove={(review) => (
                      submitReview(optimization?.plan_id, review, setOptimizationApproval)
                    )}
                    loadExport={() => (
                      loadControlledExport(
                        optimization?.plan_id,
                        optimization?.optimized_report,
                      )
                    )}
                  />
                </>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}


export default App;
