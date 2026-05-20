# Workflow Step Style Guide

Reference implementation: `get-nautobot-devices/`

---

## Color palette

All steps use the **teal** accent family from Tailwind. Never use `sky-`, `blue-`, or arbitrary hex colors.

| Role | Tailwind class | Usage |
|---|---|---|
| Card header background | `bg-gradient-to-r from-teal-600 to-teal-500` | Step card top bar |
| Header text / icons | `text-white` | On gradient header |
| Header badge / pill | `bg-white/20 text-white` | Counts, labels in header |
| Primary action button | `bg-teal-500 hover:bg-teal-600 text-white` | Round `+` / submit button |
| Selected row / item | `bg-teal-50 text-teal-900` | Active state in lists/sidebars |
| Accent icons | `text-teal-500` | Folder, status icons |
| Info banner | `bg-teal-50 text-teal-900` | Contextual hint strips |
| Info badge border | `border-teal-200` | Pill borders inside info banners |
| Focus ring | `focus:ring-teal-400/40` | Inputs, selects |
| Checkbox accent | `accent-teal-500` | Native checkboxes |

---

## Card anatomy

```
┌─────────────────────────────────────┐
│  Header (gradient from-teal-600 …)  │  py-2.5 px-4, text-white, font-semibold
├─────────────────────────────────────┤
│  Body (bg-slate-50)                 │  overflow-y-auto, space-y-4, p-4
│   • warning banner (amber-50)       │  when source not configured
│   • main content                    │
│   • preview results                 │
├─────────────────────────────────────┤
│  Footer (bg-white, border-t)        │  flex-wrap gap-2, px-4 py-3
└─────────────────────────────────────┘
```

- Outer wrapper: `rounded-xl border border-slate-200 bg-card shadow-sm`
- Dialog variant: `rounded-none border-0 shadow-none` (strip rounding/border when inside a Dialog)

---

## Config panel (node side-panel)

The `ConfigPanel` component renders inside the React Flow node property panel — it is narrow (~220 px) and must stay compact.

- Use `space-y-1.5` for label → hint → button stacking
- Labels: `font-mono text-xs font-medium` for parameter names
- Badges: `<Badge variant="secondary">` for type hints (`nautobot`, `filter tree`, …)
- Status hint (configured): `text-[11px] text-muted-foreground truncate`
- Status hint (unconfigured): `text-[11px] text-amber-600`
- Action button: `<Button variant="outline" size="sm" className="h-7 w-full text-xs">`

---

## Dialogs

- Use `<Dialog>` from Shadcn.
- Wide dialogs (filter builder): `max-w-4xl h-[85vh] flex flex-col gap-0 overflow-hidden p-0`
- Compact dialogs (source config): `sm:max-w-md`
- Footer: `<DialogFooter className="shrink-0 border-t bg-white px-4 py-3">`
- Always include `<DialogHeader className="sr-only">` with `DialogTitle` + `DialogDescription` for accessibility.

---

## Toolbar buttons (footer row)

```tsx
// Primary action
<Button variant="secondary" size="sm" className="h-8 gap-1.5 rounded-lg text-xs">
  <Icon className="h-3.5 w-3.5" aria-hidden />
  Label
</Button>

// Secondary / outlined
<Button variant="outline" size="sm" className="h-8 gap-1.5 rounded-lg border-slate-300 text-xs">
  <Icon className="h-3.5 w-3.5" aria-hidden />
  Label
</Button>

// Accent outlined (e.g. Manage Inventory)
<Button variant="outline" size="sm"
  className="h-8 gap-1.5 rounded-lg border-violet-400 text-xs text-violet-700 hover:bg-violet-50 hover:text-violet-800">
  <Icon className="h-3.5 w-3.5 text-violet-600" aria-hidden />
  Label
</Button>
```

---

## Sidebar (group tree)

- Outer: `bg-white border-r border-slate-200`
- Section header: `text-[10px] font-semibold uppercase tracking-wide text-muted-foreground`, `border-b border-slate-200 px-3 py-2`
- Row selected: `bg-teal-50 text-teal-900`
- Row hover: `hover:bg-muted`
- Folder icon: `text-teal-500`
- Count badge: `text-[10px] text-muted-foreground`

---

## Inputs

All text/number inputs follow the same pattern:

```tsx
<input
  className="h-9 w-full rounded-lg border border-input bg-white px-2 text-xs
             focus:outline-none focus:ring-2 focus:ring-teal-400/40
             disabled:cursor-not-allowed disabled:bg-muted/50"
/>
```

---

## Condition / info banners

```tsx
// Teal info (adding-to context)
<div className="rounded-lg bg-teal-50 px-3 py-2 text-xs text-teal-900">
  Adding conditions to:{" "}
  <span className="inline-flex rounded-full border border-teal-200 bg-white px-2 py-0.5 font-medium text-teal-900 shadow-sm">
    Root
  </span>
</div>

// Amber warning (missing config)
<p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
  Configure a Nautobot source…
</p>
```

---

## Checklist for new steps

- [ ] Header uses `bg-gradient-to-r from-teal-600 to-teal-500`
- [ ] No `sky-` / `blue-` colors anywhere in the step
- [ ] ConfigPanel is narrow, uses `h-7 w-full` outline buttons
- [ ] All inputs use `focus:ring-teal-400/40`
- [ ] Dialog footers use `border-t bg-white px-4 py-3`
- [ ] `<DialogHeader className="sr-only">` present with title + description
- [ ] `aria-hidden` on all decorative icons
- [ ] Shadcn primitives used for all UI (no raw `<select>`, `<dialog>`, etc.)
