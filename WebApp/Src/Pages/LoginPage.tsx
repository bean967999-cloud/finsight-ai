import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router";
import { ApiError } from "../Api/Client";
import { useSession } from "../Auth/Session";

export function LoginPage() {
  const { login, principal } = useSession();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (principal) {
    return <Navigate to="/research" replace />;
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      await login(email.trim(), password);
      navigate("/research", { replace: true });
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : "登录失败，请检查账号或服务状态。");
    } finally {
      setPassword("");
      setBusy(false);
    }
  }

  return <main className="login-shell">
    <section className="login-card">
      <p className="eyebrow">FinSight · 研究工作台</p>
      <h1>登录工作空间</h1>
      <p className="muted">使用已有账号登录；工作空间和角色由服务端确认。</p>
      <form onSubmit={submit}>
        <label>邮箱<input type="email" autoComplete="username" value={email}
          onChange={(event) => setEmail(event.target.value)} required /></label>
        <label>密码<input type="password" autoComplete="current-password" value={password}
          onChange={(event) => setPassword(event.target.value)} required /></label>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit" disabled={busy}>{busy ? "正在验证…" : "登录"}</button>
      </form>
      <p className="fine-print">登录状态仅在当前标签页内临时保存；刷新时会重新验证身份。退出登录或会话过期后需重新登录。</p>
    </section>
  </main>;
}
