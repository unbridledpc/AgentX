from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Tuple


class ToolValidationError(ValueError):
    pass


class ToolExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolArgument:
    name: str
    type: type | Tuple[type, ...]
    description: str
    required: bool = False
    default: Any = None


class Tool:
    name: str
    description: str
    args: Tuple[ToolArgument, ...] = ()
    safety_flags: Tuple[str, ...] = ()
    timeout_seconds: int | None = None
    requires_confirmation: bool = False
    destructive: bool = False

    def validate_args(self, raw_args: dict[str, Any]) -> dict[str, Any]:
        if raw_args is None:
            raw_args = {}
        normalized: dict[str, Any] = {}
        schema_names = {param.name for param in self.args}
        unknown = set(raw_args.keys()) - schema_names
        if unknown:
            raise ToolValidationError(f"Unknown arguments: {', '.join(sorted(unknown))}")

        for param in self.args:
            if param.name not in raw_args or raw_args[param.name] is None:
                if param.required and param.default is None:
                    raise ToolValidationError(f"Missing required argument: {param.name}")
                normalized[param.name] = param.default
                continue

            value = raw_args[param.name]
            expected = param.type
            if not isinstance(value, expected):
                raise ToolValidationError(
                    f"Argument {param.name} expected {expected}, got {type(value).__name__}"
                )
            normalized[param.name] = value

        return normalized

    def run(self, ctx, args: dict[str, Any]) -> Any:  # pragma: no cover
        raise NotImplementedError()
