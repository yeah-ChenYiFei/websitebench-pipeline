from __future__ import annotations

from tools.assert_verify_visuals import assess


def report(*, complete: bool = True, findings=None, messages=(), static_findings=None,
           static_complete: bool = True):
    return {
        "diagnostic_status": "clean",
        "sections": {
            "live": {
                "execution": {"complete": complete, "incomplete_reasons": []},
                "findings": [] if findings is None else findings,
                "observations": [
                    {"subject": f"subject-{index}", "message": message}
                    for index, message in enumerate(messages)
                ],
            },
            "static": {
                "execution": {"complete": static_complete, "incomplete_reasons": []},
                "findings": [] if static_findings is None else static_findings,
                "observations": [],
            },
        },
    }


def test_guard_accepts_a_complete_report_with_no_live_failures() -> None:
    result = assess(
        report(messages=("full-page similarity 0.95 is at or above the frozen reference threshold 0.94",))
    )
    assert result["ok"] is True
    assert result["below_threshold_observations"] == 0


def test_guard_rejects_below_threshold_observations_even_when_status_is_clean() -> None:
    result = assess(
        report(messages=("full-page similarity 0.91 is below the frozen reference threshold 0.94",))
    )
    assert result["ok"] is False
    assert result["below_threshold_observations"] == 1


def test_guard_rejects_live_findings_or_incomplete_execution() -> None:
    result = assess(report(complete=False, findings=[{"id": "live-finding"}]))
    assert result["ok"] is False
    assert result["live_findings"] == 1
    assert "live execution is incomplete" in result["errors"]


def test_guard_rejects_static_findings_even_when_live_is_clean() -> None:
    result = assess(report(static_findings=[{"id": "static-finding"}]))
    assert result["ok"] is False
    assert result["static_findings"] == 1


def test_guard_rejects_incomplete_static_execution() -> None:
    result = assess(report(static_complete=False))
    assert result["ok"] is False


def test_guard_rejects_a_report_without_a_static_section() -> None:
    payload = report()
    del payload["sections"]["static"]
    assert assess(payload)["ok"] is False
