import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { DEMO_MODE } from './demo/flag'

async function bootstrap() {
  if (DEMO_MODE) {
    const { initDemoMode } = await import('./demo')
    await initDemoMode()
  }
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}

bootstrap()
