# Consurg Scope Picker Design System

## 1. Atmosphere & Identity

A quiet, local-first developer workbench: precise, trustworthy, and dense enough to scan a repository without feeling crowded. The signature is a warm paper-and-ink file tree crossed by one restrained teal action color; context selection should feel like preparing a careful surgical tray, not configuring a cloud dashboard.

## 2. Color

### Palette

| Role | Token | Value | Usage |
|---|---|---:|---|
| Surface/canvas | `--surface-canvas` | `#f4f2ec` | Page background |
| Surface/primary | `--surface-primary` | `#fffdfa` | Main workspace |
| Surface/secondary | `--surface-secondary` | `#f8f6f0` | Toolbars and grouped controls |
| Surface/selected | `--surface-selected` | `#e5f2ed` | Selected tree rows |
| Text/primary | `--text-primary` | `#17211e` | Headlines and body |
| Text/secondary | `--text-secondary` | `#5f6c67` | Hints and metadata |
| Text/tertiary | `--text-tertiary` | `#87918d` | Disabled and placeholder text |
| Border/default | `--border-default` | `#d8d6ce` | Panels and controls |
| Border/subtle | `--border-subtle` | `#e9e6de` | Tree rows and quiet dividers |
| Accent/primary | `--accent-primary` | `#176b57` | Primary actions and focus |
| Accent/hover | `--accent-hover` | `#0f5847` | Primary-action hover |
| Accent/soft | `--accent-soft` | `#d7ebe4` | Accent-tinted backgrounds |
| Tier/read-write | `--tier-rw` | `#176b57` | RW selection |
| Tier/read-only | `--tier-ro` | `#315d88` | RO selection |
| Tier/signature | `--tier-sig` | `#87651c` | Signature selection |
| Tier/list-only | `--accent-soft` + `--text-primary` | `#d7ebe4` / `#17211e` | LIST selection |
| Status/error | `--status-error` | `#a33c3c` | Errors and blocked policy |
| Status/warning | `--status-warning` | `#87651c` | Omitted-file warnings |
| Status/success | `--status-success` | `#176b57` | Confirmation |

### Rules

- Accent is functional only: selection, focus, and primary actions.
- Tier colors may appear only in tier controls and their legend.
- Surfaces and borders create hierarchy; decorative gradients and glows are not used.
- No color outside this palette may appear in the picker.

## 3. Typography

### Scale

| Level | Size | Weight | Line Height | Tracking | Usage |
|---|---:|---:|---:|---:|---|
| H1 | 24px | 680 | 1.2 | -0.02em | Product title |
| H2 | 16px | 650 | 1.4 | -0.01em | Workspace regions |
| Body | 15px | 400 | 1.5 | 0 | Default copy and controls |
| Body/sm | 13px | 450 | 1.45 | 0 | Secondary information |
| Caption | 12px | 600 | 1.35 | 0.04em | Metadata and compact labels |

### Font Stack

- Primary: `"Aptos", "Segoe UI Variable", "Segoe UI", system-ui, sans-serif`
- Mono: `"Cascadia Code", "SFMono-Regular", Consolas, monospace`

### Rules

- File paths, token counts, and generated context use the mono stack.
- Body text never renders below 12px.
- Hierarchy comes from weight, spacing, and contrast rather than oversized text.

## 4. Spacing & Layout

### Base Unit

All spacing derives from a base of **4px**.

| Token | Value | Usage |
|---|---:|---|
| `--space-1` | 4px | Icon-to-label and compact gaps |
| `--space-2` | 8px | Inline controls and tree rows |
| `--space-3` | 12px | Inputs and toolbars |
| `--space-4` | 16px | Panel padding |
| `--space-5` | 20px | Header spacing |
| `--space-6` | 24px | Workspace gutters |
| `--space-8` | 32px | Page edge spacing |

### Grid

- Maximum content width: 1440px.
- Desktop workspace: two columns, file tree minmax(360px, 0.95fr) and context preview minmax(420px, 1.05fr).
- Mobile and tablet below 900px: one column with no horizontal page overflow.
- Page margin: 16px mobile, 24px desktop.

### Rules

- All spacing is a multiple of 4px.
- File depth uses a 20px indentation step because it combines a 16px control width and 4px gap.
- The context preview remains usable at every supported breakpoint.

## 5. Components

### Action Button

- **Structure**: semantic `button` with optional inline SVG and label.
- **Variants**: primary, secondary, quiet.
- **Spacing**: 8px vertical, 12px horizontal, 8px icon gap.
- **States**: default, hover, active, focus-visible, disabled, busy.
- **Accessibility**: visible focus ring, disabled semantics, action-specific labels.
- **Motion**: 140ms color/opacity/transform feedback; active uses a 1px translate.

### Tree Row

- **Structure**: disclosure control for folders, checkbox, file/folder SVG, path label, token count, tier group.
- **Variants**: folder, file, selected, denied, search match.
- **Spacing**: 8px block padding and 8px gaps; 20px per nesting level.
- **States**: expanded/collapsed, unchecked/mixed/checked, hover, focus-within, denied.
- **Accessibility**: nested native lists with keyboard-native disclosure buttons and checkboxes; folder checkbox labels name their descendant action. Tree rerenders restore focus to the exact control that initiated the change.
- **Motion**: only opacity and transform for load-in; disclosure honors reduced motion.

### Tier Segmented Control

- **Structure**: labeled group of five buttons: RW, RO, SIG, LIST, OFF.
- **Variants**: one selected tier and denied policy state.
- **Spacing**: 4px internal gap, compact caption scale.
- **States**: hover, active, focus-visible, selected, disabled.
- **Accessibility**: group label identifies the file; buttons expose `aria-pressed`.
- **Motion**: 140ms color and transform feedback.

### Status Notice

- **Structure**: live text region below actions.
- **Variants**: neutral, success, warning, error.
- **Spacing**: 8px top margin.
- **States**: empty or visible.
- **Accessibility**: `role="status"`, polite live announcements; errors remain readable without color.
- **Motion**: opacity-only appearance.

### Form Control

- **Structure**: visible or screen-reader label plus input, select, or textarea.
- **Variants**: search, scope name, task, output format, prompt preview.
- **Spacing**: 8px vertical and 12px horizontal.
- **States**: default, hover, focus-visible, disabled, readonly.
- **Accessibility**: every control is labeled; placeholder text is supplementary only.
- **Motion**: 140ms border and background feedback.

## 6. Motion & Interaction

### Timing

| Type | Duration | Easing | Usage |
|---|---:|---|---|
| Micro | 140ms | ease-out | Button, checkbox, focus feedback |
| Standard | 240ms | cubic-bezier(0.16, 1, 0.3, 1) | Workspace entry and disclosure affordance |

### Rules

- Animate only `transform`, `opacity`, and color where no layout work is triggered.
- Every interactive element has hover, active, focus-visible, and disabled behavior as applicable.
- `prefers-reduced-motion: reduce` removes non-essential movement.
- Composition is debounced and stale requests are cancelled rather than visually racing.
- Applying a new folder payload aborts and invalidates pending composition before clearing the preview, so content from the prior folder cannot appear in the new preview.
- Saving a wildcard-expanding scope requires explicit confirmation before the expanded scope is written.

## 7. Depth & Surface

### Strategy

**Borders-only.** The picker uses tonal surfaces plus one-pixel borders; it does not use box shadows.

| Type | Value | Usage |
|---|---|---|
| Default | `1px solid var(--border-default)` | Workspace, inputs, buttons |
| Subtle | `1px solid var(--border-subtle)` | Tree rows and internal dividers |

Surfaces must not use `box-shadow`; focus rings use `outline` so they remain accessibility affordances rather than visual depth.
