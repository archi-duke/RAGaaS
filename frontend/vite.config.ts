import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { federation } from '@module-federation/vite'

// base: 셸(NETRIX Platform) 임베드 시 게이트웨이 /ragaas/ 프리픽스로 서빙된다
// (자산·API 경로가 이 값 기준 — App/api.ts 가 import.meta.env.BASE_URL 로 파생).
// dev 서버는 '/' 유지 (vite proxy 로 백엔드 연결).
export default defineConfig(({ command }) => ({
  base: command === 'build' ? '/ragaas/' : '/',
  plugins: [
    react(),
    // Module Federation remote — 셸(Platform-App)이 ragaasApp/App 을 마운트한다.
    // shared react/react-dom 은 loose singleton: 셸(React 19)을 단일 인스턴스로 공유.
    federation({
      name: 'ragaasApp',
      filename: 'remoteEntry.js',
      dts: false, // TS 앱이지만 remote 타입 산출물 불필요 — dts-plugin 노이즈 제거
      exposes: {
        './App': './src/App.tsx',
        './manifest': './src/manifest.ts', // 제품 메타 (name/menus) — 셸 타이틀바 브랜딩
      },
      shared: {
        react: { singleton: true, requiredVersion: false },
        'react-dom': { singleton: true, requiredVersion: false },
      },
    }),
  ],
  build: {
    target: 'chrome89', // MF 2.0 (top-level await) 요구
  },
  server: {
    host: '0.0.0.0',
    proxy: {
      '/ingest-api': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/ingest-api/, '/api'),
      },
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
}))
