import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// base: './' 让打包后的页面能从本地文件加载；本地应用不在乎单文件体积
export default defineConfig({ base: './', plugins: [vue()], build: { chunkSizeWarningLimit: 1500 } })
