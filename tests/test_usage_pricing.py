from types import SimpleNamespace

from asr.client_gemini import _usage_counts
from db import usage


def _row(model, inp, out, total, estimated=False, success=True):
    return SimpleNamespace(model=model, input_tokens=inp, output_tokens=out,
                           total_tokens=total, estimated=estimated, success=success)


def test_interactions_transcription_usage_includes_thinking_and_tool_tokens():
    meta = {"total_input_tokens": 1000, "total_output_tokens": 100,
            "total_thought_tokens": 20, "total_tool_use_tokens": 30,
            "total_tokens": 1150}
    assert _usage_counts(meta, 4000) == (1030, 120, 1150, False)
    assert _usage_counts({"total_tokens": 982}, 4000) == (0, 0, 982, True)
    assert _usage_counts({"total_input_tokens": 0, "total_tokens": 982}, 4000) == (0, 0, 982, True)
    assert _usage_counts({}, 4000) == (1000, 0, 1000, True)


def test_paid_equivalent_is_per_model_and_old_incomplete_usage_is_not_guessed():
    result = usage.model_breakdown([
        _row("gemini-3.5-transcribe", 1000, 200, 1200),
        _row("gemini-flash-lite-latest", 10000, 1000, 11000),
        _row("gemini-3.5-transcribe", 0, 0, 982, estimated=True),
        _row("unlisted-model", 0, 0, 500),
    ])
    assert result["total_tokens"] == 13682
    assert result["unpriced_tokens"] == 1482
    assert result["equivalent_cost_usd"] == 0.0099
    assert result["estimated_tokens"] is True
    alias = next(m for m in result["models"] if m["model"] == "gemini-flash-lite-latest")
    assert alias["price_status"] == "alias_assumption"
    assert alias["priced_as"] == "gemini-3.5-flash-lite"
    assert usage.prices()["models"]["gemini-3.5-transcribe"]["input_per_million"] == 2.0
