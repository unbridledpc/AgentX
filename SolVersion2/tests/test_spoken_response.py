from __future__ import annotations

from sol.core.response_sanitizer import finalize_response_text, sanitize_assistant_response


def test_sanitize_assistant_response_removes_think_blocks_and_tags() -> None:
    raw = "<think>I need to plan this.</think>\n</think>\nHello there."
    assert sanitize_assistant_response(raw) == "Hello there."


def test_sanitize_assistant_response_strips_leading_meta_lines() -> None:
    raw = "The user said they need a summary.\nI should keep it short.\nActual answer here."
    assert sanitize_assistant_response(raw) == "Actual answer here."


def test_finalize_response_text_spoken_removes_markdown_and_limits_sentences() -> None:
    raw = "Sure. <think>hidden</think> Here is the answer:\n- First sentence.\n- Second sentence.\n- Third sentence.\n- Fourth sentence."
    assert finalize_response_text(raw, response_mode="spoken") == "First sentence. Second sentence. Third sentence."


def test_finalize_response_text_spoken_uses_fallback_when_empty() -> None:
    assert finalize_response_text("<think>internal only</think>", response_mode="spoken") == "I'm here."
