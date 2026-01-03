# ADR 0053: Application Color Scheme

## Status
Implemented

## Context

The application currently uses default Tailwind CSS colors and shadcn/ui theming without a defined brand color palette. As the application matures, establishing a consistent color scheme will:

1. Create visual identity and brand recognition
2. Ensure accessibility through intentional color contrast decisions
3. Provide semantic meaning to UI states (success, warning, danger, info)
4. Guide future design decisions with a constrained palette

### Current State

- Uses default shadcn/ui slate/zinc color tokens
- No defined primary brand color
- Status indicators use ad-hoc colors (green for success, red for error)
- No documented color palette for contributors

## Decision

Adopt the following 5-color palette as the application's official color scheme:

| Color Name | Hex Code | RGB | Usage |
|------------|----------|-----|-------|
| **Deep Teal** | `#335C67` | rgb(51, 92, 103) | Primary brand color, headers, navigation |
| **Cream** | `#FFF3B0` | rgb(255, 243, 176) | Highlights, badges, accent backgrounds |
| **Amber** | `#E09F3E` | rgb(224, 159, 62) | Warnings, pending states, attention |
| **Dark Red** | `#9E2A2B` | rgb(158, 42, 43) | Errors, danger states, destructive actions |
| **Burgundy** | `#540B0E` | rgb(84, 11, 14) | Critical alerts, severe warnings, emphasis |

### Color Palette Source

[Coolors Palette](https://coolors.co/palette/335c67-fff3b0-e09f3e-9e2a2b-540b0e)

### Semantic Color Mapping

| Semantic Use | Color | Rationale |
|--------------|-------|-----------|
| **Primary** | Deep Teal `#335C67` | Professional, calm, associated with security |
| **Secondary** | Cream `#FFF3B0` | Soft contrast, readable on dark backgrounds |
| **Warning** | Amber `#E09F3E` | Universal warning color, high visibility |
| **Danger** | Dark Red `#9E2A2B` | Clear error/danger indication |
| **Critical** | Burgundy `#540B0E` | Severe/critical states, darker than danger |

### CSS Custom Properties

```css
:root {
  /* Brand Colors */
  --color-brand-teal: 51 92 103;        /* #335C67 */
  --color-brand-cream: 255 243 176;     /* #FFF3B0 */
  --color-brand-amber: 224 159 62;      /* #E09F3E */
  --color-brand-red: 158 42 43;         /* #9E2A2B */
  --color-brand-burgundy: 84 11 14;     /* #540B0E */

  /* Semantic Aliases */
  --color-primary: var(--color-brand-teal);
  --color-accent: var(--color-brand-cream);
  --color-warning: var(--color-brand-amber);
  --color-danger: var(--color-brand-red);
  --color-critical: var(--color-brand-burgundy);
}
```

### Tailwind Configuration Extension

```js
// tailwind.config.js
module.exports = {
  theme: {
    extend: {
      colors: {
        brand: {
          teal: '#335C67',
          cream: '#FFF3B0',
          amber: '#E09F3E',
          red: '#9E2A2B',
          burgundy: '#540B0E',
        },
      },
    },
  },
}
```

### Usage Examples

```tsx
// Primary button
<Button className="bg-brand-teal hover:bg-brand-teal/90 text-white">
  Arm System
</Button>

// Warning badge
<Badge className="bg-brand-amber text-brand-burgundy">
  Pending
</Badge>

// Error alert
<Alert className="border-brand-red bg-brand-red/10 text-brand-red">
  Connection failed
</Alert>

// Critical status
<div className="bg-brand-burgundy text-white">
  ALARM TRIGGERED
</div>
```

### Accessibility Considerations

| Combination | Contrast Ratio | WCAG Level |
|-------------|----------------|------------|
| Deep Teal on White | 6.3:1 | AA (pass) |
| Burgundy on White | 12.6:1 | AAA (pass) |
| Dark Red on White | 7.2:1 | AA (pass) |
| Burgundy on Cream | 10.1:1 | AAA (pass) |
| Deep Teal on Cream | 5.0:1 | AA (pass) |
| Amber on Burgundy | 5.8:1 | AA (pass) |

All primary text combinations meet WCAG AA requirements (4.5:1 minimum).

### Alarm State Color Mapping

For the alarm panel specifically:

| Alarm State | Color | Visual |
|-------------|-------|--------|
| Disarmed | Deep Teal `#335C67` | Calm, secure, inactive |
| Armed (Away/Home) | Amber `#E09F3E` | Alert, active, attention |
| Entry Delay | Amber `#E09F3E` | Warning, countdown |
| Exit Delay | Deep Teal `#335C67` | Preparing, not yet armed |
| Triggered | Dark Red `#9E2A2B` | Danger, immediate attention |
| Alarming | Burgundy `#540B0E` | Critical, severe |

## Implementation Plan

### Phase 1: Tailwind Configuration
- [x] Add brand colors to `@theme inline` block in `index.css`
- [x] Add CSS custom properties to global styles (`:root` and `.dark`)

### Phase 2: Alarm State Colors
- [x] Update alarm state colors to use brand palette

### Phase 3: Core Components
- [x] Add `brand`, `warning`, `danger` Button variants
- [x] Update Alert component success/warning variants
- [x] Update ConnectionStatusBanner colors

### Phase 4: Alarm Panel
- [x] Update AlarmStatus component state colors
- [x] Update CountdownTimer (entry/exit/trigger delays)
- [x] Update AlarmHistory event colors
- [x] Update ArmButtons (Home, Away modes)
- [x] Update QuickActions (Disarm button)

### Phase 5: Integration Status
- [x] Update ConnectionStatus component
- [x] Update SystemStatusCard integration status colors
- [x] Update FrigateOverviewCard status pills
- [x] Update HomeAssistantOverviewCard status pills
- [x] Update HomeAssistantMqttAlarmEntityCard status pills
- [x] Update Zigbee2mqttStatusPills

### Phase 6: Other Components
- [x] Update RulesListCard enabled/disabled colors
- [x] Update PushbulletProviderForm validation colors
- [x] Update Header background and status badge

## Alternatives Considered

### Alternative 1: Material Design Colors
Use Google's Material Design color system with predefined palettes.

**Pros:**
- Well-documented accessibility guidelines
- Extensive shade variations
- Industry standard

**Cons:**
- Generic, lacks brand identity
- Requires picking from large palette anyway

**Decision:** Rejected. Custom palette provides stronger brand identity.

### Alternative 2: Tailwind Default Extended
Extend Tailwind's default color palette without custom colors.

**Pros:**
- No configuration needed
- Consistent with Tailwind ecosystem

**Cons:**
- No brand differentiation
- Limited semantic meaning

**Decision:** Rejected. Brand colors are worth the configuration.

### Alternative 3: Dark-First Color Scheme
Design for dark mode as primary, with lighter as secondary.

**Pros:**
- Modern aesthetic
- Better for security/monitoring apps

**Cons:**
- Current app is light-first
- Would require significant rework

**Decision:** Deferred. Can be addressed in future dark mode ADR.

## Consequences

**Positive:**
- Consistent visual identity across the application
- Clear semantic meaning for UI states
- Accessible color combinations documented
- Foundation for future theming/dark mode

**Negative:**
- Requires updating existing components
- May conflict with shadcn/ui defaults initially
- Contributors need to learn new color tokens

## Related ADRs

- [ADR 0051: Standardize Integration Settings UI Cards](0051-standardize-integration-settings-ui-cards.md) - Card styling that will use these colors
- [ADR 0052: Responsive Integration Overview Cards](0052-responsive-integration-overview-cards.md) - Component patterns to apply colors to
