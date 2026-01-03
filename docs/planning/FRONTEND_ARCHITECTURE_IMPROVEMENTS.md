# Frontend Architecture Improvements

## Overview

This document outlines architectural improvements for the alarm system frontend. The goal is to enhance maintainability, type safety, error resilience, and developer experience.

## Current Tech Stack

- **React 19** with TypeScript 5.9 (strict mode)
- **Vite 7** build tool with ESM
- **TanStack React Query v5** for server state
- **Zustand** with persist middleware for client state
- **React Router v7** for routing
- **Tailwind CSS** + **shadcn/ui** for styling

---

## Improvement Areas

### 1. ✅ Error Handling (COMPLETED)

**Status:** Implemented in Phase 1

**Problem:**
- Single global error boundary crashes entire app
- Empty catch blocks silently swallow errors
- No error categorization or recovery strategies
- Inconsistent error display across components

**Solution:**
- Created centralized error type system with 7 categories
- Built category-specific error handlers
- Implemented feature-level error boundaries for isolation
- Added connection status banner for network feedback
- Global query/mutation error handling with React Query

**Files Created:**
- `lib/errors.ts` - Error type system
- `lib/errorHandler.ts` - Central error handler
- `stores/notificationStore.ts` - Enhanced toast system
- `components/providers/FeatureErrorBoundary.tsx` - Per-feature isolation
- `components/ui/ConnectionStatusBanner.tsx` - Connection feedback
- `hooks/useQueryErrorHandler.ts` - Global query errors
- `hooks/useMutationErrorHandler.ts` - Mutation wrapper

**Detailed Plan:** [FRONTEND_ERROR_HANDLING_PLAN.md](./archived/FRONTEND_ERROR_HANDLING_PLAN.md)

---

### 2. ✅ State Management (COMPLETED)

**Status:** Implemented in Phase 2

**Problem:**
- Monolithic `uiStore` combining unrelated concerns
- Modal system defined but unused, data typed as `unknown`
- Theme sync happening in store action (side effect)
- No separation of concerns

**Solution:**
- Split into focused stores: `layoutStore`, `themeStore`, `modalStore`
- Created type-safe modal registry with discriminated unions
- Moved DOM sync to React effects in providers
- Built reusable modal components

**Files Created:**
- `stores/layoutStore.ts` - Sidebar and mobile state
- `stores/themeStore.ts` - Theme preference only
- `stores/modalStore.ts` - Typed modal registry
- `components/providers/ThemeProvider.tsx` - Theme DOM sync
- `components/providers/LayoutBootstrap.tsx` - Mobile detection
- `components/modals/ConfirmDeleteModal.tsx` - Delete confirmation
- `components/modals/CodeEntryModal.tsx` - Code entry
- `components/modals/ModalProvider.tsx` - Renders all modals

**Detailed Plan:** [FRONTEND_STATE_MANAGEMENT_PLAN.md](./archived/FRONTEND_STATE_MANAGEMENT_PLAN.md)

---

### 3. ✅ Component Architecture (COMPLETED)

**Status:** Implemented in Phase 2

**Problem:**
- Large monolithic hooks (e.g., `useAlarm` with 500+ lines)
- Components mixing business logic with presentation
- No clear separation between smart/dumb components
- Difficult to test and maintain

**Proposed Solution:**

#### 3.1 Split Large Hooks
Break down `useAlarm` into focused hooks:
- `useAlarmState()` - Read alarm state only
- `useAlarmActions()` - Arm, disarm, bypass actions
- `useAlarmSubscription()` - WebSocket updates
- `useAlarmValidation()` - Code validation logic

#### 3.2 Component Patterns
Establish clear patterns:
- **Container components**: Handle data fetching, state, side effects
- **Presentation components**: Receive props, render UI, emit events
- **Hook composition**: Each hook does one thing well

#### 3.3 Examples

**Before:**
```typescript
// AlarmPanel.tsx - 300 lines mixing everything
function AlarmPanel() {
  const { state, arm, disarm, error, loading, validateCode } = useAlarm()
  const [showKeypad, setShowKeypad] = useState(false)
  // ... 200+ lines of logic and JSX
}
```

**After:**
```typescript
// AlarmPanelContainer.tsx - Data and logic
function AlarmPanelContainer() {
  const state = useAlarmState()
  const { arm, disarm } = useAlarmActions()
  const { open: openCodeEntry } = useModal('code-entry')

  const handleArm = (targetState) => {
    openCodeEntry({
      title: 'Enter Code to Arm',
      onSubmit: (code) => arm(targetState, code)
    })
  }

  return <AlarmPanel state={state} onArm={handleArm} onDisarm={handleDisarm} />
}

// AlarmPanel.tsx - Pure presentation
function AlarmPanel({ state, onArm, onDisarm }) {
  // Only rendering logic, no business logic
}
```

**Impact:**
- Easier to test (props in, events out)
- Better code reuse
- Clearer responsibilities

---

### 4. ✅ Type Safety Improvements (COMPLETED)

**Status:** Implemented

**Detailed Plan:** [FRONTEND_TYPE_SAFETY_PLAN.md](./archived/FRONTEND_TYPE_SAFETY_PLAN.md)

**Problem:**
- API responses typed as `any` in some places
- Missing discriminated unions for polymorphic data
- Incomplete type coverage for WebSocket messages
- Type assertions (`as`) used instead of proper guards

**Solution:**
- Created comprehensive type guard library with runtime validation
- Added `HealthPayload` type and converted WebSocket messages to discriminated union
- Implemented safe form helpers for select/input value extraction
- Created centralized error type system with safe message extraction
- Added rule definition validation with proper type guards
- Eliminated all unsafe type assertions across codebase

**Files Created:**
- `lib/typeGuards.ts` - Type guard functions for all unions and common types
- `lib/validation.ts` - Assertion functions and safe parsing utilities
- `lib/formHelpers.ts` - Safe form value extraction helpers
- `types/errors.ts` - Error type definitions and extraction helpers
- `types/ruleDefinition.ts` - Rule definition types and validation

**Files Updated:**
- `types/alarm.ts` - Added HealthPayload, discriminated union
- `services/api.ts` - Safe error parsing, response validation
- `components/providers/AlarmRealtimeProvider.tsx` - Payload validation
- `pages/RulesPage.tsx` - Rule definition safety
- `pages/CodesPage.tsx` - Safe select handling
- `pages/SettingsPage.tsx` - Safe record operations
- `hooks/useAlarmActions.ts`, `hooks/useAlarm.ts`, `hooks/useAuth.ts` - Error handling
- `lib/errors.ts` - Type guard usage
- `lib/errorHandler.ts` - Fixed function wrapper typing

**Original Proposed Solution (for reference):**

#### 4.1 Eliminate `any` Types
Audit codebase for `any` and replace with proper types:
```typescript
// Before
const response: any = await api.get('/alarm/state')

// After
import { AlarmStateResponse } from '@/types/api'
const response = await api.get<AlarmStateResponse>('/alarm/state')
```

#### 4.2 Add Type Guards
For runtime type checking:
```typescript
export function isAlarmState(data: unknown): data is AlarmState {
  return (
    typeof data === 'object' &&
    data !== null &&
    'currentState' in data &&
    typeof data.currentState === 'string'
  )
}
```

#### 4.3 WebSocket Message Types
Discriminated union for all message types:
```typescript
type WebSocketMessage =
  | { type: 'alarm_state'; payload: AlarmState }
  | { type: 'sensor_update'; payload: Sensor }
  | { type: 'event'; payload: AlarmEvent }
```

**Impact:**
- Catch errors at compile time
- Better autocomplete
- Safer refactoring

---

### 5. ⏳ Data Fetching Patterns

**Status:** Not Started

**Problem:**
- Inconsistent use of React Query features
- No optimistic updates for mutations
- Missing query invalidation in some flows
- No prefetching for predictable navigation

**Proposed Solution:**

#### 5.1 Optimistic Updates
For instant UI feedback:
```typescript
const updateSensorMutation = useMutation({
  mutationFn: sensorService.update,
  onMutate: async (newSensor) => {
    await queryClient.cancelQueries({ queryKey: ['sensors', newSensor.id] })
    const previous = queryClient.getQueryData(['sensors', newSensor.id])
    queryClient.setQueryData(['sensors', newSensor.id], newSensor)
    return { previous }
  },
  onError: (err, newSensor, context) => {
    queryClient.setQueryData(['sensors', newSensor.id], context?.previous)
  },
})
```

#### 5.2 Query Key Factory
Centralize query key management:
```typescript
export const queryKeys = {
  alarm: {
    all: ['alarm'] as const,
    state: () => [...queryKeys.alarm.all, 'state'] as const,
    events: (filters: EventFilters) => [...queryKeys.alarm.all, 'events', filters] as const,
  },
  sensors: {
    all: ['sensors'] as const,
    list: (filters: SensorFilters) => [...queryKeys.sensors.all, 'list', filters] as const,
    detail: (id: string) => [...queryKeys.sensors.all, 'detail', id] as const,
  },
}
```

#### 5.3 Prefetch on Hover
```typescript
const prefetchSensorDetails = (id: string) => {
  queryClient.prefetchQuery({
    queryKey: queryKeys.sensors.detail(id),
    queryFn: () => sensorService.getById(id),
  })
}

// In component
<SensorRow onMouseEnter={() => prefetchSensorDetails(sensor.id)} />
```

**Impact:**
- Faster perceived performance
- Better UX with optimistic updates
- Consistent caching strategy

---

### 6. ⏳ Performance Optimization

**Status:** Not Started

**Problem:**
- No code splitting beyond lazy route loading
- Large component re-renders on minor state changes
- Missing React.memo on expensive components
- No virtualization for long lists

**Proposed Solution:**

#### 6.1 Component Code Splitting
Split large features:
```typescript
const RulesEngine = lazy(() => import('@/features/rules/RulesEngine'))
const SensorManager = lazy(() => import('@/features/sensors/SensorManager'))
```

#### 6.2 Memoization
For expensive computations:
```typescript
const sortedSensors = useMemo(
  () => sensors.sort((a, b) => a.name.localeCompare(b.name)),
  [sensors]
)

const SensorRow = memo(({ sensor, onEdit }: SensorRowProps) => {
  // Only re-renders when sensor or onEdit changes
})
```

#### 6.3 Virtual Lists
For events, sensors, rules lists:
```typescript
import { useVirtualizer } from '@tanstack/react-virtual'

function EventsList({ events }: { events: AlarmEvent[] }) {
  const parentRef = useRef<HTMLDivElement>(null)

  const virtualizer = useVirtualizer({
    count: events.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 60, // Row height in pixels
  })

  // Render only visible rows
}
```

#### 6.4 Zustand Selectors
Prevent unnecessary re-renders:
```typescript
// Before - entire store subscription
const { theme, isMobile, sidebarOpen } = useLayoutStore()

// After - only subscribe to what you need
const theme = useLayoutStore((s) => s.theme)
```

**Impact:**
- Faster initial load
- Smoother scrolling
- Reduced bundle size

---

### 7. ⏳ Testing Infrastructure

**Status:** Not Started

**Problem:**
- No component tests
- No integration tests
- Manual testing only
- Difficult to catch regressions

**Proposed Solution:**

#### 7.1 Unit Tests (Vitest)
For utilities, hooks, stores:
```typescript
describe('categorizeError', () => {
  it('categorizes 401 as auth error', () => {
    const error = { code: '401', message: 'Unauthorized' }
    const result = categorizeError(error)
    expect(result.category).toBe('auth')
  })
})
```

#### 7.2 Component Tests (React Testing Library)
For UI components:
```typescript
describe('AlarmPanel', () => {
  it('shows disarmed state', () => {
    render(<AlarmPanel state="disarmed" onArm={vi.fn()} />)
    expect(screen.getByText('Disarmed')).toBeInTheDocument()
  })

  it('calls onArm when arm button clicked', async () => {
    const onArm = vi.fn()
    render(<AlarmPanel state="disarmed" onArm={onArm} />)
    await userEvent.click(screen.getByRole('button', { name: /arm/i }))
    expect(onArm).toHaveBeenCalled()
  })
})
```

#### 7.3 E2E Tests (Playwright)
For critical user flows:
```typescript
test('user can arm and disarm alarm', async ({ page }) => {
  await page.goto('/dashboard')
  await page.click('text=Arm Away')
  await page.fill('[data-testid="code-input"]', '1234')
  await page.click('text=Submit')
  await expect(page.locator('text=Armed Away')).toBeVisible()
})
```

**Impact:**
- Catch bugs before production
- Safe refactoring
- Documented behavior

---

### 8. ⏳ Developer Experience

**Status:** Not Started

**Problem:**
- No Storybook for component development
- Limited TypeScript path aliases
- Missing ESLint rules for best practices
- No pre-commit hooks

**Proposed Solution:**

#### 8.1 Storybook
Isolate component development:
```typescript
// AlarmPanel.stories.tsx
export default {
  title: 'Alarm/AlarmPanel',
  component: AlarmPanel,
}

export const Disarmed: Story = {
  args: {
    state: 'disarmed',
    onArm: fn(),
  },
}

export const ArmedAway: Story = {
  args: {
    state: 'armed_away',
    onDisarm: fn(),
  },
}
```

#### 8.2 Additional Path Aliases
```json
{
  "compilerOptions": {
    "paths": {
      "@/components/*": ["./src/components/*"],
      "@/hooks/*": ["./src/hooks/*"],
      "@/stores/*": ["./src/stores/*"],
      "@/features/*": ["./src/features/*"],
      "@/utils/*": ["./src/lib/utils/*"]
    }
  }
}
```

#### 8.3 Enhanced ESLint Config
```json
{
  "rules": {
    "react/jsx-no-leaked-render": "error",
    "react-hooks/exhaustive-deps": "error",
    "@typescript-eslint/no-floating-promises": "error",
    "@typescript-eslint/no-misused-promises": "error",
    "no-console": ["warn", { "allow": ["warn", "error"] }]
  }
}
```

#### 8.4 Pre-commit Hooks (Husky + lint-staged)
```json
{
  "lint-staged": {
    "*.{ts,tsx}": ["eslint --fix", "prettier --write"],
    "*.{json,css,md}": ["prettier --write"]
  }
}
```

**Impact:**
- Faster development
- Consistent code style
- Fewer bugs

---

## Implementation Roadmap

### Phase 1: Foundation ✅ COMPLETE
- [x] Error handling system
- [x] State management refactor
- [x] Modal system

### Phase 2: Architecture ✅ COMPLETE
- [x] Split large hooks and components
- [x] Establish container/presentation pattern
- [x] Type safety improvements

### Phase 3: Performance
- [ ] Code splitting
- [ ] Memoization audit
- [ ] Virtual lists for long data

### Phase 4: Quality
- [ ] Testing infrastructure
- [ ] Storybook setup
- [ ] Developer tooling

---

## Success Metrics

After completing all improvements:

- **Error Resilience**: No single component crash breaks entire app
- **Type Safety**: Zero `any` types in application code
- **Performance**: Initial load < 2s, route transitions < 200ms
- **Test Coverage**: > 80% for critical paths
- **Developer Experience**: New features take 30% less time to implement
- **Bundle Size**: < 500KB gzipped for initial bundle

---

## Notes

- Improvements are designed to be incremental and non-breaking
- Each phase can be implemented independently
- Existing functionality maintained throughout migration
- All changes maintain backward compatibility during transition
