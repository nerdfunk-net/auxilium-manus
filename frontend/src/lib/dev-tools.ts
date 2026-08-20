// ENABLE_DEV_TOOLS alone is not enough to expose the OIDC test dashboard and
// its raw-JWT callback route: a production deployment that inherits a dev
// .env file would otherwise leak client_id/discovery URLs and render access
// tokens in the DOM to any authenticated (or, for the callback, unauthenticated)
// visitor. Require NODE_ENV !== "production" in addition to the flag.
export function isDevToolsEnabled(): boolean {
  return process.env.NODE_ENV !== "production" && process.env.ENABLE_DEV_TOOLS === "true";
}
