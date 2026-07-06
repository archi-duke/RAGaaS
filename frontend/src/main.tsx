// standalone 부트스트랩 — 셸 배포에서는 remoteEntry('./App')만 로드되고 이 파일은 실행되지 않는다.
// 계약 01 §7: remote 는 셸 없이 단독 실행 가능해야 한다 (개발·장애 격리).
import { createRoot } from 'react-dom/client';
import App from './App.tsx';
import { bootstrapAuth, getAuthority, getUser } from './platform/auth';

bootstrapAuth().then(() => {
  const user = getUser()?.loginid ?? '';
  createRoot(document.getElementById('root')!).render(
    <App standalone user={user} authority={getAuthority()} />,
  );
});
