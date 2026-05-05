# AgentX Frontend Archive Workbench Patch

Private experimental Phase 3 patch.

This adds a WebUI-first flow:

1. Open AgentX WebUI.
2. Open a chat.
3. Click the composer `+` menu.
4. Choose **Upload server archive**.
5. Select `.zip`, `.rar`, `.7z`, `.tar`, `.tgz`, or `.tar.gz`.
6. AgentX uploads it to the API, extracts into the sandbox workbench, analyzes it, then posts the report back into the chat.

## Install

From `~/projects/AgentX`:

```bash
unzip -o AgentX_frontend_archive_workbench_patch.zip
bash scripts/install-frontend-archive-workbench.sh ~/projects/AgentX
```

## Notes

- ZIP works with Python standard library.
- RAR/7z/TAR require an extractor installed on the AgentX VM, such as `7z`/`7zz`, `bsdtar`, `unar`, or `unrar`.
- If RAR/7z fails, install an extractor on the VM. For Ubuntu/Debian, try:

```bash
sudo apt update
sudo apt install -y p7zip-full p7zip-rar
```

If `p7zip-rar` is unavailable on your distro, use ZIP for now or install `unar`/`unrar`.

This version is read-only. It does not edit files, run project code, or patch anything automatically.
