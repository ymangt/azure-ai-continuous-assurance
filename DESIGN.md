# DESIGN.md — Assurance Console

Executable visual brief for `apps/console`. Read this before changing UI.

## Visual theme & atmosphere

Calm Azure enterprise workbench: navy sidebar, light content canvas, crisp tables, restrained accent. Feels like Microsoft/Fluent product UI for assurance operators — trustworthy, dense enough for data, never flashy.

## Color palette & roles

| Token | Value | Role |
|---|---|---|
| `--navy-950` | `#07172b` | Sidebar deep base |
| `--navy-900` | `#0c203b` | Sidebar mid |
| `--navy-800` | `#12345a` | Sidebar accents |
| `--azure-700` | `#075985` | Links / strong brand text |
| `--azure-600` | `#0078d4` | Primary actions / selection |
| `--azure-100` | `#dff1ff` | Soft brand wash |
| `--ink` | `#172338` | Body text |
| `--muted` | `#5d6b7d` | Secondary text |
| `--line` | `#dce3ec` | Borders |
| `--line-strong` | `#c7d1de` | Emphasized borders |
| `--surface` | `#ffffff` | Cards / panels |
| `--surface-subtle` | `#f8fafc` | Nested surfaces |
| `--success` | `#0e7a5f` | Pass / healthy |
| `--warning` | `#9a5d00` | Caution / stale |
| `--danger` | `#b4233d` | Fail / material risk |
| `--focus-ring` | `#4aa8dc` | Keyboard focus outline |
| `--overlay-scrim` | `rgba(7, 23, 43, 0.42)` | Mobile detail-panel dimmer |
| `--candidate-wash` | `#f5f9fc` | AI-suggestion / candidate surface |
| `--candidate-border` | `#b9d3e5` | Candidate surface border |
| Page background | `#f4f7fb` | App canvas |

Do not introduce purple gradients, neon accents, or black `#000` cyber themes.

## Typography

- Family: `"Segoe UI Variable", "Segoe UI", system-ui, sans-serif`
- Mono for digests/hashes: `"SFMono-Regular", Consolas, monospace`
- Product scale: restrained (no display/marketing fonts in labels, buttons, or tables)
- Eyebrows: small, uppercase, letter-spaced, `--azure-700`

## Layout principles

- Fixed navy sidebar (~248px) + fluid main content
- Section cards with light shadow (`--shadow`)
- Master-detail for controls/evidence/findings (`DetailPanel`)
- Overview order: metric grid → two-column grids → criteria-to-retest trace → priority findings table
- Prefer existing `SectionCard`, `MetricCard`, `StatusBadge`, `OverviewPreviewDialog` patterns

## Components

- **Fluent UI React v9** is the component system (`Button`, `Dialog`, `Badge`, `Field`, etc.)
- Status via `StatusBadge` semantic colors
- Confirm/mutate via `ActionDialog`
- Overview deep-links via `OverviewPreviewDialog` (stay on overview vs open full record)
- Do not add shadcn/ui or Tailwind utility stacks unless explicitly requested

## Depth & elevation

- Cards: soft shadow `0 8px 24px rgba(20, 42, 74, 0.07)`
- Detail panel: stronger sticky elevation when open
- Dialogs: Fluent surface + short enter motion (`overview-preview-in`, ~220ms)

## Motion

- Short, purposeful: 150–250ms
- Allowed: dialog enter/exit, screen fade-in, hover lift on metric cards, progress bars
- Forbidden: long orchestrated page loads, bouncing badges, decorative parallax
- Always honor `prefers-reduced-motion`

## Do’s

- Extend existing CSS variables before hardcoding new hex values
- Keep assurance language precise (PASS ≠ EFFECTIVE)
- Use preview dialogs for overview navigation that would otherwise yank context
- Match spacing/radius already used by `.section-card`, `.metric-card`, `.trace-step`
- Left-edge accents on readiness/assessor notes and active nav are intentional Azure workbench chrome, not generic AI side-tabs

## Don’ts

- Don’t invent a second visual language beside Fluent + current tokens
- Don’t turn the console into a marketing landing page
- Don’t add emoji ornamentation or neon glow
- Don’t auto-navigate away from Overview without an explicit primary CTA in a preview
- Don’t put secrets, live tenant IDs, or private evidence into UI copy

## Agent prompt guide

1. Read `PRODUCT.md` + this file before UI edits.
2. Prefer editing `apps/console/src/styles.css` tokens and existing components.
3. For visual polish passes, use Impeccable commands (`/polish`, `/audit`) against this brief.
4. `frontend-design` / Taste Skill apply only within this product register — clarity over novelty.
