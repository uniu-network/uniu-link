import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [
    vue({ template: { compilerOptions: { isCustomElement: (tag) => tag.startsWith('fluent-') } } }),
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api/': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/v1/': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
    historyApiFallback: true,
  },
})
