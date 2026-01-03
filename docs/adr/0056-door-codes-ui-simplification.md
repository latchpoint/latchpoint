# ADR 0056: Door Codes UI Simplification

## Status
**Implemented**

## Context
The Door Codes page currently uses a separate `DoorCodesTargetUserCard` component to select which user's codes to manage. This differs from the Alarm Codes page, which uses an inline `CodesUserSelector` dropdown within the main management card.

The current Door Codes UI:
- Has a separate "Target User" card with its own title and styling
- Uses the term "Target User" which is unclear
- Creates visual inconsistency with the Alarm Codes page

## Decision
Simplify the Door Codes UI to match the Alarm Codes pattern:

### Changes

#### Frontend

1. **Remove `DoorCodesTargetUserCard` component**
   - Delete `frontend/src/features/doorCodes/components/DoorCodesTargetUserCard.tsx`

2. **Create `DoorCodesOwnerSelector` component**
   - Create `frontend/src/features/doorCodes/components/DoorCodesOwnerSelector.tsx`
   - Match the pattern of `frontend/src/features/codes/components/CodesUserSelector.tsx`
   - Use label "Owner" (not "Target User")
   - Simple dropdown only (no extra display/input fields)
   - Add tooltip: "The user this code belongs to"

3. **Update `DoorCodesPage.tsx`**
   - Replace `DoorCodesTargetUserCard` with inline `DoorCodesOwnerSelector` inside `DoorCodeCreateCard` section
   - Structure should match `CodesPage.tsx` pattern

4. **Update Alarm Codes page for consistency**
   - Rename `CodesUserSelector` to `CodesOwnerSelector`
   - Change label from "User" to "Owner"
   - Add tooltip: "The user this code belongs to"

### UI Pattern (matching across both pages)

```
┌─────────────────────────────────────────┐
│ Manage Door Codes                       │
│                                         │
│ Owner: [Dropdown ▼] ⓘ                   │
│        tooltip: "The user this code     │
│                  belongs to"            │
│                                         │
│ [Create Code Form...]                   │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ Door Codes (Selected User Name)         │
│                                         │
│ [Code cards...]                         │
└─────────────────────────────────────────┘
```

## Files to Modify

| File | Action |
|------|--------|
| `frontend/src/features/doorCodes/components/DoorCodesTargetUserCard.tsx` | Delete |
| `frontend/src/features/doorCodes/components/DoorCodesOwnerSelector.tsx` | Create (new) |
| `frontend/src/pages/DoorCodesPage.tsx` | Update imports and layout |
| `frontend/src/features/codes/components/CodesUserSelector.tsx` | Rename to `CodesOwnerSelector`, add tooltip |
| `frontend/src/pages/CodesPage.tsx` | Update import, use "Owner" label |

## Alternatives Considered
- Keep the separate card but rename "Target User" to "Owner"
  - Rejected: still inconsistent with Alarm Codes page

## Consequences
- Consistent UI pattern between Alarm Codes and Door Codes pages
- Clearer terminology ("Owner" instead of "Target User" or "User")
- Tooltips provide clarity on what "Owner" means
- Simpler component structure (one fewer card)
- Reduced visual clutter for admins
