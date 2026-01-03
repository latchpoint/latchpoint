# Frontend Type Safety Improvements Plan

> Archived: implemented; kept for historical context.

## Overview

This document outlines the implementation plan for improving type safety across the frontend codebase. The goal is to eliminate unsafe type assertions, add runtime validation, and create proper type guards for all union types.

## Audit Summary

| Severity | Count | Description |
|----------|-------|-------------|
| Critical | 5 | Generic `as T` assertions, missing payload types |
| High | 8 | Unsafe Record assertions, unvalidated parsing |
| Medium | 16 | Enum casts, payload casts, error shape assumptions |
| Low | 4 | Redundant or unnecessary casts |

---

## Implementation Plan

### Phase 1: Type Guards & Validation Utilities

Create centralized type guard functions and validation utilities.

#### 1.1 Create `lib/typeGuards.ts`

```typescript
// Type guards for all discriminated unions and common types

// WebSocket message payload guards
export function isAlarmStatePayload(payload: unknown): payload is AlarmStatePayload {
  return (
    typeof payload === 'object' &&
    payload !== null &&
    'state' in payload &&
    isAlarmStateSnapshot((payload as Record<string, unknown>).state)
  )
}

export function isAlarmEventPayload(payload: unknown): payload is AlarmEventPayload {
  return (
    typeof payload === 'object' &&
    payload !== null &&
    'event' in payload &&
    isAlarmEvent((payload as Record<string, unknown>).event)
  )
}

export function isCountdownPayload(payload: unknown): payload is CountdownPayload {
  return (
    typeof payload === 'object' &&
    payload !== null &&
    'remaining' in payload &&
    typeof (payload as Record<string, unknown>).remaining === 'number'
  )
}

export function isHealthPayload(payload: unknown): payload is HealthPayload {
  return (
    typeof payload === 'object' &&
    payload !== null &&
    'status' in payload
  )
}

// Alarm state guards
export function isAlarmStateSnapshot(data: unknown): data is AlarmStateSnapshot {
  return (
    typeof data === 'object' &&
    data !== null &&
    'current_state' in data &&
    typeof (data as Record<string, unknown>).current_state === 'string'
  )
}

export function isAlarmEvent(data: unknown): data is AlarmEvent {
  return (
    typeof data === 'object' &&
    data !== null &&
    'event_type' in data &&
    'timestamp' in data
  )
}

// Enum validators
export function isWhenOperator(value: unknown): value is WhenOperator {
  return value === 'all' || value === 'any'
}

export function isAlarmArmMode(value: unknown): value is AlarmArmMode {
  return ['away', 'home', 'night', 'vacation', 'custom'].includes(value as string)
}

// Record validators
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function isStringRecord(value: unknown): value is Record<string, string> {
  if (!isRecord(value)) return false
  return Object.values(value).every(v => typeof v === 'string')
}
```

#### 1.2 Create `lib/validation.ts`

```typescript
// Runtime validation for API responses using assertion functions

export function assertDefined<T>(value: T | null | undefined, message?: string): asserts value is T {
  if (value === null || value === undefined) {
    throw new Error(message ?? 'Value is null or undefined')
  }
}

export function assertRecord(value: unknown, message?: string): asserts value is Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(message ?? 'Value is not a record')
  }
}

// Safe JSON parsing with validation
export function parseJsonAs<T>(
  json: string,
  validator: (data: unknown) => data is T,
  errorMessage?: string
): T {
  const parsed = JSON.parse(json)
  if (!validator(parsed)) {
    throw new Error(errorMessage ?? 'Invalid JSON structure')
  }
  return parsed
}

// Safe property access
export function getProperty<T>(
  obj: Record<string, unknown>,
  key: string,
  validator: (value: unknown) => value is T
): T | undefined {
  const value = obj[key]
  return validator(value) ? value : undefined
}
```

---

### Phase 2: WebSocket Type Safety

Fix WebSocket message handling with proper discriminated unions.

#### 2.1 Update `types/alarm.ts`

Add missing `HealthPayload` type and fix the discriminated union:

```typescript
// Add HealthPayload
export interface HealthPayload {
  status: 'healthy' | 'degraded' | 'unhealthy'
  timestamp: string
  details?: Record<string, unknown>
}

// Update AlarmWebSocketMessage to be a proper discriminated union
export type AlarmWebSocketMessage =
  | { type: 'alarm_state'; payload: AlarmStatePayload }
  | { type: 'event'; payload: AlarmEventPayload }
  | { type: 'countdown'; payload: CountdownPayload }
  | { type: 'health'; payload: HealthPayload }
```

#### 2.2 Update `components/providers/AlarmRealtimeProvider.tsx`

Replace unsafe casts with type guards:

```typescript
// Before (unsafe)
case 'alarm_state':
  const statePayload = message.payload as { state: AlarmStateSnapshot }

// After (safe)
case 'alarm_state':
  if (!isAlarmStatePayload(message.payload)) {
    console.error('Invalid alarm_state payload', message.payload)
    return
  }
  const { state } = message.payload
```

---

### Phase 3: API Response Validation

Fix unsafe API response handling.

#### 3.1 Update `services/api.ts`

**Fix 1: Empty object fallback (line 175)**

```typescript
// Before
if (response.status === 204) {
  return {} as T
}

// After - use void/undefined for 204 responses
if (response.status === 204) {
  return undefined as T  // Or better: change method signature to return T | undefined
}
```

**Fix 2: Add response validation option**

```typescript
interface RequestOptions<T> {
  // ... existing options
  validate?: (data: unknown) => data is T
}

// In request method
if (options.validate && !options.validate(result)) {
  throw new ApiError('Response validation failed', 'validation_error')
}
return result
```

**Fix 3: Safe error parsing**

```typescript
// Create proper error response type
interface ApiErrorResponse {
  detail?: string
  message?: string
  non_field_errors?: string[]
  [field: string]: unknown
}

function isApiErrorResponse(data: unknown): data is ApiErrorResponse {
  return isRecord(data)
}

// Use in error handling
if (isApiErrorResponse(parsed)) {
  // Safe to access properties
}
```

---

### Phase 4: Form & Event Handler Safety

Fix unsafe casts from HTML elements.

#### 4.1 Create `lib/formHelpers.ts`

```typescript
// Safe select value extraction with validation
export function getSelectValue<T extends string>(
  event: React.ChangeEvent<HTMLSelectElement>,
  validator: (value: string) => value is T,
  fallback: T
): T {
  const value = event.target.value
  return validator(value) ? value : fallback
}

// Safe input value extraction
export function getInputValue(event: React.ChangeEvent<HTMLInputElement>): string {
  return event.target.value
}
```

#### 4.2 Update components using select casts

```typescript
// Before (RulesPage.tsx line 584)
onChange={(e) => updateWhen({ op: e.target.value as WhenOperator })}

// After
onChange={(e) => {
  const op = getSelectValue(e, isWhenOperator, 'all')
  updateWhen({ op })
}}
```

---

### Phase 5: Error Type Safety

Fix error shape assumptions throughout the codebase.

#### 5.1 Create `types/errors.ts`

```typescript
// Standardized error shapes
export interface ErrorWithMessage {
  message: string
}

export interface ErrorWithCode {
  code: string
  message?: string
}

export function hasMessage(error: unknown): error is ErrorWithMessage {
  return (
    isRecord(error) &&
    'message' in error &&
    typeof error.message === 'string'
  )
}

export function getErrorMessage(error: unknown): string {
  if (hasMessage(error)) return error.message
  if (typeof error === 'string') return error
  return 'An unknown error occurred'
}
```

#### 5.2 Update error handling in hooks

```typescript
// Before (useAlarmActions.ts line 68)
const errorMessage = (error as { message?: string } | null)?.message

// After
const errorMessage = getErrorMessage(error)
```

---

### Phase 6: Rule Definition Type Safety

Fix rule definition parsing in RulesPage.

#### 6.1 Create `types/ruleDefinition.ts`

```typescript
// Strongly typed rule definition structure
export interface RuleDefinition {
  when: {
    op: WhenOperator
    conditions: RuleCondition[]
  }
  then: RuleAction[]
}

export function isRuleDefinition(data: unknown): data is RuleDefinition {
  if (!isRecord(data)) return false
  if (!('when' in data) || !('then' in data)) return false

  const when = data.when
  if (!isRecord(when)) return false
  if (!isWhenOperator(when.op)) return false
  if (!Array.isArray(when.conditions)) return false

  if (!Array.isArray(data.then)) return false

  return true
}
```

#### 6.2 Update RulesPage.tsx

```typescript
// Before (line 251-253)
const def = rule.definition as unknown
const asObj = def as Record<string, unknown>

// After
if (!isRuleDefinition(rule.definition)) {
  console.error('Invalid rule definition', rule.definition)
  return defaultFormState
}
const { when, then } = rule.definition
```

---

## Files to Create

| File | Purpose |
|------|---------|
| `lib/typeGuards.ts` | Type guard functions for all unions |
| `lib/validation.ts` | Runtime validation utilities |
| `lib/formHelpers.ts` | Safe form value extraction |
| `types/errors.ts` | Error type definitions and guards |
| `types/ruleDefinition.ts` | Rule definition types and guards |

## Files to Modify

| File | Changes |
|------|---------|
| `types/alarm.ts` | Add HealthPayload, fix discriminated union |
| `services/api.ts` | Add response validation, fix empty object fallback |
| `components/providers/AlarmRealtimeProvider.tsx` | Use type guards for payloads |
| `pages/RulesPage.tsx` | Use type guards for definitions and enums |
| `pages/CodesPage.tsx` | Use type guards for select values |
| `pages/SettingsPage.tsx` | Use type guards for record operations |
| `hooks/useAlarmActions.ts` | Use getErrorMessage helper |
| `hooks/useAuth.ts` | Use getErrorMessage helper |
| `hooks/useAlarm.ts` | Use getErrorMessage helper |
| `lib/errors.ts` | Use type guards instead of casts |
| `lib/errorHandler.ts` | Fix function wrapper typing |

---

## Implementation Order

1. **Create utility files** (typeGuards, validation, formHelpers)
2. **Fix types/alarm.ts** - Add HealthPayload
3. **Fix services/api.ts** - Response validation
4. **Fix AlarmRealtimeProvider.tsx** - WebSocket safety
5. **Fix RulesPage.tsx** - Rule definition safety
6. **Fix remaining components** - Form handlers, error shapes
7. **Fix hooks** - Error message extraction

---

## Success Criteria

- [ ] Zero `as` type assertions (except `as const`)
- [ ] All WebSocket payloads validated at runtime
- [ ] API responses validated before use
- [ ] Form values validated before casting
- [ ] Error shapes validated before property access
- [ ] TypeScript strict mode passes with no errors

---

## Notes

- Type guards add minimal runtime overhead
- Validation errors should be logged for debugging
- Consider using Zod for complex schema validation in future
- All changes are backward compatible
