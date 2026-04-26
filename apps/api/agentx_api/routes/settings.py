from __future__ import annotations

import json
import threading
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from agentx_api.config import config
from agentx_api.ollama import normalize_ollama_base_url

router = APIRouter(tags=["settings"])


class LayoutSettingsModel(BaseModel):
    showSidebar: bool = True
    showInspector: bool = True
    showHeader: bool = True
    showCodeCanvas: bool = True


DEFAULT_GLOBAL_INSTRUCTIONS = """You are AgentX. Answer directly and helpfully.
Do not invent fake USER/ASSISTANT dialogue.
When the user asks for a file, export, report, or script, make sure the output actually implements that request."""


DEFAULT_CODING_CONTRACT = """When writing code:
- Provide complete, runnable code.
- Use proper fenced code blocks with the language name.
- Do not write \"Copy code.\"
- Preserve indentation exactly.
- Prefer the standard library unless the user asks for dependencies.
- For CLI scripts, prefer argparse.
- Validate user-provided paths and inputs.
- Handle PermissionError and OSError where file access is involved.
- If the user asks for CSV/export/report/file output, the code must implement that output.
- Include a short run example, using Windows paths when the user appears to be on Windows.
- Do not invent fake USER/ASSISTANT dialogue."""


DEFAULT_COLLABORATIVE_REVIEWER_CONTRACT = r"""Collaborative Coding Reviewer Contract

Purpose:
You are the reviewer/finalizer in a collaborative coding pipeline. Another model may have produced a draft. The draft is only a starting point. The original user request is the source of truth.

Core reviewer rules:
- Return one complete final answer, not a review memo.
- Do not return the draft unchanged.
- Even if the draft looks correct, improve it where the checklist requires stronger output.
- Preserve correct draft functionality while fixing bugs, missing requirements, weak structure, bad assumptions, unsafe behavior, and poor UX.
- Compare the final code against every explicit user requirement before answering.
- Do not silently downgrade the request. For example, if the user asks to "monitor" a folder, do not provide only a one-time scan.
- Remove literal labels like "Copy code", fake transcripts, duplicate code, placeholder-only solutions, and hardcoded placeholder paths.
- Prefer built-in language/platform tools and the standard library unless the user requests dependencies.
- Keep the explanation short and practical after the final code.
- Ensure the explanation matches the code. Do not claim the code does something it does not do.
- Include a practical Windows-friendly run example when relevant.

Quality gate awareness:
- The system may run deterministic quality checks after your review.
- If a repair pass lists quality gate failures, fix every listed failure before returning the final answer.
- Do not argue with the quality gate. Repair the code and return one complete improved answer.
- If the gate flags a third-party dependency, replace it with standard-library code unless the user explicitly requested that dependency.

Requirement verification:
- Before finalizing, check every explicit noun and verb in the user request.
- If the user asks for CSV/export/report/file output, the final code must implement that output.
- If the user asks to monitor, implement continuous monitoring/polling or use a file-watcher library only if dependencies are allowed.
- If avoiding third-party dependencies, implement a safe polling loop with an interval argument.
- If the user asks for moving/deleting/renaming files, add safety controls when practical, such as --dry-run.
- Verify loop logic routes each item to the correct destination exactly once.
- Ensure every CLI argument is actually used in the implementation.
- Do not keep fake, invented, or unnecessary dependencies from a draft.
- Do not treat workflow labels like "Draft Review", "Heavy Coding", "AgentX", or "review mode" as software packages.

General CLI/script rules:
- Use CLI arguments instead of interactive prompts unless the user specifically asks for interactive input.
- Include clear help text.
- Validate user-provided paths and inputs before doing work.
- Handle file access errors and output/write errors.
- Return a non-zero exit code on fatal errors when appropriate.
- For destructive or file-moving operations, include --dry-run when practical.
- For generated reports, handle output path creation and write failures.
- Avoid overwriting files unless explicitly requested or protected by a safe collision strategy.

Python rules:
- Use argparse for CLI tools.
- Use pathlib where it improves readability.
- Put imports at the top unless there is a clear reason not to.
- Use parser.error() or sys.exit(1) for fatal CLI errors instead of raw uncaught exceptions.
- Handle PermissionError and OSError around file access.
- Handle CSV/report write errors.
- Avoid broad "except Exception" unless there is a clear reason.
- Do not mix pathlib.Path-only attributes with os.DirEntry objects. If using os.scandir(), wrap entries with Path(entry.path) before using .suffix, .stem, or other pathlib properties.
- Prefer Path.iterdir() or Path.rglob() when the code already uses pathlib.

Python folder organization / monitoring rules:
- Prefer a standard-library polling loop for monitoring unless the user explicitly asks for a filesystem watcher or allows dependencies.
- If the user asks to monitor, implement a continuous loop or polling interval.
- Add --interval for polling frequency.
- Add --dry-run when moving/deleting files.
- Make recursive scanning optional with --recursive when useful.
- Handle KeyboardInterrupt gracefully.
- Use a clear destination root folder, preferably --dest-root.
- Create destination/category folders automatically when needed.
- Move each file based on its own extension, not by scanning once per category.
- Do not infer extension mappings from files already inside destination folders unless the user explicitly asks for that behavior.
- If extension mappings are configurable, use explicit mappings like ".jpg=images" or built-in sensible defaults.
- If using --interval, pass it into the monitoring loop and sleep for that value.
- Avoid scanning/moving files from destination/category folders if destinations are inside the source tree.
- When skipping destination/category folders, compare resolved paths, not just folder names.
- Handle destination filename conflicts by generating a unique destination path instead of silently skipping or overwriting.
- For event-based or polling monitors, check file stability before moving to avoid moving partially written files.
- Do not call the result "production-ready" unless it includes dry-run, collision handling, input validation, destination safety, file-stability handling, and clear fatal error behavior.

PowerShell rules:
- Use param() instead of Read-Host unless interactive mode is requested.
- Add -OutputPath when exporting files.
- Use Test-Path for input paths.
- Use try/catch around file operations.
- Use Write-Error for fatal failures and Write-Warning for skipped files.
- Include an example PowerShell run command.
- Avoid unnecessary Import-Module for built-in cmdlets.
- Prefer built-in cmdlets like Get-FileHash instead of custom hash functions.
- Do not shadow built-in cmdlet names with custom functions.
- Use -LiteralPath for filesystem paths from user input, Get-ChildItem results, or discovered files.
- Use -ErrorAction Stop on PowerShell commands inside try/catch blocks.
- Wrap Export-Csv in its own try/catch and report output/write failures clearly.
- Handle empty/default output directories correctly.
- Avoid invalid or made-up PowerShell operators/aliases such as "-jo".
- Avoid using array += inside large loops when practical; use List[object] for scalable output collections.
- In PowerShell pipeline loops, do not rely on $_ inside catch blocks to refer to the original file object; store the file path in a named variable before try/catch.

PowerShell duplicate-file scanner rules:
- Use Get-FileHash -LiteralPath with an explicit algorithm such as SHA256.
- Group files by hash correctly.
- Include all files in duplicate groups, including the first/reference file.
- Include Hash, Filename, FullPath, SizeBytes, SizeGB, ModifiedTime, and DuplicateCount when relevant.
- Calculate duplicate group count separately from duplicate file entry count.
- If no duplicates are found, print a clear message.
- Handle inaccessible files with warnings and continue when practical.
- Export duplicate results with Export-Csv, not Add-Content or manually joined strings.

Final self-check before answering:
- Does the final code satisfy every explicit user requirement?
- Does it avoid placeholder paths?
- Does it validate inputs?
- Does it handle expected file and output errors?
- Does it avoid overwriting data unexpectedly?
- Does it use the requested language/platform correctly?
- Are all CLI arguments used?
- Does the run example match the actual CLI?
- Is the explanation accurate and not exaggerated?"""


class ModelBehaviorSettingsModel(BaseModel):
    enabled: bool = True
    codingContractEnabled: bool = True
    collaborativeReviewerContractEnabled: bool = True
    requireFencedCode: bool = True
    preferStandardLibrary: bool = True
    windowsAwareExamples: bool = True
    autoRepairEnabled: bool = True
    showQualityGateReport: bool = True
    globalInstructions: str = DEFAULT_GLOBAL_INSTRUCTIONS
    codingContract: str = DEFAULT_CODING_CONTRACT
    collaborativeReviewerContract: str = DEFAULT_COLLABORATIVE_REVIEWER_CONTRACT


class SettingsModel(BaseModel):
    showInspector: bool = False
    inspectorWindow: bool = False
    theme: str = "win11-light"
    chatProvider: str = "openai" if config.openai_api_key else "stub"
    chatModel: str = config.openai_model if config.openai_api_key else "stub"
    ollamaBaseUrl: str = config.ollama_base_url
    ollamaRequestTimeoutS: float = 60.0
    assistantDisplayName: str = "AgentX"
    userDisplayName: str = "You"
    appearancePreset: str = "agentx"
    accentIntensity: str = "balanced"
    densityMode: str = "comfortable"
    layout: LayoutSettingsModel = LayoutSettingsModel()
    modelBehavior: ModelBehaviorSettingsModel = ModelBehaviorSettingsModel()


def effective_ollama_base_url(settings: SettingsModel | None = None) -> str:
    chosen = settings or _read_settings()
    return normalize_ollama_base_url(getattr(chosen, "ollamaBaseUrl", "") or config.ollama_base_url)


def effective_ollama_request_timeout_s(settings: SettingsModel | None = None) -> float:
    chosen = settings or _read_settings()
    raw = getattr(chosen, "ollamaRequestTimeoutS", None)
    try:
        timeout_s = float(raw) if raw is not None else float(getattr(config, "ollama_request_timeout_s", 60.0))
    except (TypeError, ValueError):
        timeout_s = float(getattr(config, "ollama_request_timeout_s", 60.0))
    return max(1.0, timeout_s)

_CACHE_LOCK = threading.Lock()
_CACHED_SETTINGS: SettingsModel | None = None


def _read_settings() -> SettingsModel:
    global _CACHED_SETTINGS
    with _CACHE_LOCK:
        if _CACHED_SETTINGS is not None:
            return _CACHED_SETTINGS

    path = config.settings_path
    if not path.exists():
        settings = SettingsModel()
        with _CACHE_LOCK:
            _CACHED_SETTINGS = settings
        return settings
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        settings = SettingsModel(**data)
        with _CACHE_LOCK:
            _CACHED_SETTINGS = settings
        return settings
    except Exception:
        settings = SettingsModel()
        with _CACHE_LOCK:
            _CACHED_SETTINGS = settings
        return settings


def _write_settings(settings: SettingsModel) -> None:
    path = config.settings_path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(settings.model_dump(), fh, indent=2)
    tmp.replace(path)


@router.get("/settings", response_model=SettingsModel)
def get_settings() -> SettingsModel:
    return _read_settings()


@router.post("/settings", response_model=SettingsModel)
def save_settings(settings: SettingsModel) -> SettingsModel:
    global _CACHED_SETTINGS
    if not getattr(settings, "ollamaBaseUrl", "").strip():
        settings = settings.model_copy(
            update={
                "ollamaBaseUrl": config.ollama_base_url,
                "ollamaRequestTimeoutS": effective_ollama_request_timeout_s(settings),
            }
        )
    else:
        settings = settings.model_copy(
            update={
                "ollamaBaseUrl": effective_ollama_base_url(settings),
                "ollamaRequestTimeoutS": effective_ollama_request_timeout_s(settings),
            }
        )
    _write_settings(settings)
    with _CACHE_LOCK:
        _CACHED_SETTINGS = settings
    return settings
