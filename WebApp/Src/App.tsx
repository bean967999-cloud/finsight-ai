import { lazy, Suspense } from "react";
import { Navigate, NavLink, Outlet, Route, Routes } from "react-router";
import { useSession } from "./Auth/Session";
import { LoginPage } from "./Pages/LoginPage";
import { AdminPage, DocumentTasksPage } from "./Pages/AdminPage";
import { ResearchPage } from "./Pages/ResearchPage";
import { EvidencePage } from "./Pages/EvidencePage";
import { TracePage } from "./Pages/TracePage";
import { EvidenceRunProvider } from "./Auth/EvidenceRun";
import { EvaluationPage } from "./Pages/EvaluationPage";
import { ReviewPage } from "./Pages/ReviewPage";
import { label } from "./Presentation/Labels";
import { TechnicalDetails, TechnicalValue } from "./Presentation/TechnicalDetails";

const RiskPage = lazy(() => import("./Pages/RiskPage"));

const sections = [
  { to: "/research", label: "投研首页" },
  { to: "/trace", label: "执行轨迹" },
  { to: "/evidence", label: "文档证据" },
  { to: "/risk", label: "风险看板" },
  { to: "/review", label: "人工审核" },
  { to: "/evaluation", label: "评估看板" },
  { to: "/admin", label: "管理与审计" },
  { to: "/documents", label: "文档与任务" },
];

function ProtectedLayout() {
  const { principal, logout } = useSession();
  if (!principal) return <Navigate to="/login" replace />;
  const isAdmin = principal.memberships.some((item) => item.role === "workspace_admin");

  return <EvidenceRunProvider><div className="app-shell">
    <aside className="sidebar">
      <div className="brand">FinSight<span>金融研究工作台</span></div>
      <nav aria-label="主导航">
        {sections.filter((item) => isAdmin || !["/admin", "/evaluation", "/documents"].includes(item.to)).map((item) =>
          <NavLink key={item.to} to={item.to}>{item.label}</NavLink>
        )}
      </nav>
      <div className="sidebar-footer">
        <small>当前角色：{[...new Set(principal.memberships.map(item => label("role", item.role)))].join("、") || "暂无工作空间角色"}</small>
        <TechnicalDetails title="身份详情"><TechnicalValue name="用户编号" value={principal.user_id} /></TechnicalDetails>
        <button type="button" onClick={logout}>退出登录</button>
      </div>
    </aside>
    <main className="content"><Outlet /></main>
  </div></EvidenceRunProvider>;
}

function AdminGate() {
  const { principal } = useSession();
  const allowed = principal?.memberships.some((item) => item.role === "workspace_admin");
  return allowed ? <Outlet /> : <Navigate to="/research" replace />;
}

export function App() {
  return <Routes>
    <Route path="/login" element={<LoginPage />} />
    <Route element={<ProtectedLayout />}>
      <Route path="/research" element={<ResearchPage />} />
      <Route path="/trace" element={<TracePage />} />
      <Route path="/evidence" element={<EvidencePage />} />
      <Route path="/review" element={<ReviewPage />} />
      <Route path="/risk" element={<Suspense fallback={<p>正在加载风险看板…</p>}><RiskPage /></Suspense>} />
      <Route element={<AdminGate />}>
        <Route path="/evaluation" element={<EvaluationPage />} />
      </Route>
      <Route element={<AdminGate />}>
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/documents" element={<DocumentTasksPage />} />
      </Route>
    </Route>
    <Route path="*" element={<Navigate to="/research" replace />} />
  </Routes>;
}
