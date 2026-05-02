/**
 * Sticky banner for demo mode. Renders only when DEMO_MODE is true.
 * The Reset button hard-reloads the page; module-level stores re-init from
 * fixtures, satisfying the "no persistence" guarantee from ADR-0089.
 */

export function DemoBanner() {
  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        zIndex: 9999,
        background: 'linear-gradient(90deg, #f59e0b 0%, #ef4444 100%)',
        color: 'white',
        padding: '6px 16px',
        fontSize: 13,
        fontWeight: 500,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        boxShadow: '0 1px 4px rgba(0,0,0,0.2)',
      }}
    >
      <span>
        🎭 Demo mode — nothing is saved. All data is in-memory and resets on refresh.
      </span>
      <button
        type="button"
        onClick={() => window.location.reload()}
        style={{
          background: 'rgba(255,255,255,0.2)',
          border: '1px solid rgba(255,255,255,0.4)',
          color: 'white',
          padding: '2px 12px',
          borderRadius: 4,
          cursor: 'pointer',
          fontSize: 12,
          fontWeight: 600,
        }}
      >
        Reset
      </button>
    </div>
  )
}
