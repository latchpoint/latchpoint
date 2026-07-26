import { Navigate } from 'react-router'

export function DebugIndexRedirect() {
  return <Navigate to="entities" replace />
}

export default DebugIndexRedirect
