# AgentXWeb V9 patch bundle

This bundle applies the V9 frontend stabilization patch to `AgentXWeb`.

## What it fixes

- TypeScript build failures in `src/api/client.ts`, `src/ui/App.tsx`, and `src/ui/pages/SettingsPage.tsx`.
- Missing Workbench `thread_workspace` response type.
- Incorrect thread-summary state update that attempted to store message arrays in `ThreadSummary`.
- Missing Settings page `updateModelBehavior` helper.
- Build script now runs typecheck before Vite build.
- Adds `CHANGELOG.md` and bumps package version to `0.2.7-v9`.

## Apply on the VM

Copy these two files into the parent directory that contains `AgentXWeb/`:

- `AgentXWeb-v9-typecheck-stabilization.patch`
- `apply-agentxweb-v9.sh`

Then run:

```bash
cd ~/projects
bash apply-agentxweb-v9.sh
```

If your path is different:

```bash
bash apply-agentxweb-v9.sh AgentXWeb-v9-typecheck-stabilization.patch /path/to/AgentXWeb
```

The script makes a backup first, then runs:

```bash
npm ci
npm run typecheck
npm test
npm run build
```

## Manual apply

```bash
cd ~/projects
cp -a AgentXWeb AgentXWeb.bak-v9-$(date +%Y%m%d-%H%M%S)
patch -p0 < AgentXWeb-v9-typecheck-stabilization.patch
cd AgentXWeb
npm ci
npm run typecheck
npm test
npm run build
```
