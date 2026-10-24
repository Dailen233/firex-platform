import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
// 本机 inotify 实例上限（fs.inotify.max_user_instances=128）易被编辑器/多进程占满，
// 导致 vite dev 的 fs.watch 报 EMFILE。这里提供显式 polling 开关，默认保持 inotify 原行为。
// polling 代价：周期性 stat 全量监听文件，CPU 略高、变更延迟约 interval；仅需时用 dev:polling 开启。
const usePolling = process.env.VITE_USE_POLLING === 'true'
const pollingInterval = Number(process.env.VITE_POLLING_INTERVAL) || 300
// Backend origin for the dev proxy. 8001 belongs to another project; the fixture
// backend runs on 8002. Override with VITE_BACKEND_ORIGIN when needed.
const backendTarget = process.env.VITE_BACKEND_ORIGIN || 'http://127.0.0.1:8002'
export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 4173,
    allowedHosts: ['terminal.local'],
    proxy: {
      '/health': { target: backendTarget, changeOrigin: true },
      '/api': { target: backendTarget, changeOrigin: true },
    },
    ...(usePolling ? { watch: { usePolling: true, interval: pollingInterval } } : {}),
  },
  build: {
    rollupOptions: { output: { manualChunks: { three: ['three'], charts: ['echarts'] } } },
  },
})
