import { Navigate } from 'react-router'

export function SettingsIndexRedirect() {
  return <Navigate to="alarm" replace />
}

export default SettingsIndexRedirect

