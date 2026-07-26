import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

async function bootstrap() {
  // Read the env flag inline rather than importing DEMO_MODE from './demo/flag'.
  // Rolldown folds `import.meta.env.VITE_DEMO_MODE` at this call site, so a
  // non-demo build drops the dynamic import below AND the module it points at.
  // Importing the constant across a module boundary defeated that: the branch
  // was still eliminated, but the demo module was emitted as an unreachable
  // ~457 kB chunk. See ADR-0106, Track A.2.
  if (import.meta.env.VITE_DEMO_MODE === 'true') {
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
