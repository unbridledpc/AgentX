from __future__ import annotations

from dataclasses import dataclass
import sys
from typing import Any, Callable, Iterable, TypeVar

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.rule import Rule
    from rich.table import Table
    from rich.text import Text

    RICH_AVAILABLE = True
except Exception:  # pragma: no cover - fallback path
    Console = None  # type: ignore[assignment]
    Panel = None  # type: ignore[assignment]
    Rule = None  # type: ignore[assignment]
    Table = None  # type: ignore[assignment]
    Text = None  # type: ignore[assignment]
    RICH_AVAILABLE = False


BRAND_NAME = "NexAI"
BRAND_SUBTITLE = "Local-first AI assistant platform"
GALAXY_PRIMARY = "bold #5B8CFF"
GALAXY_SECONDARY = "#8A5BFF"
GALAXY_ACCENT = "#00D4FF"
GALAXY_DIM = "grey50"
GALAXY_SUCCESS = "green"
GALAXY_WARN = "yellow"
GALAXY_ERROR = "red"
GALAXY_NOTE = "#B8C6FF"

_STATUS_ICONS = {
    "pass": "[green][PASS][/green]",
    "warn": "[yellow][WARN][/yellow]",
    "fail": "[red][FAIL][/red]",
}

_T = TypeVar("_T")


@dataclass(frozen=True)
class SummaryItem:
    label: str
    value: str


_console = Console() if RICH_AVAILABLE else None
_stderr_console = Console(stderr=True) if RICH_AVAILABLE else None


def _plain_print(message: str = "", *, stderr: bool = False) -> None:
    print(message, file=sys.stderr if stderr else sys.stdout)


def _message(prefix: str, message: str) -> None:
    to_stderr = prefix in {"warn", "error"}
    if RICH_AVAILABLE and _console is not None:
        target = _stderr_console if to_stderr and _stderr_console is not None else _console
        if prefix == "info":
            target.print(f"[{GALAXY_ACCENT}][*][/{GALAXY_ACCENT}] {message}")
        elif prefix == "success":
            target.print(f"[{GALAXY_SUCCESS}][+][/{GALAXY_SUCCESS}] {message}")
        elif prefix == "warn":
            target.print(f"[{GALAXY_WARN}][!][/{GALAXY_WARN}] {message}")
        else:
            target.print(f"[{GALAXY_ERROR}][-][/{GALAXY_ERROR}] {message}")
        return
    plain_prefix = {
        "info": "INFO",
        "warn": "WARN",
        "error": "ERROR",
        "success": "OK",
    }[prefix]
    _plain_print(f"{plain_prefix}: {message}", stderr=to_stderr)


def show_logo() -> None:
    if RICH_AVAILABLE and _console is not None:
        logo = Text()
        logo.append("  ███╗   ██╗███████╗██╗  ██╗ █████╗ ██╗\n", GALAXY_PRIMARY)
        logo.append("  ████╗  ██║██╔════╝╚██╗██╔╝██╔══██╗██║\n", GALAXY_SECONDARY)
        logo.append("  ██╔██╗ ██║█████╗   ╚███╔╝ ███████║██║\n", GALAXY_SECONDARY)
        logo.append("  ██║╚██╗██║██╔══╝   ██╔██╗ ██╔══██║██║\n", "#6B7CFF")
        logo.append("  ██║ ╚████║███████╗██╔╝ ██╗██║  ██║██║\n", GALAXY_PRIMARY)
        subtitle = Text(BRAND_SUBTITLE, style=f"bold {GALAXY_ACCENT}")
        _console.print(
            Panel.fit(
                Text.assemble(logo, "\n", subtitle),
                title=f"[bold {GALAXY_SECONDARY}]{BRAND_NAME}[/bold {GALAXY_SECONDARY}]",
                border_style="#5B8CFF",
            )
        )
        return
    _plain_print(BRAND_NAME)
    _plain_print(BRAND_SUBTITLE)


def section(title: str, *, subtitle: str | None = None) -> None:
    if RICH_AVAILABLE and _console is not None:
        _console.print(Rule(f"[bold {GALAXY_SECONDARY}]{title}[/bold {GALAXY_SECONDARY}]"))
        if subtitle:
            _console.print(f"[{GALAXY_DIM}]{subtitle}[/{GALAXY_DIM}]")
        return
    _plain_print(f"\n== {title} ==")
    if subtitle:
        _plain_print(subtitle)


def stage(index: int, total: int, title: str, *, subtitle: str | None = None) -> None:
    section(f"Step {index}/{total}  {title}", subtitle=subtitle)


def subsection(title: str, *, subtitle: str | None = None) -> None:
    if RICH_AVAILABLE and _console is not None:
        _console.print(f"[bold {GALAXY_PRIMARY}]{title}[/bold {GALAXY_PRIMARY}]")
        if subtitle:
            _console.print(f"[{GALAXY_DIM}]{subtitle}[/{GALAXY_DIM}]")
        return
    _plain_print(title)
    if subtitle:
        _plain_print(subtitle)


def info(message: str) -> None:
    _message("info", message)


def warn(message: str) -> None:
    _message("warn", message)


def error(message: str) -> None:
    _message("error", message)


def success(message: str) -> None:
    _message("success", message)


def note(message: str) -> None:
    if RICH_AVAILABLE and _console is not None:
        _console.print(f"[{GALAXY_NOTE}][•][/{GALAXY_NOTE}] {message}")
        return
    _plain_print(f"NOTE: {message}")


def bullet_list(items: Iterable[str], *, style: str = "default") -> None:
    material = [item for item in items if item]
    if not material:
        return
    if RICH_AVAILABLE and _console is not None:
        color = {
            "default": GALAXY_DIM,
            "warn": GALAXY_WARN,
            "error": GALAXY_ERROR,
            "success": GALAXY_SUCCESS,
        }.get(style, GALAXY_DIM)
        for item in material:
            _console.print(f"[{color}]- {item}[/{color}]")
        return
    for item in material:
        _plain_print(f"- {item}")


def preflight_result(status: str, title: str, details: str | None = None) -> None:
    key = status.strip().lower()
    if RICH_AVAILABLE and _console is not None:
        icon = _STATUS_ICONS.get(key, _STATUS_ICONS["warn"])
        _console.print(f"{icon} [bold]{title}[/bold]")
        if details:
            _console.print(f"[{GALAXY_DIM}]    {details}[/{GALAXY_DIM}]")
        return
    plain = key.upper()
    _plain_print(f"{plain}: {title}")
    if details:
        _plain_print(f"  {details}")


def run_with_status(message: str, fn: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
    if RICH_AVAILABLE and _console is not None:
        with _console.status(f"[bold {GALAXY_ACCENT}]{message}[/bold {GALAXY_ACCENT}]"):
            return fn(*args, **kwargs)
    info(message)
    return fn(*args, **kwargs)


def summary_panel(title: str, items: Iterable[SummaryItem | tuple[str, str] | str], *, style: str = "#5B8CFF") -> None:
    lines: list[str] = []
    for item in items:
        if isinstance(item, SummaryItem):
            lines.append(f"{item.label}: {item.value}")
        elif isinstance(item, tuple):
            lines.append(f"{item[0]}: {item[1]}")
        else:
            lines.append(str(item))
    if RICH_AVAILABLE and _console is not None:
        body = "\n".join(lines)
        _console.print(
            Panel(
                body,
                title=f"[bold {GALAXY_SECONDARY}]{title}[/bold {GALAXY_SECONDARY}]",
                border_style=style,
                expand=False,
            )
        )
        return
    _plain_print(title)
    for line in lines:
        _plain_print(f"- {line}")


def next_steps_panel(title: str, steps: Iterable[str], *, notes: Iterable[str] | None = None) -> None:
    items: list[str] = [f"• {step}" for step in steps if step]
    if notes:
        items.extend(f"Note: {note_item}" for note_item in notes if note_item)
    summary_panel(title, items, style=GALAXY_ACCENT)


def failure_panel(title: str, message: str, *, guidance: Iterable[str] | None = None, log_path: str | None = None) -> None:
    lines = [message]
    if guidance:
        lines.extend(f"- {item}" for item in guidance if item)
    if log_path:
        lines.append(f"Log file: {log_path}")
    summary_panel(title, lines, style=GALAXY_ERROR)


def key_value_table(title: str, rows: Iterable[tuple[str, str]]) -> None:
    material = [(left, right) for left, right in rows if left or right]
    if not material:
        return
    if RICH_AVAILABLE and _console is not None and Table is not None:
        table = Table(
            title=f"[bold {GALAXY_SECONDARY}]{title}[/bold {GALAXY_SECONDARY}]",
            border_style=GALAXY_PRIMARY,
            show_header=False,
            box=None,
            pad_edge=False,
        )
        table.add_column(style=GALAXY_PRIMARY, no_wrap=True)
        table.add_column(style="default")
        for left, right in material:
            table.add_row(left, right)
        _console.print(table)
        return
    summary_panel(title, [f"{left}: {right}" for left, right in material])


def spacer() -> None:
    _plain_print()
