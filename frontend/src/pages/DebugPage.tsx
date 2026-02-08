import { Page } from '@/components/layout'
import { EntityStateInspector } from '@/features/debug/components/EntityStateInspector'

function DebugPage() {
  return (
    <Page title="Debug" description="Diagnostic tools for inspecting system state.">
      <EntityStateInspector />
    </Page>
  )
}

export default DebugPage
