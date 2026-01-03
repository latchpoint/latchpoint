/**
 * AlarmPanel - Main alarm control panel component.
 *
 * This file re-exports the container component for backward compatibility.
 * The implementation has been split into:
 * - AlarmPanelContainer: Business logic, hooks, and data fetching
 * - AlarmPanelView: Pure presentation component
 */

export { AlarmPanelContainer as AlarmPanel } from './AlarmPanelContainer'
export { AlarmPanelView } from './AlarmPanelView'
export { AlarmPanelContainer as default } from './AlarmPanelContainer'
