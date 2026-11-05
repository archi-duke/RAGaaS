// 로컬 Office 문서 변환 클라이언트 — 사용자 PC 의 런처 게이트웨이를 통해 ragaas-converter 호출.
//
// 사내 DRM(NASCA) 문서는 서버에서 복호화할 수 없다. DRM 에이전트가 붙은 로컬 Office 로만 열리므로,
// 브라우저 → 런처(http://127.0.0.1:5599) → ragaas-converter 로 텍스트를 뽑아 upload-text 로 등록한다.
// 설계: GoJIRA docs/design-launcher-gateway.md (§5 경로 /v1/docs/{fmt}/text, §6 /launcher/*, §7.2 오류 코드)
import config from '../platform/config';

export type LocalFormat = 'docx' | 'pptx';

export const LOCAL_CONVERT_FORMATS: LocalFormat[] = ['docx', 'pptx'];

const DRM_PREFIX = '<## NASCA DRM FILE';
const TOKEN_HEADER = 'X-Gojira-Launcher-Token';
const SERVICE_NAME = 'ragaas-converter';

export interface ConvertResult {
    text: string;
    format: LocalFormat;
    units: number;
    unit: 'page' | 'slide' | string;
    drm: boolean;
    chars: number;
    elapsedMs: number;
}

export type LocalConvertErrorCode =
    | 'launcher_unavailable'   // 런처 미설치/미기동
    | 'service_not_installed'  // 런처는 있으나 변환기 미설치 (설치 실패 포함)
    | 'requirement_missing'    // Office/PowerShell 없음 (또는 비 Windows)
    | 'convert_failed'         // 문서 열기 실패 (손상, 암호, DRM 미복호화)
    | 'timeout'
    | 'too_large'
    | 'unknown';

export class LocalConvertError extends Error {
    code: LocalConvertErrorCode;
    hint?: string;
    constructor(code: LocalConvertErrorCode, message: string, hint?: string) {
        super(message);
        this.code = code;
        this.hint = hint;
    }
}

interface ErrorBody {
    code?: string;
    error?: string;
    message?: string;
    hint?: string;
    installable?: boolean;
}

const base = () => config.LAUNCHER_BASE.replace(/\/$/, '');

/** 파일 확장자가 로컬 변환 대상(docx/pptx)이면 형식을, 아니면 null. */
export function localFormatOf(filename: string): LocalFormat | null {
    const ext = filename.split('.').pop()?.toLowerCase();
    return (LOCAL_CONVERT_FORMATS as string[]).includes(ext || '') ? (ext as LocalFormat) : null;
}

/** 파일 선두가 NASCA DRM 헤더인지 (선두 32바이트만 읽는다). */
export async function isDrmFile(file: File): Promise<boolean> {
    const head = new Uint8Array(await file.slice(0, 32).arrayBuffer());
    let s = '';
    for (let i = 0; i < Math.min(head.length, DRM_PREFIX.length); i++) s += String.fromCharCode(head[i]);
    return s === DRM_PREFIX;
}

async function fetchWithTimeout(url: string, opts: RequestInit, ms: number): Promise<Response> {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), ms);
    try {
        return await fetch(url, { ...opts, signal: ctrl.signal });
    } finally {
        clearTimeout(t);
    }
}

let cachedToken: string | null = null;

/** 런처 핸드셰이크 — /launcher/health 가 허용 Origin 에만 token 을 준다. 실패 시 launcher_unavailable. */
async function launcherToken(force = false): Promise<string> {
    if (cachedToken !== null && !force) return cachedToken;
    let res: Response;
    try {
        res = await fetchWithTimeout(`${base()}/launcher/health`, { method: 'GET' }, 2500);
    } catch {
        throw new LocalConvertError('launcher_unavailable', '로컬 런처에 연결할 수 없습니다.');
    }
    if (!res.ok) throw new LocalConvertError('launcher_unavailable', `로컬 런처 응답 오류 (${res.status})`);
    const data = await res.json().catch(() => ({}));
    cachedToken = data.token || '';
    return cachedToken as string;
}

/** 런처가 응답하는지 (설치 안내 UI 판단용). */
export async function detectLauncher(): Promise<boolean> {
    try {
        await launcherToken(true);
        return true;
    } catch {
        return false;
    }
}

async function installConverter(token: string): Promise<void> {
    const res = await fetchWithTimeout(
        `${base()}/launcher/services/${SERVICE_NAME}/install`,
        { method: 'POST', headers: { [TOKEN_HEADER]: token } },
        10 * 60 * 1000,
    );
    // 설치 API 는 SSE 진행률을 흘릴 수 있다 — 끝까지 읽어 완료를 기다린다.
    await res.text().catch(() => '');
    if (!res.ok) {
        throw new LocalConvertError('service_not_installed', `로컬 변환기 설치 실패 (${res.status})`);
    }
}

/**
 * docx/pptx 를 로컬에서 텍스트로 변환한다.
 * 변환기가 미설치(409 service_not_installed, installable)면 1회 설치 후 재시도한다.
 */
export async function convertLocally(file: File, format: LocalFormat): Promise<ConvertResult> {
    const token = await launcherToken();
    const send = () =>
        fetchWithTimeout(
            `${base()}/v1/docs/${format}/text`,
            {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/octet-stream',
                    'X-File-Name': encodeURIComponent(file.name),
                    [TOKEN_HEADER]: token,
                },
                body: file,
            },
            5 * 60 * 1000,
        );

    let res: Response;
    try {
        res = await send();
    } catch (e: unknown) {
        if ((e as { name?: string } | null)?.name === 'AbortError') throw new LocalConvertError('timeout', '로컬 변환 시간이 초과되었습니다.');
        cachedToken = null;
        throw new LocalConvertError('launcher_unavailable', '로컬 런처에 연결할 수 없습니다.');
    }

    let body: ErrorBody & Partial<ConvertResult> = await res.json().catch(() => ({}));
    if (res.status === 409 && body?.code === 'service_not_installed' && body?.installable) {
        await installConverter(token);
        res = await send();
        body = await res.json().catch(() => ({}));
    }
    if (res.ok) return body as ConvertResult;

    const msg: string = body?.error || body?.message || `로컬 변환 실패 (${res.status})`;
    switch (res.status) {
        case 401:
        case 403:
            cachedToken = null;
            throw new LocalConvertError('launcher_unavailable', `로컬 런처 인증 실패: ${msg}`);
        case 404:
        case 409:
            throw new LocalConvertError('service_not_installed', msg);
        case 413:
            throw new LocalConvertError('too_large', msg);
        case 424:
            throw new LocalConvertError('requirement_missing', msg);
        case 422:
            throw new LocalConvertError('convert_failed', msg, body?.hint);
        case 504:
            throw new LocalConvertError('timeout', msg);
        default:
            throw new LocalConvertError('unknown', msg);
    }
}

/** 사용자에게 보여줄 안내 문구. */
export function describeLocalConvertError(err: LocalConvertError): string {
    switch (err.code) {
        case 'launcher_unavailable':
            return '로컬 런처가 실행 중이지 않습니다. docx/pptx(DRM 포함) 문서는 PC 의 로컬 런처로 변환해 등록합니다. 런처를 설치·실행한 뒤 다시 시도하세요.';
        case 'service_not_installed':
            return `로컬 변환기(ragaas-converter)를 사용할 수 없습니다. ${err.message}`;
        case 'requirement_missing':
            return `이 PC 에서는 변환할 수 없습니다 (Windows + Microsoft Office 필요). ${err.message}`;
        case 'convert_failed':
            return `문서를 열지 못했습니다: ${err.message}${err.hint ? `\n${err.hint}` : ''}`;
        case 'timeout':
            return '변환 시간이 초과되었습니다. 문서가 매우 크거나 Office 가 응답하지 않습니다.';
        case 'too_large':
            return '파일이 너무 큽니다.';
        default:
            return err.message;
    }
}
