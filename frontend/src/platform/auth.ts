// 플랫폼 인증 어댑터 — 앱 코드의 유일한 인증 소비 지점 (계약 docs/platform-contract/02 §5).
//
// 셸(Platform-App) 안에서 실행 중이면: 셸 auth 모듈이 로드 시 게시한 window.__platformAuth
// 를 그대로 사용한다 (셸이 remote 마운트 전에 반드시 게시 — 호출 시점마다 조회해
// 모듈 로드 순서에 무관하게 동작). 이 키에 쓰는 것은 금지 — 게시 주체는 셸뿐이다.
// standalone(단독 실행)이면: 아래 로컬 구현 — SSO_SESSION 쿠키 → introspect,
// dev 환경은 DEV_USER 로 X-User-Id 폴백 (백엔드 계약 05 §1-5 와 짝).
//
// 원칙: 자체 로그인/토큰 저장 금지. 토큰은 변수에 저장하지 말고 요청 시마다 getToken().
import config from './config';

export interface PlatformAuth {
  getToken(): string | null;
  getUser(): { loginid: string } | null;
  getAuthority(): Record<string, number> | null;
  authFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response>;
  onSessionChange(cb: (s: { user: string | null }) => void): () => void;
  requireLogin(): void;
}

declare global {
  interface Window {
    __platformAuth?: PlatformAuth;
  }
}

const shell = (): PlatformAuth | null =>
  (typeof window !== 'undefined' && window.__platformAuth) || null;

// ── standalone 로컬 구현 ──

function localGetToken(): string | null {
  if (typeof document === 'undefined') return null;
  const m = document.cookie.match(/(^| )SSO_SESSION=([^;]+)/);
  return m ? decodeURIComponent(m[2]) : null;
}

// standalone SSO 모드에서 introspect 로 확정된 신원 (bootstrapAuth 가 채움)
let standaloneUser: string | null = null;

function localGetUser(): { loginid: string } | null {
  if (standaloneUser) return { loginid: standaloneUser };
  if (!config.USE_SSO) return { loginid: config.DEV_USER };
  return null;
}

function localRequireLogin(): void {
  if (config.USE_SSO && config.SSO_URL && typeof window !== 'undefined') {
    document.cookie = 'SSO_SESSION=; path=/; max-age=0';
    window.location.href = `${config.SSO_URL}/Account/ADFSLogin?client=${window.location.origin}`;
  } else {
    console.warn('[platform/auth] requireLogin: SSO 미구성(standalone dev) — 로그인 흐름 없음');
  }
}

/**
 * standalone 부트스트랩 — 셸 없이 뜰 때 main.tsx 가 1회 호출.
 * USE_SSO=true 면 SSO_SESSION 쿠키를 introspect 로 검증해 신원을 확정한다
 * (셸 §4 절차의 축소판). 토큰이 없거나 무효면 로그인 리다이렉트.
 * 셸 안에서는 아무것도 하지 않는다 (셸 인증이 진실의 원천).
 */
export async function bootstrapAuth(): Promise<void> {
  if (shell() || !config.USE_SSO) return;
  const token = localGetToken();
  if (!token) return localRequireLogin();
  try {
    const r = await fetch(
      `${config.SSO_URL}/Account/introspect?token=${encodeURIComponent(token)}`,
    );
    const d = r.ok ? await r.json() : null;
    if (d?.loginid && d?.active !== 'false') {
      standaloneUser = d.loginid;
      return;
    }
  } catch (e) {
    console.error('[platform/auth] introspect 실패:', e);
  }
  localRequireLogin();
}

// ── 공개 API — 호출 시점에 셸 게시본 우선 ──

export const getToken = (): string | null => (shell()?.getToken ?? localGetToken)();
export const getUser = (): { loginid: string } | null => (shell()?.getUser ?? localGetUser)();
export const getAuthority = (): Record<string, number> | null =>
  shell()?.getAuthority?.() ?? null;
export const requireLogin = (): void => (shell()?.requireLogin ?? localRequireLogin)();
export const onSessionChange = (cb: (s: { user: string | null }) => void): (() => void) =>
  shell()?.onSessionChange?.(cb) ?? (() => {});
