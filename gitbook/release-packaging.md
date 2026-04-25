# Release Packaging

Release packaging is handled by:

```text
scripts/package_release.py
```

Run:

```powershell
python .\scripts\package_release.py
```

or:

```bash
python scripts/package_release.py
```

## Required Inputs

The release builder expects:

- `install-sol.sh`
- `SolVersion2/sol`
- `apps/api`
- `SolWeb`
- `SolWeb/dist/index.html`

Build SolWeb first:

```bash
cd SolWeb
npm install
npm run build
```

## Outputs

By default the script writes:

| Output | Purpose |
| --- | --- |
| `dist/nexai-<version>.zip` | Release archive |
| `dist/nexai-<version>.zip.sha256` | SHA256 checksum |
| `dist/release-manifest.json` | File manifest and metadata |

The version is read from:

```text
SolVersion2/sol/version.py
```

## Included Roots

The release includes:

- `install-sol.sh`
- root `README.md`
- `LICENSE`
- `RELEASE.md`
- `SolVersion2`
- `SolWeb`
- `apps`

## Exclusions

The release intentionally excludes:

- `.git`
- virtualenvs
- `node_modules`
- test folders
- Python caches
- pytest caches
- egg-info
- runtime data
- runtime logs
- API data
- editor junk
- desktop app folder
- SolWeb source files

`SolWeb/dist` is retained because it is the built frontend shipped in the release.

## Validation

The script validates:

- Required repo paths exist.
- Python files compile in the staged release tree.
- Required archive paths are present.
- Forbidden content is absent.
- The final archive checksum is generated.

If `SolWeb/dist/index.html` is older than `SolWeb/src`, the script warns that the frontend may need rebuilding.
