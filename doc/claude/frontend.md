# Frontend

## UI/UX Standards

### MUST Use Shadcn UI
```bash
npx shadcn@latest add {component}  # button, dialog, table, form, etc.
```

**DO:**
- ✅ Use Shadcn components for ALL UI primitives
- ✅ Use Tailwind utility classes (`bg-background`, `text-foreground`, NOT `bg-blue-500`)
- ✅ Use Lucide React icons (`import { Check, X } from "lucide-react"`)
- ✅ Forms with react-hook-form + zod validation
- ✅ Toast notifications (`useToast()` hook)
- ✅ Mobile-first responsive design
- ✅ Proper ARIA labels and accessibility

**DON'T:**
- ❌ Build UI from scratch when Shadcn exists
- ❌ Use arbitrary colors or inline styles
- ❌ Mix other UI libraries
- ❌ Use `alert()` or `confirm()` (use Dialog/AlertDialog)

### Common UI Patterns
```typescript
// Button variants
<Button variant="default|secondary|destructive|outline|ghost|link">

// Dialog
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"

// Form
import { Form, FormField, FormItem, FormLabel, FormControl } from "@/components/ui/form"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"

// Toast
import { useToast } from "@/hooks/use-toast"
const { toast } = useToast()
toast({ title: "Success", description: "Done!" })
```

## Nautobot / Source Data Fetching

Nautobot and other source data is fetched through backend REST endpoints under
`/api/proxy/sources/nautobot/*` — there is no client-side GraphQL client, and none
should be added (see API proxy pattern in main CLAUDE.md). Add new source data needs
as backend endpoints, then call them from a TanStack Query hook under
`/frontend/src/hooks/queries/`.

❌ DON'T create inline GraphQL queries, a client-side GraphQL client, or dedicated
backend endpoints for each query

## TanStack Query (Data Fetching & Caching)

**MANDATORY for all data fetching** — replaces manual `useState + useEffect` for server state.

### Core Principles
- **Declarative data fetching**: Query hooks replace manual useState/useEffect
- **Automatic caching**: Data persists across navigation, reduces API calls
- **Background refetch**: Fresh data on window focus/reconnect
- **Centralized keys**: Use query key factory for type-safe invalidation
- **Smart polling**: Auto-start/stop based on data state

### Query Hook Pattern

```typescript
// 1. Add query keys to /frontend/src/lib/query-keys.ts
export const queryKeys = {
  myFeature: {
    all: ['myFeature'] as const,
    list: (filters?: { status?: string }) =>
      filters
        ? ([...queryKeys.myFeature.all, 'list', filters] as const)
        : ([...queryKeys.myFeature.all, 'list'] as const),
    detail: (id: string) => [...queryKeys.myFeature.all, 'detail', id] as const,
  },
}

// 2. Create hook in /frontend/src/hooks/queries/use-my-feature-query.ts
import { useQuery } from '@tanstack/react-query'
import { useApi } from '@/hooks/use-api'
import { queryKeys } from '@/lib/query-keys'

const DEFAULT_OPTIONS = {}

export function useMyFeatureQuery(options = DEFAULT_OPTIONS) {
  const { apiCall } = useApi()
  const { filters, enabled = true } = options

  return useQuery({
    queryKey: queryKeys.myFeature.list(filters),
    queryFn: async () => apiCall('my-feature', { method: 'GET' }),
    enabled,
    staleTime: 30 * 1000,
  })
}
```

### Mutation Hook Pattern

```typescript
export function useMyFeatureMutations() {
  const { apiCall } = useApi()
  const queryClient = useQueryClient()
  const { toast } = useToast()

  const createItem = useMutation({
    mutationFn: async (data: CreateItemInput) =>
      apiCall('my-feature', { method: 'POST', body: JSON.stringify(data) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.myFeature.list() })
      toast({ title: 'Success', description: 'Item created!' })
    },
    onError: (error: Error) =>
      toast({ title: 'Error', description: error.message, variant: 'destructive' }),
  })

  return { createItem }
}
```

### Polling Pattern (Jobs/Tasks)

```typescript
export function useJobQuery(taskId: string) {
  return useQuery({
    queryKey: queryKeys.jobs.detail(taskId),
    queryFn: () => fetchJob(taskId),
    enabled: !!taskId,
    refetchInterval: (query) => {
      const data = query.state.data
      if (!data) return 2000
      if (['SUCCESS', 'FAILURE', 'REVOKED'].includes(data.status)) return false
      return 2000
    },
    staleTime: 0,
  })
}
```

### Optimistic Updates

```typescript
const syncRepository = useMutation({
  mutationFn: async (id) => apiCall(`git/${id}/sync`, { method: 'POST' }),
  onMutate: async (id) => {
    await queryClient.cancelQueries({ queryKey: queryKeys.git.repositories() })
    const previous = queryClient.getQueryData(queryKeys.git.repositories())
    queryClient.setQueryData(queryKeys.git.repositories(), (old) => ({
      ...old,
      repositories: old.repositories.map((r) =>
        r.id === id ? { ...r, sync_status: 'syncing' } : r
      ),
    }))
    return { previous }
  },
  onError: (err, id, context) => {
    queryClient.setQueryData(queryKeys.git.repositories(), context?.previous)
  },
  onSettled: () => queryClient.invalidateQueries({ queryKey: queryKeys.git.repositories() }),
})
```

### TanStack Query DO / DON'T

**DO:**
- ✅ Use centralized query key factory (`queryKeys`)
- ✅ Create dedicated hooks for each resource
- ✅ Use `DEFAULT_OPTIONS = {}` constant for default params
- ✅ Invalidate affected queries after mutations
- ✅ Match `staleTime` to volatility (5min static, 30s semi-static, 0 for polling)
- ✅ Use `useMemo` for derived state (not `useState`)

**DON'T:**
- ❌ Use manual `useState + useEffect` for server data
- ❌ Use inline query keys (always use `queryKeys` factory)
- ❌ Store query data in `useState` (use `useMemo` for derived state)
- ❌ Forget to invalidate cache after mutations
- ❌ Use inline object literals as default params (`= {}` creates new object every render)

## React Best Practices (CRITICAL — Prevents Infinite Loops)

### 1. Default Parameters — Use Constants
```typescript
// ❌ WRONG - Creates new array every render
function Component({ items = [] }) { }

// ✅ CORRECT
const EMPTY_ARRAY: string[] = []
function Component({ items = EMPTY_ARRAY }) { }
```

### 2. Custom Hooks — Memoize Returns
```typescript
// ❌ WRONG - New object every render
export function useMyHook() {
  const [state, setState] = useState()
  return { state, setState }
}

// ✅ CORRECT
export function useMyHook() {
  const [state, setState] = useState()
  return useMemo(() => ({ state, setState }), [state])
}
```

### 3. useEffect Dependencies — MUST Be Stable
```typescript
// ❌ WRONG - Runs every render!
const config = { key: 'value' }
useEffect(() => doSomething(config), [config])

// ✅ CORRECT
const DEFAULT_CONFIG = { key: 'value' }  // Outside component
useEffect(() => doSomething(DEFAULT_CONFIG), [])

// OR for dynamic values
const config = useMemo(() => ({ key: someValue }), [someValue])
useEffect(() => doSomething(config), [config])
```

### 4. Callbacks to Hooks — ALWAYS useCallback
```typescript
// ❌ WRONG - New function every render
const { data } = useMyHook({ onChange: () => doSomething() })

// ✅ CORRECT
const handleChange = useCallback(() => doSomething(), [])
const { data } = useMyHook({ onChange: handleChange })
```

### 5. Exhaustive Dependencies — Include All
```typescript
// ❌ WRONG - Missing dependencies
useEffect(() => {
  if (isReady) loadData(userId)
}, [])

// ✅ CORRECT
useEffect(() => {
  if (isReady) loadData(userId)
}, [isReady, userId, loadData])
```

## Frontend INCORRECT Practices

- ❌ Placing components at `/components/` root without feature grouping
- ❌ Direct backend API calls from frontend
- ❌ Inline GraphQL queries in components
- ❌ Building UI from scratch instead of using Shadcn
- ❌ Using inline array/object literals in default params
- ❌ Custom hooks without memoized returns
- ❌ Missing or incomplete useEffect dependencies
- ❌ Manual `useState + useEffect` for server data (use TanStack Query)
- ❌ Inline query keys (always use `queryKeys` factory)
- ❌ Storing query data in `useState` (use `useMemo` for derived state)
- ❌ Forgetting to invalidate cache after mutations
