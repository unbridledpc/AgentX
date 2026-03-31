// Runtime config for SolWeb (served as a static file).
//
// This lets you change the API base *without* rebuilding the site.
//
// Examples:
// - same-origin reverse proxy: window.__SOLWEB_CONFIG__ = { apiBase: "/api", showInspector: false };
// - direct backend:            window.__SOLWEB_CONFIG__ = { apiBase: "http://127.0.0.1:8420", showInspector: true };
window.__SOLWEB_CONFIG__ = {
  apiBase: "http://127.0.0.1:8420",
  // Hide the Inspector by default on non-localhost deployments.
  // Set to true to force-enable it.
  showInspector: undefined
};
