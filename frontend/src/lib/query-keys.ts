export const queryKeys = {
  workflowSteps: {
    all: ["workflow-steps"] as const,
    list: () => [...queryKeys.workflowSteps.all, "list"] as const,
  },
  workflows: {
    all: ["workflows"] as const,
    list: () => [...queryKeys.workflows.all, "list"] as const,
    detail: (id: number) => [...queryKeys.workflows.all, "detail", id] as const,
  },
  pluginConfig: {
    all: ["plugin-config"] as const,
    detail: (pluginId: string) => [...queryKeys.pluginConfig.all, pluginId] as const,
  },
  settings: {
    all: ["settings"] as const,
    list: (keyPrefix?: string) =>
      keyPrefix
        ? ([...queryKeys.settings.all, "list", keyPrefix] as const)
        : ([...queryKeys.settings.all, "list"] as const),
    detail: (key: string) => [...queryKeys.settings.all, "detail", key] as const,
  },
  hatchet: {
    all: ["hatchet"] as const,
    settings: () => [...queryKeys.hatchet.all, "settings"] as const,
    status: () => [...queryKeys.hatchet.all, "status"] as const,
  },
  redis: {
    all: ["redis"] as const,
    settings: () => [...queryKeys.redis.all, "settings"] as const,
    stats: () => [...queryKeys.redis.all, "stats"] as const,
  },
  logging: {
    all: ["logging"] as const,
    settings: () => [...queryKeys.logging.all, "settings"] as const,
  },
  workflowRuns: {
    all: ["workflow-runs"] as const,
    list: (workflowId: number, filtersKey?: string) =>
      filtersKey
        ? ([...queryKeys.workflowRuns.all, "list", workflowId, filtersKey] as const)
        : ([...queryKeys.workflowRuns.all, "list", workflowId] as const),
    detail: (runId: number) =>
      [...queryKeys.workflowRuns.all, "detail", runId] as const,
    artifact: (runId: number, artifactId: string) =>
      [...queryKeys.workflowRuns.all, "artifact", runId, artifactId] as const,
  },
  sourcesNautobot: {
    all: ["sources-nautobot"] as const,
    fieldOptions: () => [...queryKeys.sourcesNautobot.all, "field-options"] as const,
    fieldValues: (nautobotUrl: string, field: string) =>
      [...queryKeys.sourcesNautobot.all, "field-values", nautobotUrl, field] as const,
    preview: (nautobotUrl: string, operationsKey: string) =>
      [...queryKeys.sourcesNautobot.all, "preview", nautobotUrl, operationsKey] as const,
    inventories: () => [...queryKeys.sourcesNautobot.all, "inventories"] as const,
    groups: () => [...queryKeys.sourcesNautobot.all, "groups"] as const,
    inventoryDetail: (id: number) =>
      [...queryKeys.sourcesNautobot.all, "inventory", id] as const,
    customFields: (nautobotUrl: string) =>
      [...queryKeys.sourcesNautobot.all, "custom-fields", nautobotUrl] as const,
  },
  sourcesIse: {
    all: ["sources-ise"] as const,
    list: () => [...queryKeys.sourcesIse.all, "list"] as const,
  },
  credentials: {
    all: ["credentials"] as const,
    list: (includeExpired?: boolean) =>
      includeExpired
        ? ([...queryKeys.credentials.all, "list", "with-expired"] as const)
        : ([...queryKeys.credentials.all, "list"] as const),
  },
  gitRepositories: {
    all: ["git-repositories"] as const,
    list: (activeOnly?: boolean) =>
      activeOnly
        ? ([...queryKeys.gitRepositories.all, "list", "active"] as const)
        : ([...queryKeys.gitRepositories.all, "list"] as const),
  },
  templates: {
    all: ["templates"] as const,
    list: (filtersKey?: string) =>
      filtersKey
        ? ([...queryKeys.templates.all, "list", filtersKey] as const)
        : ([...queryKeys.templates.all, "list"] as const),
    detail: (id: number) => [...queryKeys.templates.all, "detail", id] as const,
    categories: () => [...queryKeys.templates.all, "categories"] as const,
  },
  rbac: {
    all: ["rbac"] as const,
    permissions: () => [...queryKeys.rbac.all, "permissions"] as const,
    roles: () => [...queryKeys.rbac.all, "roles"] as const,
    role: (id: number) => [...queryKeys.rbac.all, "role", id] as const,
    userRoles: (userId: number) => [...queryKeys.rbac.all, "user-roles", userId] as const,
    userPermissions: (userId: number) =>
      [...queryKeys.rbac.all, "user-permissions", userId] as const,
    myPermissions: () => [...queryKeys.rbac.all, "my-permissions"] as const,
  },
  users: {
    all: ["users"] as const,
    list: () => [...queryKeys.users.all, "list"] as const,
    detail: (id: number) => [...queryKeys.users.all, "detail", id] as const,
  },
};
