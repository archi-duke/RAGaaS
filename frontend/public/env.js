// dev/standalone 기본값 — 컨테이너에서는 entrypoint.sh 가 실제 env 로 이 파일을 덮어쓴다 (계약 05 §5).
// 값이 비면 config.ts 의 폴백(상대경로 프록시)이 적용된다.
window._env_ = {};
