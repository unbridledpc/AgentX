// Public-safe AgentXWeb runtime config example.
// Copy to agentxweb.local.config.js or agentxweb.config.js for a deployment-specific override.
// Do not commit private LAN IPs here.
window.AGENTX_WEB_CONFIG = {
  apiBase: window.location.origin.replace(":5173", ":8000").replace(":5174", ":8000"),
  updateFeed: {
    enabled: true,
    repo: "unbridledpc/AgentX",
    branch: "main",
    currentSha: "",
    currentVersion: "0.3.0-v12"
  }
};
