// Compile-time flag for demo mode. Lives in its own module (no side-effect
// imports) so non-demo bundles can read DEMO_MODE without pulling in MSW,
// fixtures, or any other demo-only code via the static import graph.
export const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === 'true'
