from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

from sol.cli import main as cli_main
from sol.cli.run import compose_run_prompt, read_stdin_text, read_task_file, run_task_via_api
from sol.install.models import InstallProfile, ServiceMode
from sol.install.store import save_install_config
from sol.install.wizard import build_install_config


def _config(tmp_path: Path) -> object:
    app_root = tmp_path / "app"
    (app_root / "SolVersion2" / "plugins").mkdir(parents=True)
    (app_root / "SolVersion2" / "skills").mkdir(parents=True)
    (app_root / "SolVersion2" / "Server" / "data" / "features").mkdir(parents=True)
    (app_root / "apps" / "api" / "sol_api").mkdir(parents=True)
    (app_root / "SolWeb" / "dist").mkdir(parents=True)
    (app_root / "SolWeb" / "dist" / "index.html").write_text("ok", encoding="utf-8")
    return build_install_config(
        app_root=app_root,
        runtime_root=tmp_path / "runtime",
        working_dir=tmp_path / "work",
        profile=InstallProfile.STANDARD,
        model_provider="stub",
        api_host="127.0.0.1",
        api_port=8420,
        web_host="127.0.0.1",
        web_port=5173,
        service_mode=ServiceMode.SYSTEMD_USER,
    )


class _FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeHttpError(urllib.error.HTTPError):
    def __init__(self, url: str, code: int, payload: object) -> None:
        super().__init__(url, code, "error", hdrs=None, fp=None)
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload


class _FakeStdin(io.StringIO):
    def __init__(self, text: str, *, is_tty: bool) -> None:
        super().__init__(text)
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


def test_run_task_via_api_success_returns_response_text(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda req, timeout=60.0: _FakeResponse({"role": "assistant", "content": "Hello from NexAI"}),
    )
    result = run_task_via_api(config, "say hello")
    assert result.ok is True
    assert result.text == "Hello from NexAI"
    assert result.exit_code == 0


def test_run_task_via_api_returns_clean_message_when_api_unreachable(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=60.0: (_ for _ in ()).throw(urllib.error.URLError("boom")))
    result = run_task_via_api(config, "say hello")
    assert result.ok is False
    assert result.text == "NexAI API is not running. Try: nexai service status"
    assert result.exit_code == 1


def test_run_task_via_api_maps_provider_error_response(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)

    def _raise(req, timeout=60.0):
        raise _FakeHttpError(
            "http://127.0.0.1:8420/v1/chat",
            502,
            {
                "detail": {
                    "type": "model_unavailable",
                    "provider": "ollama",
                    "model": "qwen3.5:9b",
                    "message": "Model `qwen3.5:9b` is not available on the configured Ollama instance.",
                    "base_url": "http://127.0.0.1:11434",
                }
            },
        )

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    result = run_task_via_api(config, "say hello")
    assert result.ok is False
    assert result.text == "Model 'qwen3.5:9b' is not available"
    assert result.exit_code == 1


def test_run_task_via_api_returns_usage_error_for_empty_task(tmp_path: Path) -> None:
    config = _config(tmp_path)
    result = run_task_via_api(config, "   ")
    assert result.ok is False
    assert result.text == 'Usage: nexai run "<task>"'
    assert result.exit_code == 2


def test_read_task_file_returns_file_contents(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("line one\nline two\n", encoding="utf-8")
    result = read_task_file(str(path))
    assert result == "line one\nline two\n"


def test_read_task_file_missing_returns_clean_error(tmp_path: Path) -> None:
    result = read_task_file(str(tmp_path / "missing.txt"))
    assert result.text == f"File not found: {tmp_path / 'missing.txt'}"
    assert result.exit_code == 2


def test_read_task_file_non_utf8_returns_clean_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.bin"
    path.write_bytes(b"\xff\xfe\xfd")
    result = read_task_file(str(path))
    assert result.text == f"Input file must be UTF-8 text: {path}"
    assert result.exit_code == 2


def test_read_stdin_text_returns_none_for_tty() -> None:
    assert read_stdin_text(_FakeStdin("", is_tty=True)) is None


def test_compose_run_prompt_with_task_and_file_combines_correctly() -> None:
    prompt = compose_run_prompt("summarize this file", file_text="alpha\nbeta\n")
    assert prompt == "summarize this file\n\nalpha\nbeta\n"


def test_compose_run_prompt_with_stdin_only_uses_stdin() -> None:
    prompt = compose_run_prompt("", stdin_text="from pipe")
    assert prompt == "from pipe"


def test_compose_run_prompt_with_task_and_stdin_combines_correctly() -> None:
    prompt = compose_run_prompt("explain this error", stdin_text="Traceback...")
    assert prompt == "explain this error\n\nTraceback..."


def test_compose_run_prompt_rejects_file_and_stdin_together() -> None:
    result = compose_run_prompt("task", file_text="alpha", stdin_text="beta")
    assert result.text == "Use either --file or stdin, not both"
    assert result.exit_code == 2


def test_compose_run_prompt_rejects_whitespace_only_file() -> None:
    result = compose_run_prompt("summarize", file_text="   ")
    assert result.text == "No usable input provided"
    assert result.exit_code == 2


def test_cli_run_joins_multiword_input_and_prints_response(tmp_path: Path, monkeypatch, capsys) -> None:
    config = _config(tmp_path)
    install_cfg = tmp_path / "install.json"
    save_install_config(config, install_cfg)
    captured_task: dict[str, object] = {}
    monkeypatch.setattr("sol.cli.status_installation", lambda install: {"services": {"api": {"state": "running", "healthy": True}}})
    monkeypatch.setattr(
        "sol.cli.run_task_via_api",
        lambda install, task, status=None: captured_task.update({"task": task, "status": status}) or type("Result", (), {"text": "done", "exit_code": 0})(),
    )
    monkeypatch.setattr("sol.cli.build_runtime_services_from_config", lambda config_path, confirm: type("Services", (), {"agent": object()})())
    monkeypatch.setattr("sys.stdin", _FakeStdin("", is_tty=True))
    code = cli_main(["--install-config", str(install_cfg), "run", "write", "a", "hello", "world", "script"])
    captured = capsys.readouterr()
    assert code == 0
    assert captured_task["task"] == "write a hello world script"
    assert captured.out.strip() == "done"


def test_cli_run_empty_input_returns_usage_error(tmp_path: Path, monkeypatch, capsys) -> None:
    config = _config(tmp_path)
    install_cfg = tmp_path / "install.json"
    save_install_config(config, install_cfg)
    monkeypatch.setattr("sol.cli.build_runtime_services_from_config", lambda config_path, confirm: type("Services", (), {"agent": object()})())
    monkeypatch.setattr("sol.cli.status_installation", lambda install: None)
    monkeypatch.setattr("sys.stdin", _FakeStdin("", is_tty=True))
    code = cli_main(["--install-config", str(install_cfg), "run", ""])
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out.strip() == 'Usage: nexai run "<task>"'


def test_cli_run_file_only_uses_file_contents(tmp_path: Path, monkeypatch, capsys) -> None:
    config = _config(tmp_path)
    install_cfg = tmp_path / "install.json"
    notes = tmp_path / "notes.txt"
    notes.write_text("alpha\nbeta\n", encoding="utf-8")
    save_install_config(config, install_cfg)
    captured_task: dict[str, object] = {}
    monkeypatch.setattr("sol.cli.build_runtime_services_from_config", lambda config_path, confirm: type("Services", (), {"agent": object()})())
    monkeypatch.setattr("sol.cli.status_installation", lambda install: {"services": {"api": {"state": "running", "healthy": True}}})
    monkeypatch.setattr("sys.stdin", _FakeStdin("", is_tty=True))
    monkeypatch.setattr(
        "sol.cli.run_task_via_api",
        lambda install, task, status=None: captured_task.update({"task": task}) or type("Result", (), {"text": "ok", "exit_code": 0})(),
    )
    code = cli_main(["--install-config", str(install_cfg), "run", "--file", str(notes)])
    captured = capsys.readouterr()
    assert code == 0
    assert captured_task["task"] == "alpha\nbeta\n"
    assert captured.out.strip() == "ok"


def test_cli_run_task_and_file_combine_correctly(tmp_path: Path, monkeypatch, capsys) -> None:
    config = _config(tmp_path)
    install_cfg = tmp_path / "install.json"
    notes = tmp_path / "notes.txt"
    notes.write_text("alpha\nbeta\n", encoding="utf-8")
    save_install_config(config, install_cfg)
    captured_task: dict[str, object] = {}
    monkeypatch.setattr("sol.cli.build_runtime_services_from_config", lambda config_path, confirm: type("Services", (), {"agent": object()})())
    monkeypatch.setattr("sol.cli.status_installation", lambda install: {"services": {"api": {"state": "running", "healthy": True}}})
    monkeypatch.setattr("sys.stdin", _FakeStdin("", is_tty=True))
    monkeypatch.setattr(
        "sol.cli.run_task_via_api",
        lambda install, task, status=None: captured_task.update({"task": task}) or type("Result", (), {"text": "ok", "exit_code": 0})(),
    )
    code = cli_main(["--install-config", str(install_cfg), "run", "--file", str(notes), "summarize", "this", "file"])
    captured = capsys.readouterr()
    assert code == 0
    assert captured_task["task"] == "summarize this file\n\nalpha\nbeta\n"
    assert captured.out.strip() == "ok"


def test_cli_run_stdin_only_uses_stdin_contents(tmp_path: Path, monkeypatch, capsys) -> None:
    config = _config(tmp_path)
    install_cfg = tmp_path / "install.json"
    save_install_config(config, install_cfg)
    captured_task: dict[str, object] = {}
    monkeypatch.setattr("sol.cli.build_runtime_services_from_config", lambda config_path, confirm: type("Services", (), {"agent": object()})())
    monkeypatch.setattr("sol.cli.status_installation", lambda install: {"services": {"api": {"state": "running", "healthy": True}}})
    monkeypatch.setattr("sys.stdin", _FakeStdin("line one\nline two\n", is_tty=False))
    monkeypatch.setattr(
        "sol.cli.run_task_via_api",
        lambda install, task, status=None: captured_task.update({"task": task}) or type("Result", (), {"text": "ok", "exit_code": 0})(),
    )
    code = cli_main(["--install-config", str(install_cfg), "run"])
    captured = capsys.readouterr()
    assert code == 0
    assert captured_task["task"] == "line one\nline two\n"
    assert captured.out.strip() == "ok"


def test_cli_run_task_and_stdin_combine_correctly(tmp_path: Path, monkeypatch, capsys) -> None:
    config = _config(tmp_path)
    install_cfg = tmp_path / "install.json"
    save_install_config(config, install_cfg)
    captured_task: dict[str, object] = {}
    monkeypatch.setattr("sol.cli.build_runtime_services_from_config", lambda config_path, confirm: type("Services", (), {"agent": object()})())
    monkeypatch.setattr("sol.cli.status_installation", lambda install: {"services": {"api": {"state": "running", "healthy": True}}})
    monkeypatch.setattr("sys.stdin", _FakeStdin("Traceback...", is_tty=False))
    monkeypatch.setattr(
        "sol.cli.run_task_via_api",
        lambda install, task, status=None: captured_task.update({"task": task}) or type("Result", (), {"text": "ok", "exit_code": 0})(),
    )
    code = cli_main(["--install-config", str(install_cfg), "run", "explain", "this", "error"])
    captured = capsys.readouterr()
    assert code == 0
    assert captured_task["task"] == "explain this error\n\nTraceback..."
    assert captured.out.strip() == "ok"


def test_cli_run_rejects_file_and_stdin_together(tmp_path: Path, monkeypatch, capsys) -> None:
    config = _config(tmp_path)
    install_cfg = tmp_path / "install.json"
    notes = tmp_path / "notes.txt"
    notes.write_text("alpha\n", encoding="utf-8")
    save_install_config(config, install_cfg)
    monkeypatch.setattr("sol.cli.build_runtime_services_from_config", lambda config_path, confirm: type("Services", (), {"agent": object()})())
    monkeypatch.setattr("sys.stdin", _FakeStdin("beta\n", is_tty=False))
    code = cli_main(["--install-config", str(install_cfg), "run", "--file", str(notes)])
    captured = capsys.readouterr()
    assert code == 2
    assert captured.out.strip() == "Use either --file or stdin, not both"


def test_cli_run_preserves_interactive_fallback_with_no_args_and_tty_stdin(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path)
    install_cfg = tmp_path / "install.json"
    save_install_config(config, install_cfg)
    monkeypatch.setattr("sol.cli.build_runtime_services_from_config", lambda config_path, confirm: type("Services", (), {"agent": object()})())
    monkeypatch.setattr("sys.stdin", _FakeStdin("", is_tty=True))
    monkeypatch.setattr("sol.cli.interactive_run", lambda agent: 0)
    assert cli_main(["--install-config", str(install_cfg), "run"]) == 0
