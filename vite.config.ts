import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig({plugins:[vue()],server:{host:'0.0.0.0',port:4173,allowedHosts:['terminal.local']},build:{rollupOptions:{output:{manualChunks:{three:['three'],charts:['echarts']}}}}})
