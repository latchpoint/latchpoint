import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { DEMO_MODE } from './demo/flag'

async function bootstrap() {
  if (DEMO_MODE) {
    try {
      const { initDemoMode } = await import('./demo')
      await initDemoMode()
    } catch (err) {
      // MSW worker registration can fail (e.g. service workers blocked, missing
      // mockServiceWorker.js asset). Mount the app anyway so the failure is
      // visible in the console instead of leaving the visitor on a blank page.
      console.error('[demo] init failed; mounting app without MSW', err)
    }
  }
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}

bootstrap().catch((err) => {
  console.error('[bootstrap] fatal error', err)
})
