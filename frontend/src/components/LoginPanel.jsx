import { LogIn, ShieldCheck } from "lucide-react";


function LoginPanel({ isReady, error, onLogin }) {
  return (
    <main className="main-content auth-content">
      <section className="panel login-panel" aria-labelledby="login-heading">
        <ShieldCheck size={32} aria-hidden="true" />
        <p className="panel-kicker">OIDC AUTHENTICATION</p>
        <h1 id="login-heading">登录工业控制工作台</h1>
        <p>
          登录身份将用于方案归属、角色授权、独立审批和审计记录。
          系统不会接受由页面填写的审批人身份。
        </p>
        {error && <div className="auth-error" role="alert">{error}</div>}
        <button
          className="button button-primary"
          type="button"
          onClick={onLogin}
          disabled={!isReady || Boolean(error)}
        >
          <LogIn size={18} aria-hidden="true" />
          {isReady ? "使用组织账号登录" : "正在校验登录状态"}
        </button>
      </section>
    </main>
  );
}


export default LoginPanel;
