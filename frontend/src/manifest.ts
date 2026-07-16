// MF './manifest' — 셸(NETRIX platform-app)이 스코프 진입 시 로드하는 제품 메타.
// 순수 데이터만 (컴포넌트/사이드이펙트 금지 — 초경량 청크 유지). 계약: PLATFORM-MF-CONTRACT.md §1
//   name  : /ragaas 스코프 타이틀바 브랜드명
//   menus : 셸 타이틀바 메뉴. key 는 셸 page prop / onNavigate 보고 키와 같은 네임스페이스.
//           pages 는 이 메뉴를 활성으로 유지할 내부 페이지 키(App.tsx ShellBridge 가 보고).
export default {
  name: 'RAGaaS',
  menus: [
    { key: 'knowledges', label: 'Knowledges', pages: ['kb', 'graph'] },
  ],
};
