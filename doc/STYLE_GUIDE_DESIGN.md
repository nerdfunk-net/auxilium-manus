# Auxilium Manus Design System Guide

**Version:** 1.0
**Last Updated:** 2026-08-14
**Purpose:** Visual design patterns and UI component specifications for Auxilium Manus.

> **COLOR RULE:** App chrome MUST use semantic color tokens (`text-foreground`, `bg-card`, `bg-success`, `text-warning-foreground`, …) — **never** raw Tailwind palette classes (`text-gray-600`, `bg-blue-50`, `border-green-200`, `bg-white`, `bg-slate-50`, …). Tokens live in `frontend/src/app/globals.css` and follow `prefers-color-scheme`. See [Section 4](#4-color-system).
>
> **Workflow steps use `--step-*` tokens**, not `--primary`. Canvas nodes, ConfigPanels, and step dialogs use `.step-header`, `bg-step`, `bg-step-surface`, etc. Do not use step tokens on dashboard pages, settings, or tools. See [WORKFLOW-STEPS-STYLE_GUIDE.md](WORKFLOW-STEPS-STYLE_GUIDE.md).

> **Note:** This guide is visual design only. For architecture (route stubs, feature folders, TanStack Query, RBAC), see `CLAUDE.md`. For workflow step contracts and canvas node rules, see `doc/WORKFLOW-STEPS.md` and `doc/WORKFLOW-STEPS-STYLE_GUIDE.md`.

---

## Table of Contents

1. [Page Structure & Layout](#1-page-structure--layout)
2. [Content Section Patterns](#2-content-section-patterns)
3. [Tabbed Interfaces](#3-tabbed-interfaces)
4. [Color System](#4-color-system)
5. [Spacing & Layout](#5-spacing--layout)
6. [Typography System](#6-typography-system)
7. [Components & Patterns](#7-components--patterns)
8. [Loading States](#8-loading-states)
9. [Empty States](#9-empty-states)
10. [Dialogs & Modals](#10-dialogs--modals)
11. [Common Icons Reference](#11-common-icons-reference)
12. [Common Mistakes to Avoid](#12-common-mistakes-to-avoid)
13. [Quick Reference Templates](#13-quick-reference-templates)
14. [Structural Consistency Checklist](#14-structural-consistency-checklist)

---

## Reference Implementations

- **Document page (canonical):** Templates (`/frontend/src/components/features/templates/templates-page.tsx`)
- **Document page (also canonical):** Inventory (`/frontend/src/components/features/inventory/inventory-page.tsx`)
- **Workspace page:** Workflow builder (`/frontend/src/components/features/workflows/workflow-builder-page.tsx`) and topbar (`.../components/workflow-topbar.tsx`)
- **Settings canvas:** General settings (`/frontend/src/components/features/settings/components/general-settings-canvas.tsx`)
- **Settings list + header:** Credentials (`/frontend/src/components/features/settings/components/credentials-settings-canvas.tsx`)
- **Auth card:** Login (`/frontend/src/components/features/auth/login-page.tsx`)
- **Destructive dialog:** Delete template (`/frontend/src/components/features/templates/components/delete-template-dialog.tsx`)
- **Table + empty state:** Templates table (`/frontend/src/components/features/templates/components/templates-table.tsx`)
- **App shell / sidebar:** `dashboard-shell.tsx`, `app-sidebar.tsx`
- **Workflow step chrome:** [WORKFLOW-STEPS-STYLE_GUIDE.md](WORKFLOW-STEPS-STYLE_GUIDE.md)

---

## 1. Page Structure & Layout

The product is a **sidebar + main area** app. `DashboardShell` is a full-viewport flex row (`h-screen overflow-hidden`). The sidebar is `w-56`. The main column is `flex min-w-0 flex-1 flex-col`. Feature pages fill that column.

There are **two page families**. Pick one and stay consistent. Do not mix a document-page header with a workspace topbar on the same screen.

### 1.1 App Shell

```tsx
// DashboardShell — do not reimplement
<div className="flex h-screen overflow-hidden bg-background text-foreground">
  <AppSidebar />
  <div className="flex min-w-0 flex-1 flex-col">{children}</div>
</div>
```

**Sidebar rules** (`app-sidebar.tsx`):

- Width: `w-56 shrink-0`, surface `border-r bg-card`
- Brand row: `h-16 border-b px-5`, icon `size-9 rounded-xl bg-primary text-primary-foreground`, product name `text-sm font-semibold`, tagline `text-xs text-muted-foreground`
- Nav links: `rounded-lg px-3 py-2 text-sm text-muted-foreground`, hover `hover:bg-accent hover:text-accent-foreground`, active `bg-accent text-accent-foreground` plus `aria-current="page"`
- Nav icons: `size-4`
- Footer: username `text-xs font-medium`, helper `text-xs text-muted-foreground`, Sign out is `Button variant="ghost" size="sm"`

Route files under `app/(dashboard)/*/page.tsx` stay **stubs**. Layout and chrome live in `components/features/{domain}/`.

### 1.2 Family A — Document Pages

Use for list, builder, and editor screens that **scroll**: Inventory, Templates, Template Editor, Tools.

```tsx
export function MyFeaturePage() {
  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-6xl space-y-6">
        {/* Page header */}
        {/* Content sections */}
      </div>
    </div>
  )
}
```

**Key properties:**

- Outer: `h-full overflow-y-auto p-6`
- Inner: `mx-auto max-w-6xl space-y-6`
- Tools / nested utility pages may use `max-w-3xl` or `max-w-4xl` and `p-8` instead of `p-6` — keep the header pattern below

### 1.3 Page Header (Document Pages)

The page header is the first thing users see. Use this exact pattern:

```tsx
<div className="flex items-center justify-between gap-4">
  <div className="flex items-center gap-4">
    <div className="flex size-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
      <FileCode className="h-6 w-6" />
    </div>
    <div>
      <h1 className="text-3xl font-bold text-foreground">Page Title</h1>
      <p className="mt-1 text-muted-foreground">Brief description of the page purpose</p>
    </div>
  </div>

  <div className="flex items-center gap-2">
    <Button variant="outline">Secondary</Button>
    <Button>Primary action</Button>
  </div>
</div>
```

**Rules:**

- Icon box: `size-12 rounded-xl bg-primary/10 text-primary` — not a solid primary fill (that fill is reserved for the sidebar brand mark and the login card)
- Icon size: `h-6 w-6` (or `size-6`)
- Icon-to-title gap: **`gap-4`** — never `gap-3` or `space-x-3`
- Title: `text-3xl font-bold text-foreground`
- Description: `mt-1 text-muted-foreground`
- Actions sit on the right with `gap-2`
- Icon-only helpers use `Button variant="outline" size="icon"` plus a `Tooltip` and `aria-label`

**Tools nested pages** (Database Migration, Add Certificate) add a back control before the icon:

```tsx
<div className="flex items-center gap-3">
  <Button variant="ghost" size="icon" asChild>
    <Link href="/tools" aria-label="Back to tools">
      <ArrowLeft className="size-4" />
    </Link>
  </Button>
  {/* then the same icon + title block */}
</div>
```

Prefer the document-page header sizes (`size-12`, `text-3xl`) for new tools pages. Existing tools pages use a slightly smaller chip (`size-10 rounded-lg bg-muted`) and `text-xl font-semibold` — do not introduce a third size.

### 1.4 Family B — Workspace Pages

Use when the feature is an **editor, canvas, or inspection workspace** that must fill the remaining viewport: Workflows, Workflow Runs, Settings.

```tsx
export function MyWorkspacePage() {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex h-16 items-center justify-between border-b bg-card px-5">
        <div>
          <h1 className="text-sm font-semibold">Workspace title</h1>
          <p className="text-xs text-muted-foreground">One-line context</p>
        </div>
        <div className="flex items-center gap-3">
          {/* actions, tabs, or status */}
        </div>
      </header>
      <main className="flex min-h-0 flex-1">
        {/* canvas, split panes, or settings canvas */}
      </main>
    </div>
  )
}
```

**Key properties:**

- Root: `flex min-h-0 flex-1 flex-col` so the page fills `DashboardShell` without overflowing
- Topbar: **always** `h-16 border-b bg-card px-5` — same height as the sidebar brand row
- Title: `text-sm font-semibold` (not `text-3xl` — this is a workspace, not a document)
- Subtitle: `text-xs text-muted-foreground`
- Dirty indicator (workflows): a `●` in `text-muted-foreground` next to the title
- Primary action (Run, Save Changes) stays a default `Button` on the right

**Settings** uses the same topbar, but the left side is a `TabsList` of section links instead of a title. See [Section 3](#3-tabbed-interfaces).

**Workflow builder** splits `main` into canvas (`flex-1`) + properties panel (`w-[344px] border-l bg-card`). Collapsed rail is `w-11`. Do not invent a third inspector width.

### 1.5 Settings Canvas (under the workspace topbar)

Settings sections scroll inside the workspace `main`:

```tsx
<div className="flex h-full flex-col gap-6 overflow-y-auto bg-muted p-8">
  <div className="mx-auto w-full max-w-2xl space-y-6">
    {/* Card sections */}
  </div>
</div>
```

**Width:**

| Content | Inner max width |
|---------|-----------------|
| Forms (General, Redis, Hatchet, Logging) | `max-w-2xl` |
| Tables / lists (Credentials, Users, Sources) | `max-w-5xl` |

**List canvases** (Credentials) add a compact in-canvas header — not the document-page `text-3xl` header, because Settings already has a topbar:

```tsx
<div className="flex items-start justify-between gap-4">
  <div className="flex items-start gap-3">
    <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
      <KeyRound className="size-5" />
    </div>
    <div>
      <h1 className="text-lg font-semibold">Credential vault</h1>
      <p className="mt-1 text-sm text-muted-foreground">Short description.</p>
    </div>
  </div>
  <Button><Plus className="size-4" />Add SSH login</Button>
</div>
```

### 1.6 Auth Pages (no sidebar)

Login and related auth screens are centered cards on `bg-background`:

```tsx
<main className="flex min-h-screen items-center justify-center bg-background px-4 py-10 text-foreground">
  <section className="w-full max-w-md rounded-2xl border bg-card p-8 shadow-sm">
    <div className="mb-8 flex items-center gap-3">
      <div className="flex size-11 items-center justify-center rounded-xl bg-primary text-primary-foreground">
        <Boxes className="size-6" />
      </div>
      <div>
        <h1 className="text-lg font-semibold">Auxilium Manus</h1>
        <p className="text-sm text-muted-foreground">Sign in to the NetDevOps workflow builder.</p>
      </div>
    </div>
    {/* form */}
  </section>
</main>
```

The login brand mark uses **solid** `bg-primary` (same as the sidebar), not `bg-primary/10`.

---

## 2. Content Section Patterns

### 2.1 Card Section (Primary Pattern)

This is the **primary pattern** for prominent content on document pages and settings canvases. Use shadcn `Card` — do not hand-roll a second card chrome.

```tsx
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

<Card>
  <CardHeader className="pb-3">
    <CardTitle className="text-base">Section Title</CardTitle>
  </CardHeader>
  <CardContent className="space-y-4">
    {/* content */}
  </CardContent>
</Card>
```

**Key properties:**

- Card primitive already applies `rounded-xl border bg-card text-card-foreground shadow-sm`
- Header: default `p-6`; tighten with `pb-3` when the title is a short section label
- Title: `text-base` (CardTitle is `font-semibold tracking-tight` by default)
- Optional right-side action in the header: `CardHeader className="flex flex-row items-center justify-between pb-3"`
- Content: default `p-6 pt-0`; add `space-y-4` for stacked fields

**When to use:**

- Settings form groups (Session, Artifacts, Workflow Runs)
- Feature configuration blocks (template editor panels)
- Status / summary blocks (schema status, source lists)

### 2.2 Bordered Table Panel

Use for tabular lists on document pages and settings canvases:

```tsx
<div className="overflow-hidden rounded-lg border">
  <table className="w-full text-sm">
    <thead className="bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
      <tr>
        <th className="px-4 py-3 text-left font-medium">Name</th>
        <th className="px-4 py-3 text-right font-medium">Actions</th>
      </tr>
    </thead>
    <tbody className="divide-y">
      <tr className="bg-background hover:bg-muted/30">
        <td className="px-4 py-3 font-medium text-foreground">…</td>
        <td className="px-4 py-3">
          <div className="flex justify-end gap-1">{/* icon buttons */}</div>
        </td>
      </tr>
    </tbody>
  </table>
</div>
```

Row actions are `Button variant="ghost" size="icon"` with `aria-label`. Type/category chips use `<Badge variant="secondary">`.

The shadcn `Table` primitive is also acceptable. Do not mix both styles inside one feature.

### 2.3 Banner / Callout

For page-level source, permission, or configuration notices — not for form validation:

```tsx
{/* Neutral / ready */}
<div className="rounded-lg border border-border bg-muted/30 px-4 py-2 text-sm text-muted-foreground">
  Using Nautobot source: <strong className="text-foreground">{sourceId}</strong>
</div>

{/* Needs attention — use Alert warning, not a one-off amber box */}
<Alert variant="warning">
  <AlertCircle />
  <AlertDescription>
    No Nautobot source is configured.
  </AlertDescription>
</Alert>
```

Inline links inside banners: `text-primary underline-offset-4 hover:underline`.

### 2.4 Filter / Toolbar Row

Search and simple filters sit **below** the page header, not inside it:

```tsx
<div className="relative max-w-sm">
  <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
  <Input className="pl-9" placeholder="Search templates…" value={search} onChange={…} />
</div>
```

Switch + label toolbars (credentials “show expired”):

```tsx
<div className="flex items-center gap-3 rounded-lg border bg-card px-4 py-3">
  <Switch id="include-expired" checked={includeExpired} onCheckedChange={setIncludeExpired} />
  <label htmlFor="include-expired" className="text-sm text-muted-foreground">
    Show expired credentials
  </label>
</div>
```

### 2.5 Split Workspace (Runs)

Workflow Runs is a split workspace, not a document page:

- Left list: `w-[380px] shrink-0 border-r bg-muted` (use the token, not `bg-slate-50`)
- Right detail: remaining `flex-1`

Do not reuse this split on settings or inventory.

---

## 3. Tabbed Interfaces

### 3.1 Settings Topbar Tabs (Primary App Pattern)

Settings sections are **routes**, not in-page tab panels. The topbar renders a `TabsList`; each trigger is a `Link`.

```tsx
<header className="flex h-16 items-center justify-between border-b bg-card px-5">
  <Tabs value={activeSection}>
    <TabsList>
      {visibleSections.map((section) => (
        <TabsTrigger asChild key={section.id} value={section.id}>
          <Link href={`/settings/${section.id}`}>{section.label}</Link>
        </TabsTrigger>
      ))}
    </TabsList>
  </Tabs>
</header>
```

**Key properties:**

- Default `TabsList` is a compact pill (`h-9 w-fit rounded-lg bg-muted p-1`) — **not** `grid w-full`
- Only show sections the user can access
- The canvas below the topbar is the section body; do not repeat a giant page title

### 3.2 In-Dialog Tabs

Use underline-style tabs inside large dialogs (node config modal):

```tsx
<TabsList className="h-auto w-full justify-start rounded-none border-b bg-transparent p-0">
  <TabsTrigger
    value="general"
    className="h-9 rounded-none border-b-2 border-transparent px-5 text-xs text-muted-foreground hover:text-foreground data-[state=active]:border-accent-foreground data-[state=active]:bg-background data-[state=active]:font-medium data-[state=active]:text-accent-foreground data-[state=active]:shadow-none"
  >
    General
  </TabsTrigger>
</TabsList>
```

Tab content in that modal: `mt-0 min-h-0 flex-1 overflow-y-auto p-6`.

### 3.3 In-Page Tabs

When a **document page** needs tabs (rare), wrap them in `space-y-6` and keep the default pill `TabsList`. Do not stretch to `grid w-full` unless there are a fixed 2–4 peer steps that should share width equally.

```tsx
<Tabs defaultValue="overview" className="w-full">
  <TabsList>
    <TabsTrigger value="overview">Overview</TabsTrigger>
    <TabsTrigger value="history">History</TabsTrigger>
  </TabsList>
  <TabsContent value="overview" className="space-y-6">
    {/* Card sections */}
  </TabsContent>
</Tabs>
```

---

## 4. Color System

### 4.0 The Semantic Token Rule (MANDATORY)

**App chrome never references concrete palette colors.** All structural colors come from CSS variables in `frontend/src/app/globals.css` (`:root` plus `@media (prefers-color-scheme: dark)`) and are exposed as Tailwind utilities via `@theme inline`.

```tsx
// ❌ WRONG — hardcoded palette, breaks dark mode
<p className="text-gray-600">...</p>
<div className="bg-green-50 border-green-200 text-green-800">Saved!</div>
<div className="bg-slate-50 p-8">...</div>

// ✅ CORRECT — semantic tokens
<p className="text-muted-foreground">...</p>
<Alert variant="success">Saved!</Alert>
<div className="bg-muted p-8">...</div>
```

**Exceptions:**

1. **Canvas category tiles** (artifact-type rainbow in `step-visuals.ts`) — keep distinct hues so step kinds stay visually different. Nautobot/result tiles use `--step-*`.
2. **Data-driven colors** from an API (e.g. a Nautobot status color) may use inline `style`.
3. **Syntax / terminal dumps** may use a dark `bg-slate-950 text-slate-100` well inside a dialog. Do not use that well as page chrome.

There is **no** `.dark` class toggle and **no** `dark:` color overrides in new code. `prefers-color-scheme` updates the CSS variables; components just use tokens.

### 4.1 Token Reference

Defined today in `globals.css`:

| Token utility | Light (approx.) | Use for |
|---------------|-----------------|---------|
| `bg-background` / `text-foreground` | slate-50 / slate-900 | Page background / primary text |
| `bg-card` / `text-card-foreground` | white / slate-900 | Cards, sidebar, topbars, tables |
| `bg-popover` / `text-popover-foreground` | white / slate-900 | Dropdowns, popovers |
| `bg-primary` / `text-primary-foreground` | slate-900 / slate-50 | Primary buttons, brand mark |
| `text-primary` | slate-900 | Links, active emphasis |
| `bg-secondary` / `text-secondary-foreground` | indigo-50 / indigo-900 | Secondary badges and quiet fills |
| `bg-muted` / `text-muted-foreground` | slate-100 / slate-500 | Subtle surfaces / secondary text |
| `bg-accent` / `text-accent-foreground` | sky-100 / sky-800 | Nav hover/active, accent highlights |
| `bg-destructive` / `text-destructive` / `text-destructive-foreground` | red-600 | Destructive actions, errors, invalid fields |
| `border-border` (or `border`) | slate-200 | Standard borders |
| `border-input` | slate-200 | Input borders |
| `ring-ring` | sky-400 | Focus rings (`focus-visible:ring-ring/50`) |
| `bg-success` / `text-success-foreground` / `border-success-border` | green well | Success banners, badges, icons |
| `bg-warning` / `text-warning-foreground` / `border-warning-border` | amber well | Warnings, unconfigured hints |
| `bg-info` / `text-info-foreground` / `border-info-border` | sky well | Informational banners |
| `bg-error` / `text-error-foreground` / `border-error-border` | red well | Error banners and toasts |
| `bg-step` / `text-step-foreground` / `hover:bg-step-hover` | teal-500 | Step primary actions |
| `bg-step-surface` / `text-step-surface-foreground` | teal-50 | Step wells, selected rows |
| `text-step-muted-foreground` / `border-step-border` | teal-700 / teal-200 | Step helper text and borders |
| `.step-header` | teal gradient | Step ConfigPanel / dialog headers |

`--radius` is `0.75rem` (12px). Cards use `rounded-xl`; controls use `rounded-md`.

**Brand character:** near-black primary, sky/cyan ring and accent, indigo secondary. Workflow steps use the **step** (teal) family only.

Shorthand utilities `.status-success`, `.status-warning`, `.status-error`, `.status-info` set background + text + border-color in one class (add `border` for the width). Prefer `Alert` variants over using these directly.

### 4.2 Status Colors

`--destructive` is for **actions** (Delete buttons, invalid fields). Status **surfaces** use success / warning / info / error.

| Intent | Do this |
|--------|---------|
| Success (block) | `<Alert variant="success">` or `bg-success text-success-foreground border-success-border` |
| Warning (block) | `<Alert variant="warning">` |
| Error (block) | `<Alert variant="destructive">` (uses error surface tokens) |
| Info (block) | `<Alert variant="info">` |
| Destructive action | `Button variant="destructive"` |
| Neutral chip | `<Badge variant="outline">` or `secondary` |
| Error chip | `<Badge variant="destructive">` |
| Inline error text | `text-sm text-destructive` |
| Unconfigured hint (ConfigPanel) | `text-[11px] text-warning-foreground` |
| Required / invalid | `text-destructive` / `border-destructive` |

Run-status icons (`RunStatusIcon`) and step result badges (`StepStatusBadge`) already use these tokens. Reuse those components.

### 4.3 Step (teal) tokens

Use only in `workflow-steps/`, canvas nodes, and step dialogs:

```tsx
<DialogHeader className="border-b step-header px-4 py-3">
  <DialogTitle className="text-base text-step-header-foreground">…</DialogTitle>
</DialogHeader>

<Button className="bg-step text-step-foreground hover:bg-step-hover">Save</Button>

<div className="rounded-lg bg-step-surface px-3 py-2 text-xs text-step-surface-foreground">
  Hint
</div>
```

Do **not** use `from-teal-600`, `bg-teal-50`, or `bg-teal-500` — `.step-header` / `bg-step` / `bg-step-surface` follow `prefers-color-scheme`.

### 4.4 Shared Color Components

There is no `StatusAlert` / `IconChip` package. Use:

| Need | Use |
|------|-----|
| Status block | `<Alert variant="default\|destructive\|warning\|success\|info">` |
| Page header icon | `size-12 rounded-xl bg-primary/10 text-primary` (Section 1.3) |
| Sidebar / login brand | `rounded-xl bg-primary text-primary-foreground` |
| Toast | `useToast()` — default or `variant: "destructive"` |
| Workflow run status | `RunStatusIcon`, `StepStatusBadge` |

### 4.5 Migration Mapping (Old → New)

When touching a file that still uses raw palette classes, migrate them:

| Old (hardcoded) | New (token / primitive) |
|-----------------|-------------------------|
| `text-gray-900`, `text-slate-900`, `text-gray-800` | `text-foreground` |
| `text-gray-500/600/700`, `text-slate-500/600`, `text-gray-400` | `text-muted-foreground` |
| `bg-white` | `bg-card` (surfaces) or `bg-background` (page) |
| `bg-slate-50`, `bg-gray-50` | `bg-muted` or `bg-background` |
| `border-gray-200/300`, `border-slate-200` | `border-border` (or `border`) |
| `text-blue-600` (links) | `text-primary` |
| `bg-blue-50`, `border-blue-200`, `text-blue-800` | `bg-info` / `text-info-foreground` / `border-info-border` |
| `bg-blue-500 text-white` on Button | remove — default `Button` is already primary |
| `text-red-500` (required `*`) | `text-destructive` |
| `bg-red-50`, `text-red-700`, `border-red-200` | `bg-error`, `text-error-foreground`, `border-error-border` |
| `bg-amber-50 text-amber-900 border-amber-200` | `bg-warning text-warning-foreground border-warning-border` |
| `text-amber-600` (unconfigured) | `text-warning-foreground` |
| `bg-green-50 text-green-800` | `bg-success text-success-foreground` |
| `from-teal-600 to-teal-500 text-white` | `step-header` |
| `bg-teal-500 hover:bg-teal-600 text-white` | `bg-step text-step-foreground hover:bg-step-hover` |
| `bg-teal-50 text-teal-900` | `bg-step-surface text-step-surface-foreground` |
| `text-teal-500` | `text-step` |
| `dark:*` color overrides paired with the above | delete — tokens follow `prefers-color-scheme` |

---

## 5. Spacing & Layout

### 5.1 Standard Spacing Scale

| Class | Pixels | Use Case |
|-------|--------|----------|
| `space-y-2` | 8px | Field internals (`FormItem` default) |
| `space-y-4` | 16px | Fields inside a card, stacked blocks |
| `space-y-6` | 24px | Page sections, card groups, tab content |
| `gap-1` | 4px | Icon-only action clusters in tables |
| `gap-2` | 8px | Button groups, inline controls |
| `gap-3` | 12px | Compact in-canvas headers, login brand row |
| `gap-4` | 16px | Document page icon-to-title; header action wrap |
| `p-6` | 24px | Document page padding; dialog body; card header |
| `p-8` | 32px | Settings canvas padding; tools page padding |
| `px-5` | 20px | Workspace topbar and sidebar brand row |
| `px-4 py-3` | 16×12 | Table cells, banners, switch toolbars |

### 5.2 Padding Guidelines

**Pages:**

- Document: `p-6` on the scroll container
- Settings canvas / tools: `p-8`
- Workspace topbar: `px-5`, height `h-16` (no extra vertical padding)

**Surfaces:**

- Card: default CardHeader/CardContent padding
- Dialog: default `p-6` on `DialogContent`
- Large editor dialog (node config): `p-0` on the shell, `p-6` on the scrollable tab body
- Icon boxes: padding via `size-12` + flex center, not `p-2` on a free-sized box

### 5.3 Border Radius

| Element | Class | Token |
|---------|-------|-------|
| Cards | `rounded-xl` | `--radius` (0.75rem) |
| Login card | `rounded-2xl` | — |
| Page icon chip | `rounded-xl` | — |
| Sidebar brand mark | `rounded-xl` | — |
| Dialogs | `rounded-lg` | default primitive |
| Buttons, inputs, badges | `rounded-md` | — |
| Nav links | `rounded-lg` | — |
| Tables (wrapper) | `rounded-lg` | — |

Do not mix `rounded-lg` and `rounded-xl` icon chips on document pages.

### 5.4 Widths (do not invent new ones)

| Surface | Width |
|---------|-------|
| Sidebar | `w-56` (224px) |
| Document inner | `max-w-6xl` |
| Settings form canvas | `max-w-2xl` |
| Settings list canvas | `max-w-5xl` |
| Tools inner | `max-w-3xl` or `max-w-4xl` |
| Auth card | `max-w-md` |
| Workflow inspector | `w-[344px]` (collapsed `w-11`) |
| Runs list column | `w-[380px]` |
| Dialog default | `max-w-lg` (primitive) |

---

## 6. Typography System

Fonts: **Geist Sans** (`--font-geist-sans`) for UI, **Geist Mono** (`--font-geist-mono`) for paths, template names, IDs, and command-like values. Set on `<html>` in `app/layout.tsx`.

### 6.1 Headings

```tsx
{/* Document page title */}
<h1 className="text-3xl font-bold text-foreground">Templates</h1>
<p className="mt-1 text-muted-foreground">Manage Jinja2 templates…</p>

{/* Workspace topbar title */}
<h1 className="text-sm font-semibold">My workflow</h1>
<p className="text-xs text-muted-foreground">Select devices, run commands, and store artifacts.</p>

{/* Settings in-canvas title */}
<h1 className="text-lg font-semibold">Credential vault</h1>
<p className="mt-1 text-sm text-muted-foreground">Configure SSH login credentials…</p>

{/* Card section title */}
<CardTitle className="text-base">Session</CardTitle>
```

### 6.2 Content Text

```tsx
<Label>Field Label</Label>                 {/* text-sm font-medium */}
<p className="text-sm">Body copy</p>
<p className="text-sm text-muted-foreground">Secondary / empty / loading copy</p>
<p className="text-xs text-muted-foreground">Helper, captions, topbar subtitle</p>
<span className="font-mono text-xs">/var/lib/manus/export</span>
```

Form descriptions use `FormDescription` (muted, small). Validation uses `FormMessage` (destructive).

### 6.3 Special Text Styles

```tsx
{/* Empty table / list */}
<p className="rounded-lg border border-dashed px-4 py-10 text-center text-sm text-muted-foreground">
  No templates yet. Create your first template to get started.
</p>

{/* Monospace names in dialog copy */}
<DialogDescription>
  This permanently removes <span className="font-mono">{name}</span>.
</DialogDescription>

{/* Table header */}
<thead className="bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
```

Do not add `tracking-tight` on document `<h1>` titles. CardTitle may keep its default tracking.

---

## 7. Components & Patterns

Use **shadcn** primitives from `frontend/src/components/ui/` for all UI chrome. Do not add another component library.

### 7.1 Buttons

```tsx
<div className="flex items-center gap-2">
  <Button>Primary Action</Button>
  <Button variant="outline">Secondary</Button>
  <Button variant="ghost">Tertiary</Button>
  <Button variant="destructive">Delete</Button>
</div>

<Button disabled={isPending}>
  {isPending && <Loader2 className="size-4 animate-spin" />}
  Save Changes
</Button>
```

**Variants:** `default` (primary), `destructive`, `outline`, `secondary`, `ghost`, `link`.
**Sizes:** `default` (`h-9`), `sm` (`h-8`), `lg` (`h-10`), `icon` (`size-9`).

Icons inside buttons are `size-4`. The primitive already sets `gap-2` and `[&_svg]:size-4` — do not add `mr-2` on the icon unless you are not using `Button`.

Do not override `Button` with `bg-teal-600` / `bg-blue-600` on app pages. Teal buttons belong only in workflow-step ConfigPanels per the steps style guide.

### 7.2 Alerts

```tsx
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { AlertCircle, AlertTriangle, CheckCircle2 } from 'lucide-react'

<Alert>
  <AlertCircle />
  <AlertDescription>Neutral information.</AlertDescription>
</Alert>

<Alert variant="warning">
  <AlertTriangle />
  <AlertTitle>Schema differences detected</AlertTitle>
  <AlertDescription>Review the diffs before applying.</AlertDescription>
</Alert>

<Alert variant="success">
  <CheckCircle2 />
  <AlertTitle>Schema is in sync</AlertTitle>
  <AlertDescription>The database matches the current models.</AlertDescription>
</Alert>

<Alert variant="destructive">
  <AlertCircle />
  <AlertDescription>{errorMessage}</AlertDescription>
</Alert>
```

Login / inline field errors may use a compact well instead of `Alert`:

```tsx
<p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">
  {authError}
</p>
```

### 7.3 Form Layouts

Use **react-hook-form + zod + shadcn Form** for settings and multi-field dialogs.

```tsx
<Form {...form}>
  <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6">
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Session</CardTitle>
      </CardHeader>
      <CardContent>
        <FormField
          control={form.control}
          name="session_timeout_minutes"
          render={({ field }) => (
            <FormItem>
              <FormLabel>Default session timeout (minutes)</FormLabel>
              <FormControl>
                <Input type="number" className="w-40" {...field} />
              </FormControl>
              <FormDescription>How long a session can be idle before sign-out.</FormDescription>
              <FormMessage />
            </FormItem>
          )}
        />
      </CardContent>
    </Card>

    <div className="flex items-center justify-end">
      <Button type="submit" disabled={isPending}>
        {isPending && <Loader2 className="size-4 animate-spin" />}
        Save Changes
      </Button>
    </div>
  </form>
</Form>
```

**Switch row** (settings):

```tsx
<FormItem className="flex items-center justify-between rounded-lg border p-3">
  <div>
    <FormLabel>Switch to Runs when a run starts</FormLabel>
    <FormDescription>Navigate to the Runs page automatically…</FormDescription>
  </div>
  <FormControl>
    <Switch checked={field.value} onCheckedChange={field.onChange} />
  </FormControl>
</FormItem>
```

Simple dialogs may use `Label` + `Input` with `space-y-2` groups inside `space-y-4` — still no native `<input>` styling forks. Login is the exception that inlines input classes; new auth fields should use the `Input` primitive.

### 7.4 Toasts

```tsx
import { useToast } from '@/hooks/use-toast'

const { toast } = useToast()

toast({ title: 'Saved', description: 'General settings updated.' })
toast({ title: 'Error', description: error.message, variant: 'destructive' })
```

Toasts render bottom-right (`Toaster`). Do not call `alert()`. Mutations should toast on success/error rather than painting a one-off banner, unless the page has a persistent status panel (schema sync).

### 7.5 Badges

```tsx
<Badge>Default</Badge>
<Badge variant="secondary">jinja2</Badge>
<Badge variant="outline">{workflowStatus}</Badge>
<Badge variant="destructive">Error</Badge>
```

Map workspace status to variants: Error → `destructive`, Running → `default`, otherwise `outline`.

### 7.6 Dropdowns & Selects

File menus and overflow actions use `DropdownMenu`. Constrained choices use `Select`. Compact topbar selects: `SelectTrigger className="h-8 w-[110px]"`.

---

## 8. Loading States

Use `Loader2` from Lucide with `animate-spin`. Do not invent CSS border spinners.

### 8.1 Route / Page Loading

Dashboard segment fallback (`app/(dashboard)/loading.tsx`):

```tsx
<div className="flex h-full items-center justify-center">
  <Loader2 className="size-8 animate-spin text-muted-foreground" />
</div>
```

Document pages that load a named record should keep the header and replace the body:

```tsx
<div className="flex items-center justify-center py-24 text-muted-foreground">
  <Loader2 className="mr-2 size-5 animate-spin" />
  Loading template…
</div>
```

Workspace pages keep the `h-16` topbar visible and spin in `main`.

### 8.2 Inline / Section Loading

```tsx
<p className="text-sm text-muted-foreground">Loading credentials…</p>
```

Lists that already have a chrome (Runs column, inspector):

```tsx
<div className="flex items-center justify-center py-10">
  <Loader2 className="size-6 animate-spin text-muted-foreground" />
</div>
```

### 8.3 Button Loading

```tsx
<Button disabled={isPending}>
  {isPending && <Loader2 className="size-4 animate-spin" />}
  {isPending ? 'Saving…' : 'Save Changes'}
</Button>
```

Destructive confirms: disable the confirm button and change the label (`Deleting…`).

### 8.4 Query Errors

```tsx
<p className="text-sm text-destructive">{error.message}</p>
```

Do not dump raw 5xx `error_id` payloads into a toast title; show the user-facing `message`.

---

## 9. Empty States

### 9.1 Empty Table / List (Document & Settings)

```tsx
<p className="rounded-lg border border-dashed px-4 py-10 text-center text-sm text-muted-foreground">
  No templates yet. Create your first template to get started.
</p>
```

### 9.2 Empty Workspace (centered)

Keep the topbar. Center a short message with an optional icon and a single outline action:

```tsx
<div className="flex flex-1 flex-col items-center justify-center gap-4 p-6 text-center text-muted-foreground">
  <Play className="size-10 opacity-30" aria-hidden />
  <div className="space-y-1">
    <p className="text-sm font-medium text-foreground">No saved workflow</p>
    <p className="text-sm">Save a workflow first, then click Run to see executions here.</p>
  </div>
  <Button asChild variant="outline">
    <Link href="/workflows">Open workflow editor</Link>
  </Button>
</div>
```

### 9.3 Missing Configuration

Use `Alert variant="warning"` plus an outline button to Settings (see Inventory `NautobotSourceBanner`). Do not block the whole page behind a spinner once you know the source is missing.

### 9.4 No Permission

```tsx
<div className="flex h-full items-center justify-center p-10">
  <Card className="max-w-md">
    <CardHeader>
      <CardTitle>No permission</CardTitle>
    </CardHeader>
    <CardContent className="text-sm text-muted-foreground">
      You do not have permission to view this settings section.
    </CardContent>
  </Card>
</div>
```

---

## 10. Dialogs & Modals

Always shadcn `Dialog`. Never `window.confirm()` / `window.alert()`.

### 10.1 Standard Dialog

```tsx
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

interface MyDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function MyDialog({ open, onOpenChange }: MyDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Dialog title</DialogTitle>
          <DialogDescription>What this dialog does.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-2">{/* fields */}</div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="button" onClick={onConfirm}>
            Confirm
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
```

Controlled dialogs that only close on explicit cancel often use:

```tsx
<Dialog open={open} onOpenChange={(next) => !next && onClose()}>
```

### 10.2 Confirmation / Destructive Dialog

Canonical: `delete-template-dialog.tsx` / `delete-credential-dialog.tsx`.

```tsx
<DialogContent className="sm:max-w-sm">
  <DialogHeader>
    <DialogTitle>Delete template?</DialogTitle>
    <DialogDescription>
      This permanently removes <span className="font-mono">{templateName ?? 'this template'}</span>.
    </DialogDescription>
  </DialogHeader>
  <DialogFooter>
    <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
    <Button type="button" variant="destructive" disabled={isDeleting} onClick={onConfirm}>
      {isDeleting ? 'Deleting…' : 'Delete'}
    </Button>
  </DialogFooter>
</DialogContent>
```

Footer order: Cancel (outline) left/first, confirm right. Destructive confirms use `variant="destructive"`.

### 10.3 Large Editor Dialog

Node configuration is a **75vh / max-w-2xl** dialog with `p-0`, internal tabs, and a scrollable body. Reuse that shell only for similarly dense step/editors — not for simple forms.

```tsx
<DialogContent className="flex h-[75vh] max-w-2xl flex-col gap-0 overflow-hidden p-0">
```

### 10.4 Dialog Size Classes

| Size | Class | Use Case |
|------|-------|----------|
| Small | `sm:max-w-sm` | Delete / confirm |
| Medium | `sm:max-w-md` | Short forms |
| Default | primitive `max-w-lg` | Standard dialogs |
| Large | `max-w-2xl` | Multi-field forms, node config |
| Extra large | `max-w-4xl` | Wide data (use sparingly) |

Overlay is `bg-black/50`. Do not remove the overlay except for documented canvas-adjacent cases (`showOverlay`).

---

## 11. Common Icons Reference

Use **Lucide React** only.

| Icon | Use Case |
|------|----------|
| `Boxes` | Product mark (sidebar, login) |
| `Workflow` | Workflows nav |
| `Network` | Inventory nav / network sources |
| `FileCode` | Templates |
| `PlayCircle` / `Play` | Runs, execute |
| `Settings` | Settings nav |
| `Wrench` | Developer tools |
| `KeyRound` | Credentials, certificates |
| `Database` | Database migration |
| `Plus` | Create / add |
| `Trash2` | Delete |
| `Pencil` | Edit |
| `Eye` | View / preview |
| `Upload` / `Download` | Import / export |
| `Search` | Search inputs |
| `HelpCircle` | Help / docs |
| `ArrowLeft` | Back to parent page |
| `Save` / `SaveAll` | Save / Save As |
| `FolderOpen` / `FolderCog` / `FilePlus` | Open / manage / new file |
| `Loader2` | Loading (`animate-spin`) |
| `CheckCircle2` | Success |
| `XCircle` / `AlertCircle` | Error / attention |
| `AlertTriangle` | Warning |
| `RefreshCw` | Reload / refetch |
| `RotateCcw` | Reset to default |
| `LogOut` / `LogIn` | Auth |
| `Copy` | Duplicate / clipboard |
| `GitBranch` | Git sources |
| `Shield` / `ShieldCheck` | Auth / ISE |
| `FlaskConical` | pyATS |
| `CalendarClock` | Schedules |
| `PanelRightOpen` | Inspector |

**Sizes:**

| Context | Class |
|---------|-------|
| Document page chip | `h-6 w-6` |
| Sidebar brand | `size-5` |
| Settings in-canvas chip | `size-5` |
| Buttons, nav, dialogs | `size-4` |
| Table row actions | `size-4` |
| Empty-state illustration | `size-10 opacity-30` |
| Route loading | `size-8` |

```tsx
import { Plus, Loader2 } from 'lucide-react'

<Button>
  <Plus className="size-4" />
  Create New Template
</Button>

<Loader2 className="size-4 animate-spin" />
```

---

## 12. Common Mistakes to Avoid

### ❌ Design Don'ts

- Don't use raw Tailwind palette classes in app chrome (`text-gray-600`, `bg-blue-50`, `bg-slate-50`, `bg-white`, `border-green-200`)
- Don't add `dark:` color overrides — tokens follow `prefers-color-scheme`
- Don't copy workflow-step **teal** gradients, `bg-teal-500` buttons, or `teal-50` info wells onto Inventory, Settings, Templates, or Tools
- Don't introduce a custom canvas node renderer or per-step page chrome — see the workflow-steps style guide
- Don't put a document-page `text-3xl` header on a workspace that already has an `h-16` topbar
- Don't change topbar height (`h-16`) or sidebar width (`w-56`)
- Don't use `gap-3` / `space-x-3` between the document-page icon chip and title — it is **`gap-4`**
- Don't use `mt-2` on document subtitles — this app uses **`mt-1`**
- Don't override `Button` with `bg-blue-600` / `bg-teal-600` on dashboard pages
- Don't use `alert()` or `confirm()`
- Don't build primitives that already exist in `components/ui/`
- Don't put logic in `app/(dashboard)/*/page.tsx` — stubs only
- Don't skip loading, empty, and permission states
- Don't mix `rounded-lg` and `rounded-xl` icon chips on the same page family

### ✅ Design Do's

- Use semantic tokens for all app chrome
- Pick **document** or **workspace** family and follow that header exactly
- Use shadcn `Card`, `Button`, `Dialog`, `Alert`, `Tabs`, `Table` / bordered table, `Form`
- Keep Lucide icons at the sizes in Section 11
- Toast mutation results with `useToast()`
- Preserve the topbar (workspace) or page header (document) while content loads
- Test light and dark (`prefers-color-scheme`)
- Add `aria-label` on icon-only buttons and `aria-current="page"` on active nav
- For new workflow steps, follow [WORKFLOW-STEPS-STYLE_GUIDE.md](WORKFLOW-STEPS-STYLE_GUIDE.md) instead of this page-header pattern

---

## 13. Quick Reference Templates

### 13.1 Document Page

```tsx
'use client'

import { Plus } from 'lucide-react'

import { Button } from '@/components/ui/button'

export function MyFeaturePage() {
  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-6xl space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="flex size-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Plus className="h-6 w-6" />
            </div>
            <div>
              <h1 className="text-3xl font-bold text-foreground">My Feature</h1>
              <p className="mt-1 text-muted-foreground">Brief description</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline">Secondary</Button>
            <Button>
              <Plus className="size-4" />
              Primary
            </Button>
          </div>
        </div>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Section</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">{/* content */}</CardContent>
        </Card>
      </div>
    </div>
  )
}
```

### 13.2 Workspace Page

```tsx
'use client'

import { Button } from '@/components/ui/button'

export function MyWorkspacePage() {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex h-16 items-center justify-between border-b bg-card px-5">
        <div>
          <h1 className="text-sm font-semibold">Workspace title</h1>
          <p className="text-xs text-muted-foreground">One-line context</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline">Secondary</Button>
          <Button>Run</Button>
        </div>
      </header>
      <main className="min-h-0 flex-1">{/* canvas or split panes */}</main>
    </div>
  )
}
```

### 13.3 Settings Form Canvas

```tsx
export function MySettingsCanvas() {
  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto bg-muted p-8">
      <div className="mx-auto w-full max-w-2xl space-y-6">
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSave)} className="space-y-6">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Section</CardTitle>
              </CardHeader>
              <CardContent>{/* FormFields */}</CardContent>
            </Card>
            <div className="flex items-center justify-end">
              <Button type="submit">Save Changes</Button>
            </div>
          </form>
        </Form>
      </div>
    </div>
  )
}
```

---

## Design Checklist

Before considering a UI implementation complete:

- [ ] **Family chosen**: Document page **or** workspace page — not a mix
- [ ] **Root spacing**: Document uses `space-y-6`; workspace uses `h-16` topbar + `min-h-0 flex-1`
- [ ] **Page header**: Document uses `size-12` icon chip, `gap-4`, `text-3xl`, `mt-1` subtitle
- [ ] **Workspace topbar**: `h-16 border-b bg-card px-5`, `text-sm` title, `text-xs` subtitle
- [ ] **Sections**: shadcn `Card` with `CardTitle className="text-base"`
- [ ] **Colors**: semantic tokens only in app chrome — no `gray-` / `slate-` / `blue-` / `green-` palette classes
- [ ] **Dark mode**: verified with `prefers-color-scheme: dark`
- [ ] **Typography**: follows the scale in Section 6
- [ ] **Spacing**: `gap-2` for buttons, `space-y-6` between sections, `p-6` / `p-8` as specified
- [ ] **Icons**: Lucide, correct size, `aria-label` on icon-only buttons
- [ ] **Loading**: `Loader2` + message; header/topbar remains visible
- [ ] **Empty / permission**: dashed empty or centered workspace empty; Card for no-permission
- [ ] **Alerts**: `Alert` variants, not one-off colored divs
- [ ] **Dialogs**: shadcn Dialog, outline Cancel, destructive for deletes
- [ ] **Toasts**: `useToast()` on mutations
- [ ] **Responsive**: document pages remain readable; workspace pages scroll inside panes, not the whole app shell
- [ ] **Workflow steps**: if this is a step ConfigPanel, this checklist is superseded by [WORKFLOW-STEPS-STYLE_GUIDE.md](WORKFLOW-STEPS-STYLE_GUIDE.md)

---

## Resources

**Component library:** [shadcn/ui](https://ui.shadcn.com) — primitives in `frontend/src/components/ui/`

**Icons:** [Lucide](https://lucide.dev)

**Tokens:** `frontend/src/app/globals.css`

**Related guides:**

- [WORKFLOW-STEPS-STYLE_GUIDE.md](WORKFLOW-STEPS-STYLE_GUIDE.md) — canvas nodes, ConfigPanel step tokens, fan-out block
- [WORKFLOW-STEPS.md](WORKFLOW-STEPS.md) — step contracts and execution
- `CLAUDE.md` — architecture, query hooks, route stubs, permissions

**Canonical files:**

- Document page: `frontend/src/components/features/templates/templates-page.tsx`
- Workspace topbar: `frontend/src/components/features/workflows/components/workflow-topbar.tsx`
- Settings form: `frontend/src/components/features/settings/components/general-settings-canvas.tsx`
- Sidebar: `frontend/src/components/layout/app-sidebar.tsx`

---

## 14. Structural Consistency Checklist

When building a new page or aligning an existing one, these are the usual sources of visual drift.

### 14.1 Page-Level Structure

Every **document page** MUST follow:

```tsx
export function MyPage() {
  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-6xl space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <div className="flex size-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Icon className="h-6 w-6" />
            </div>
            <div>
              <h1 className="text-3xl font-bold text-foreground">Page Title</h1>
              <p className="mt-1 text-muted-foreground">Description</p>
            </div>
          </div>
        </div>
        {/* sections */}
      </div>
    </div>
  )
}
```

Every **workspace page** MUST follow:

```tsx
export function MyWorkspacePage() {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex h-16 items-center justify-between border-b bg-card px-5">
        {/* title block or TabsList */}
      </header>
      <main className="min-h-0 flex-1">{/* … */}</main>
    </div>
  )
}
```

| Mistake | Correct |
|---------|---------|
| Root `<div>` with no height/overflow | Document: `h-full overflow-y-auto p-6`; workspace: `flex min-h-0 flex-1 flex-col` |
| `text-3xl` title under a Settings/Workflows topbar | Workspace titles are `text-sm font-semibold`; settings in-canvas titles are `text-lg` |
| `gap-3` or `space-x-3` between document icon and title | `gap-4` |
| Subtitle `mt-2` on document pages | `mt-1` |
| Title `text-gray-900` / subtitle `text-gray-600` | `text-foreground` / `text-muted-foreground` |
| Settings canvas `bg-slate-50` | `bg-muted` |
| Solid `bg-primary` icon chip on a document page | `bg-primary/10 text-primary` (solid fill is sidebar + login only) |
| Spinner replacing the whole workspace including topbar | Keep `h-16` topbar; spin in `main` |
| New inspector width (`w-80`, `w-72`, …) | Workflow inspector is `w-[344px]` |

### 14.2 Section Consistency

- Cards: `rounded-xl border bg-card shadow-sm` via the `Card` primitive — do not add `shadow-lg` or strip the border
- Card titles in settings: **`text-base`**, header **`pb-3`**
- Table wrappers: `overflow-hidden rounded-lg border`
- Do not mix gradient “panel headers” from other apps — this product has none in app chrome
- Teal gradient headers belong only in workflow-step ConfigPanels

### 14.3 Loading State Pattern

Loading **MUST** preserve the document header or workspace topbar so the page does not jump:

```tsx
if (isLoading) {
  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-6xl space-y-6">
        {/* same header as the loaded state */}
        <div className="flex items-center justify-center py-20">
          <Loader2 className="size-8 animate-spin text-muted-foreground" />
        </div>
      </div>
    </div>
  )
}
```

### 14.4 Reference Implementation

When in doubt:

- **Document structure:** Templates page
- **Workspace structure:** Workflow topbar + builder page
- **Settings forms:** General settings canvas
- **Destructive dialogs:** Delete template dialog
- **Empty lists:** Templates table dashed empty state
- **Step UI:** `get-nautobot-devices` ConfigPanel + [WORKFLOW-STEPS-STYLE_GUIDE.md](WORKFLOW-STEPS-STYLE_GUIDE.md)

---

**Need implementation help?**

This guide is visual design. For feature implementation:

- File organization and route stubs
- TanStack Query hooks and `queryKeys`
- API calls via `/api/proxy/*`
- RBAC (`require_permission`, `hasPermission`)
- Workflow definition vs canvas vs run

See `CLAUDE.md`.
