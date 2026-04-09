import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'
import fs from 'fs'
import { execSync } from 'child_process'

function isRunningInDocker(): boolean {
  return fs.existsSync('/.dockerenv')
}

function readVersionFromToml(): string {
  try {
    const tomlPath = path.resolve(__dirname, '../pyproject.toml')
    const content = fs.readFileSync(tomlPath, 'utf-8')
    const match = content.match(/^version\s*=\s*"(.+)"/m)
    return match?.[1] ?? '0.0.0'
  } catch {
    return '0.0.0'
  }
}

function getGitCommitShort(): string {
  try {
    return execSync('git rev-parse --short HEAD', { encoding: 'utf-8' }).trim()
  } catch {
    return 'dev'
  }
}

function toWebSocketTarget(httpTarget: string): string {
  if (httpTarget.startsWith('https://')) return httpTarget.replace('https://', 'wss://')
  if (httpTarget.startsWith('http://')) return httpTarget.replace('http://', 'ws://')
  return httpTarget
}

// In unified container: Vite and Daphne run in same container
// Outside Docker: proxy to localhost:5427
const apiProxyTarget =
  process.env.VITE_API_PROXY_TARGET ??
  (isRunningInDocker() ? 'http://127.0.0.1:8000' : 'http://localhost:5427')

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    __APP_VERSION__: JSON.stringify(process.env.VITE_APP_VERSION || readVersionFromToml()),
    __GIT_COMMIT__: JSON.stringify(process.env.VITE_GIT_COMMIT || getGitCommitShort()),
    __REPO_URL__: JSON.stringify(process.env.VITE_REPO_URL || 'https://github.com/latchpoint/latchpoint'),
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    clearMocks: true,
    restoreMocks: true,
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
      '/ws': {
        target: toWebSocketTarget(apiProxyTarget),
        ws: true,
      },
    },
  },
})
