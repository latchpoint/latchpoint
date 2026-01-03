import { Navigate } from 'react-router-dom'

export function SettingsIndexRedirect() {
  return <Navigate to="alarm" replace />
}

export default SettingsIndexRedirect

