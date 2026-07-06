import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { federation } from '@module-federation/vite'

// RAGaaS-App — 플랫폼 MF remote (docs/platform-contract/01 §2)
// - expose './App' 표준 진입점, shared singleton 은 react/react-dom 만
//   (requiredVersion 은 package.json range 자동 — 수동 고정 금지, 계약 01 §4)
// - '@platform/web-ui' singleton 은 Phase 2(Kendo 이관) 시점에 추가
// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    federation({
      name: 'ragaasApp',
      filename: 'remoteEntry.js',
      dts: false,
      exposes: {
        './App': './src/App',
      },
      shared: {
        react: { singleton: true },
        'react-dom': { singleton: true },
      },
    }),
  ],
  // CRA 관례(REACT_APP_*) env 키를 dev 에서 import.meta.env 로 노출 (계약 01 §1)
  envPrefix: ['REACT_APP_', 'VITE_'],
  server: {
    host: '0.0.0.0',
    port: 3002,
    strictPort: true,
    // dev 에서 셸(:3000)이 remoteEntry/chunk 를 크로스오리진 로드
    cors: true,
    proxy: {
      '/ingest-api': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/ingest-api/, '/api/v2'),
      },
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    target: 'chrome89', // MF 2.0 (top-level await) 요구
  },
})
