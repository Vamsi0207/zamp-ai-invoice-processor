import { defineConfig } from '@playwright/test'
import path from 'node:path'

export default defineConfig({
  testDir: './e2e', workers: 1, timeout: 45000, fullyParallel: false,
  reporter: 'list',
  use: { baseURL: 'http://127.0.0.1:5178', viewport: { width: 1440, height: 1100 }, screenshot: 'only-on-failure', trace: 'retain-on-failure',
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {} },
  webServer: [
    { command: '.venv/bin/python -m scripts.e2e_server', cwd: path.resolve('..'), url: 'http://127.0.0.1:8911/health', reuseExistingServer: false, env: { GEMINI_API_KEY: '', OPENAI_API_KEY: '' } },
    { command: 'npm run dev -- --port 5178 --strictPort', url: 'http://127.0.0.1:5178', reuseExistingServer: false, env: { ZAMP_API_TARGET: 'http://127.0.0.1:8911' } },
  ],
})
