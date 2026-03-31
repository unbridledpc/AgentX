# Release Packaging

Use the deterministic packaging script to build a clean release archive:

```powershell
python .\scripts\package_release.py
```

The release archive:

- defaults to `nexai-<version>.zip`
- includes `install-sol.sh`, `SolVersion2`, `apps`, and built `SolWeb/dist`
- requires `SolWeb/dist/index.html`
- excludes local state such as `.git`, virtualenvs, caches, logs, data directories, editor junk, frontend source, and tests
- writes:
  - `dist/nexai-<version>.zip`
  - `dist/nexai-<version>.zip.sha256`
  - `dist/release-manifest.json`

The script validates:

- required roots and built assets exist
- forbidden content is not present in the final archive
- expected archive layout is present
- shipped Python files compile in the staged release tree

The final release summary prints the version, archive path, SHA256, file count, size, and warnings.
