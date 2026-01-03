# ADR 0052: Responsive Integration Overview Cards

## Status
Implemented

## Context

The integration settings pages each feature an "Overview Card" (IntegrationOverviewCard) as the first card. These cards contain:
- Title with icon
- Description text
- Enable/disable toggle with help text
- Status pills (connection state, error indicators)
- Action buttons (Refresh, Reset, Save, Test Connection, Sync Devices, etc.)
- Optional content section (alerts, loading states, additional status)

### Current Responsive State

The existing implementation uses a mobile-first approach with `sm:` breakpoint (640px) for responsive behavior:

| Element | Mobile (< 640px) | Desktop (>= 640px) |
|---------|------------------|---------------------|
| Action buttons | Stacked full-width (`flex-col`, `w-full`) | Horizontal wrap (`sm:flex-row`, `sm:w-auto`) |
| Status pills | Flex wrap (`flex-wrap gap-2`) | Same |
| Card padding | Fixed `p-6` | Same |
| Card header | Always `flex-row` when actions present | Same |
| Form grids | Single column | 2-3 columns (`sm:grid-cols-2/3`) |

### Problems Identified

1. **Header layout doesn't stack on mobile**: When both title/description AND header actions exist, the header uses `flex-row items-start justify-between` regardless of screen size. On narrow mobile screens, this can cause cramped layouts.

2. **Fixed card padding**: `p-6` (1.5rem) is generous on mobile where screen real estate is precious. Should reduce to `p-4` on mobile.

3. **No intermediate breakpoints**: Only `sm:` (640px) is used. Tablet-sized screens (768px-1024px) don't get optimized layouts.

4. **Status pills can overflow**: While flex-wrap helps, many pills (Zigbee2MQTT has 6+) can create excessive vertical stacking on mobile without clear grouping.

5. **Button order not optimized**: Primary actions (Save) should be more prominent on mobile, but current stacking order doesn't prioritize them.

6. **Toggle row doesn't adapt**: The enable toggle row uses `flex items-center justify-between gap-4`, which works but the gap could be reduced on mobile.

7. **Icon sizes are fixed**: `h-4 w-4` / `h-5 w-5` icons don't scale, though this is less critical.

## Decision

Improve responsive design for IntegrationOverviewCard (and propagate patterns to IntegrationConnectionCard and SectionCard) with the following changes:

### 1. Responsive Card Padding

**Current:**
```tsx
<CardHeader className="p-6">
<CardContent className="p-6 pt-0">
```

**Proposed:**
```tsx
<CardHeader className="p-4 sm:p-6">
<CardContent className="p-4 pt-0 sm:p-6 sm:pt-0">
```

**Rationale:** Reduces padding from 24px to 16px on mobile, reclaiming valuable screen space.

### 2. Header Layout Responsive Stacking

**Current (when actions present):**
```tsx
<CardHeader className="flex-row items-start justify-between space-y-0">
  <div>{/* title + description */}</div>
  <div>{/* actions */}</div>
</CardHeader>
```

**Proposed:**
```tsx
<CardHeader className="flex-col space-y-4 sm:flex-row sm:items-start sm:justify-between sm:space-y-0">
  <div>{/* title + description */}</div>
  <div className="w-full sm:w-auto">{/* actions */}</div>
</CardHeader>
```

**Rationale:** On mobile, title/description and header actions stack vertically for better readability. On desktop, they remain side-by-side.

### 3. Reduced Gap on Mobile for Toggle Row

**Current:**
```tsx
<div className="flex items-center justify-between gap-4">
```

**Proposed:**
```tsx
<div className="flex items-center justify-between gap-2 sm:gap-4">
```

**Rationale:** Tighter spacing on mobile while maintaining comfortable spacing on desktop.

### 4. Status Pills Grouping for Many Pills

For integrations with many status pills (Zigbee2MQTT), introduce optional grouping:

**Current:**
```tsx
<div className="flex flex-wrap items-center gap-2">
  {/* All pills flat */}
</div>
```

**Proposed (for 4+ pills):**
```tsx
<div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
  <div className="flex flex-wrap items-center gap-2">
    {/* Primary status pills (enabled, connected) */}
  </div>
  <div className="flex flex-wrap items-center gap-2">
    {/* Secondary status pills (sync, device count, errors) */}
  </div>
</div>
```

**Rationale:** Groups related pills together, preventing a single long row that wraps unpredictably.

### 5. Action Button Priority Order

**Current:** Buttons render in component order with no mobile-specific prioritization.

**Proposed:** Add `order` utilities or restructure to ensure primary actions (Save) appear first on mobile:

```tsx
<div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:justify-end">
  <Button className="order-first sm:order-last">Save</Button>
  <Button className="order-2 sm:order-1">Reset</Button>
  <Button className="order-3 sm:order-2">Refresh</Button>
</div>
```

**Alternative:** Accept that on mobile, full-width stacked buttons are all equally accessible, and maintain visual consistency by keeping Save last (bottom of stack = easy thumb reach).

### 6. Optional md: Breakpoint for Tablets

Add `md:` (768px) breakpoint for intermediate layouts where appropriate:

```tsx
// Example: 1 column mobile, 2 columns tablet, 3 columns desktop
<div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3">
```

**Scope:** Apply selectively where 3+ column layouts exist (Z-Wave JS timeout fields).

### 7. Content Section Spacing

**Current:**
```tsx
<div className="space-y-3">
```

**Proposed:**
```tsx
<div className="space-y-2 sm:space-y-3">
```

**Rationale:** Tighter vertical rhythm on mobile.

## Implementation Plan

### Phase 1: SectionCard Base Component
Update `frontend/src/components/ui/section-card.tsx`:
- [ ] Add responsive padding (`p-4 sm:p-6`)
- [ ] Add responsive header stacking when actions present
- [ ] Ensure backward compatibility via props if needed

### Phase 2: IntegrationOverviewCard
Update `frontend/src/features/integrations/components/IntegrationOverviewCard.tsx`:
- [ ] Apply responsive gap to toggle row
- [ ] Apply responsive spacing to content section
- [ ] Ensure action buttons follow responsive pattern

### Phase 3: Status Pills Grouping
Update Zigbee2MQTT and any integration with 4+ status pills:
- [ ] `frontend/src/features/zigbee2mqtt/components/Zigbee2mqttStatusPills.tsx`
- [ ] Create optional `StatusPillGroup` component if pattern repeats

### Phase 4: Integration-Specific Cards
Apply responsive improvements to each integration's overview card:
- [ ] `frontend/src/features/frigate/components/FrigateOverviewCard.tsx`
- [ ] `frontend/src/features/homeAssistant/components/HomeAssistantOverviewCard.tsx`
- [ ] `frontend/src/features/mqtt/components/MqttSettingsCard.tsx`
- [ ] `frontend/src/features/zigbee2mqtt/components/Zigbee2mqttSettingsCard.tsx`
- [ ] `frontend/src/features/zwavejs/components/ZwavejsSettingsCard.tsx`

### Phase 5: Testing & Polish
- [ ] Test on mobile viewport (375px - iPhone SE)
- [ ] Test on tablet viewport (768px - iPad)
- [ ] Test on desktop viewport (1024px+)
- [ ] Verify no regressions in existing functionality
- [ ] Screenshot comparison before/after

## Alternatives Considered

### Alternative 1: CSS Container Queries
Use container queries (`@container`) instead of viewport breakpoints for truly component-scoped responsive behavior.

**Pros:**
- Component responds to its container, not viewport
- Better for reusable components in different contexts

**Cons:**
- Requires Tailwind CSS v3.2+ with container query plugin
- Less browser support (Safari 16+, Chrome 105+)
- More complex setup

**Decision:** Defer to future. Current viewport-based approach is sufficient and better supported.

### Alternative 2: Responsive Variant Props
Pass responsive behavior as component props:

```tsx
<IntegrationOverviewCard
  padding={{ base: 4, sm: 6 }}
  headerLayout={{ base: 'stacked', sm: 'row' }}
/>
```

**Pros:**
- Explicit control per instance
- No global CSS changes

**Cons:**
- Verbose API
- Inconsistent if different cards use different props

**Decision:** Rejected. Prefer consistent defaults via Tailwind utilities.

### Alternative 3: Separate Mobile Component
Create `IntegrationOverviewCardMobile` and conditionally render.

**Pros:**
- Complete control over mobile layout
- No CSS complexity

**Cons:**
- Duplicated component logic
- Maintenance burden
- Hydration mismatches in SSR (not applicable here, but bad pattern)

**Decision:** Rejected. Responsive CSS is the standard approach.

## Consequences

**Positive:**
- Better mobile experience for users managing integrations on phones
- Consistent responsive patterns across all integration cards
- Reduced visual clutter on small screens via tighter spacing
- Foundation for future responsive improvements

**Negative:**
- Requires updates to multiple components
- Risk of visual regressions (mitigated by testing plan)
- Slightly more complex CSS class strings

## Tailwind Classes Reference

| Purpose | Classes |
|---------|---------|
| Responsive padding | `p-4 sm:p-6` |
| Responsive header stack | `flex-col space-y-4 sm:flex-row sm:items-start sm:justify-between sm:space-y-0` |
| Responsive gap | `gap-2 sm:gap-4` |
| Responsive spacing | `space-y-2 sm:space-y-3` |
| Full-width on mobile | `w-full sm:w-auto` |
| Button order | `order-first sm:order-last` |

## Related ADRs

- [ADR 0051: Standardize Integration Settings UI Cards](0051-standardize-integration-settings-ui-cards.md) - Defines the card structure this ADR makes responsive
- [ADR 0016: Settings UI as Routed Tabs with Per-Tab Save](0016-settings-routed-tabs-per-tab-save.md) - Overall settings page architecture

## Todos

- [x] Update SectionCard base component with responsive padding and header stacking
- [x] Update IntegrationOverviewCard with responsive gap and spacing
- [x] Update IntegrationConnectionCard similarly
- [x] Add status pill grouping for Zigbee2MQTT
- [x] Update integration-specific cards (Frigate, HA, MQTT, Zigbee2MQTT, Z-Wave)
- [x] Update MqttSettingsForm and ZwavejsSettingsCard form grids
- [ ] Test all integration settings tabs on mobile, tablet, desktop viewports
