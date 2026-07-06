// 런타임 설정 로더 — 플랫폼 계약 05 §5/§6.
// 조회 우선순위: window._env_ (컨테이너 entrypoint 가 생성한 env.js)
//   → import.meta.env (vite dev, REACT_APP_* prefix)
//   → 하드코딩 dev 폴백.
// 빌드 산출물에 호스트/스킴을 인라인하지 않는다 (폐쇄망 재빌드-없는 배포 요건).

declare global {
  interface Window {
    _env_?: Record<string, string>;
  }
}

function env(key: string, fallback: string): string {
  const runtime = typeof window !== 'undefined' ? window._env_?.[key] : undefined;
  if (runtime !== undefined && runtime !== '') return runtime;
  const buildtime = (import.meta.env as Record<string, string | undefined>)[key];
  if (buildtime !== undefined && buildtime !== '') return buildtime;
  return fallback;
}

const config = {
  /** RAGaaS 백엔드 API 베이스. 셸 배포: {gateway}/ragaas-api/api/v2, standalone: 같은 호스트 프록시 */
  RAGAAS_API: env('REACT_APP_RAGAAS_API', '/api/v2/'),
  /** ingest 서비스 API 베이스. 셸 배포: {gateway}/ragaas-ingest-api/api/v2, standalone: nginx/vite 프록시 */
  RAGAAS_INGEST_API: env('REACT_APP_RAGAAS_INGEST_API', '/ingest-api/'),
  /** standalone SSO 모드 토글 (셸 안에서는 셸 인증이 우선이라 미사용) */
  USE_SSO: env('REACT_APP_USE_SSO', 'false') === 'true',
  /** SSO 서버 (ADFSLogin / introspect) — standalone SSO 모드에서만 사용 */
  SSO_URL: env('REACT_APP_SSO_URL', ''),
  /** dev 폴백 사용자 (백엔드 DEV_USER 와 짝) */
  DEV_USER: env('REACT_APP_DEV_USER', 'dev'),
};

/** WebSocket 베이스 URL — RAGAAS_API 에서 유도 (http→ws, 상대경로면 현재 origin 기준) */
export function wsBase(): string {
  const api = config.RAGAAS_API.replace(/\/$/, '');
  if (/^https?:\/\//.test(api)) return api.replace(/^http/, 'ws');
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}${api}`;
}

export default config;
