import { useEffect, useRef } from 'react';
import {
  BrowserRouter,
  MemoryRouter,
  Routes,
  Route,
  useLocation,
  useNavigate,
} from 'react-router-dom';
// 셸 모드에서는 main.tsx 가 실행되지 않으므로 전역 스타일은 여기(노출 진입점)서 로드한다.
// Kendo 테마 소유권은 Phase 2 에서 @platform/web-ui 로 이관 예정 (계약 04).
import '@progress/kendo-theme-bootstrap/dist/all.css';
import './index.css';
import Dashboard from './pages/Dashboard';
import KnowledgeBaseDetail from './pages/KnowledgeBaseDetail';
import GraphViewer from './pages/KnowledgeGraphViewer';

// 플랫폼 마운트 계약 (docs/platform-contract/01 §2)
export interface RemoteAppProps {
  /** introspect 로 확정된 사용자 loginid — 셸이 인증 완료 후에만 마운트하므로 항상 존재 */
  user: string;
  /** 권한 맵 (GET /Account/me 의 authority) */
  authority: Record<string, number> | null;
  /** 셸 탭 재클릭 등 초기 화면 복귀 요구 시 증가 */
  resetKey?: number;
  /** 셸이 배정한 URL 프리픽스 (라우팅 표준 도입 시) */
  basePath?: string;
  /** 내부 페이지 전환 보고 — 페이지 전환마다 + 마운트 직후 1회 */
  onNavigate?: (page: string, ctx?: { projectCode?: string }) => void;
  /** standalone 부트스트랩(main.tsx) 전용 — 셸은 전달하지 않는다 */
  standalone?: boolean;
}

function pageKey(pathname: string): string {
  if (pathname.startsWith('/kb/')) return 'kb';
  if (pathname.startsWith('/graph-viewer')) return 'graphViewer';
  return 'dashboard';
}

/** 페이지 전환(및 마운트 직후 1회)을 셸에 보고 — 계약 01 §2 */
function NavigationReporter({ onNavigate }: Pick<RemoteAppProps, 'onNavigate'>) {
  const location = useLocation();
  const onNavigateRef = useRef(onNavigate);
  onNavigateRef.current = onNavigate;
  useEffect(() => {
    onNavigateRef.current?.(pageKey(location.pathname), { projectCode: '' });
  }, [location.pathname]);
  return null;
}

/** resetKey 증가 시 초기 화면 복귀 */
function ResetHandler({ resetKey }: Pick<RemoteAppProps, 'resetKey'>) {
  const navigate = useNavigate();
  const mounted = useRef(false);
  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true;
      return;
    }
    navigate('/');
  }, [resetKey, navigate]);
  return null;
}

function AppRoutes(props: RemoteAppProps) {
  return (
    <>
      <NavigationReporter onNavigate={props.onNavigate} />
      <ResetHandler resetKey={props.resetKey} />
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/kb/:id" element={<KnowledgeBaseDetail />} />
        <Route path="/graph-viewer" element={<GraphViewer />} />
      </Routes>
    </>
  );
}

/**
 * RAGaaS remote 진입점 (MF expose './App').
 * 셸 모드: MemoryRouter — remote 내부 페이지는 셸 URL 에 반영하지 않는다 (계약 01 §2).
 * standalone: BrowserRouter — 개발 편의용 딥링크 유지.
 */
function App(props: RemoteAppProps) {
  if (props.standalone) {
    return (
      <BrowserRouter>
        <AppRoutes {...props} />
      </BrowserRouter>
    );
  }
  return (
    <MemoryRouter>
      <AppRoutes {...props} />
    </MemoryRouter>
  );
}

export default App;
