import { Navigate } from 'react-router-dom'

export function DebugIndexRedirect() {
  return <Navigate to="entities" replace />
}

export default DebugIndexRedirect
