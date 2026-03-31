# Supervised Autonomy Platform

This feature adds:

- supervised long-running jobs
- bounded reflection and reusable hints
- manifest-driven tool plugins
- instruction-only skills
- local skill-pack import for `SKILL.md` packs

## Safe defaults

- Jobs never bypass Sol's existing tool validation.
- Destructive and high-risk plans stop for approval.
- Tool execution still flows through the existing `Agent.execute(...)` path.
- Audit logging remains append-only and machine-readable.
- Learned hints are structured and promotion-gated.

## CLI quickstart

List plugins:

```powershell
python -m sol plugins list
```

Enable the example plugin:

```powershell
python -m sol plugins enable echo_demo
```

List skills:

```powershell
python -m sol skills list
```

Import a local skill pack:

```powershell
python -m sol skills import-pack "<path-to-skill-pack>"
```

Create and run a job:

```powershell
python -m sol job create --goal "Inspect the repo and summarize the backend entrypoint"
python -m sol job run <job_id>
```

If a job blocks on approval:

```powershell
python -m sol job approve <job_id>
python -m sol job run <job_id>
```
