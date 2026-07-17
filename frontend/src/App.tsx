import { useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, useNavigate, useLocation } from 'react-router-dom';
// 전역 스타일 — main.tsx(standalone)뿐 아니라 여기(MF remote 진입 './App')에서도
// import 해야 셸 임베드 시 .container/.card/:root 변수 등이 실린다. 없으면 무스타일.
import '@progress/kendo-theme-bootstrap/dist/all.css';
import './index.css';
import Dashboard from './pages/Dashboard';
import KnowledgeBaseDetail from './pages/KnowledgeBaseDetail';
import GraphViewer from './pages/KnowledgeGraphViewer';

// 셸(NETRIX platform-app)이 MF remote 마운트 시 주입하는 props (계약: PLATFORM-MF-CONTRACT.md §1).
// standalone(dev) 진입 시에는 전부 undefined — 없어도 동작.
type ShellProps = {
  user?: string;
  authority?: Record<string, number>;
  resetKey?: number;
  page?: string;
  onNavigate?: (page: string, ctx?: Record<string, unknown>) => void;
};

// 셸 ↔ 라우터 브리지 — 타이틀바 메뉴/홈 클릭을 라우팅으로, 내부 라우트를 셸 보고로.
//   셸 → remote: page prop 변경(타이틀바 'Knowledges' 클릭 = 'knowledges') / resetKey 증가(브랜드 홈)
//   remote → 셸: onNavigate(pageKey) — manifest.menus[].pages 와 같은 네임스페이스로 보고해
//               셸이 활성 메뉴를 유지한다.
function ShellBridge({ resetKey, page, onNavigate }: ShellProps) {
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    if (page === 'knowledges') navigate('/');
  }, [page]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (resetKey && resetKey > 0) navigate('/');
  }, [resetKey]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const p = location.pathname.startsWith('/kb/')
      ? 'kb'
      : location.pathname.startsWith('/graph-viewer')
        ? 'graph'
        : 'knowledges';
    onNavigate?.(p, {});
  }, [location.pathname]); // eslint-disable-line react-hooks/exhaustive-deps

  return null;
}

function App(props: ShellProps) {
  // basename 은 trailing slash 제거 필수. 셸 스코프 URL 은 '/ragaas'(끝 슬래시 없음)인데
  // basename 이 '/ragaas/'(BASE_URL 원값)면 react-router stripBasename 이 매칭 실패 →
  // 어떤 라우트도 안 그려져 빈 화면. dev(base '/')는 '' → '/' 로 폴백.
  const basename = (import.meta.env.BASE_URL || '/').replace(/\/+$/, '') || '/';
  return (
    <Router basename={basename}>
      <ShellBridge {...props} />
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/kb/:id" element={<KnowledgeBaseDetail />} />
        <Route path="/graph-viewer" element={<GraphViewer />} />
      </Routes>
    </Router>
  );
}

export default App;
