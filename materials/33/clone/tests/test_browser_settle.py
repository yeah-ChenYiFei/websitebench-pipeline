from __future__ import annotations

from browser_settle import settle_page


class FakePage:
    def __init__(self, observations: list[dict[str, object]]) -> None:
        self.observations = observations
        self.index = 0

    def evaluate(self, _script: str) -> dict[str, object]:
        observation = self.observations[min(self.index, len(self.observations) - 1)]
        self.index += 1
        return observation

    def wait_for_timeout(self, _milliseconds: int) -> None:
        return None


def _observation(
    height: int,
    sections: int,
    images: int,
    loaded: int,
    *,
    at_bottom: bool = True,
) -> dict[str, object]:
    return {
        "scroll_height": height,
        "section_count": sections,
        "image_count": images,
        "loaded_image_count": loaded,
        "failed_images": [],
        "at_bottom": at_bottom,
    }


def test_settle_requires_two_unchanged_bottom_observations() -> None:
    page = FakePage(
        [
            _observation(5000, 20, 20, 20, at_bottom=False),
            _observation(7000, 30, 30, 29),
            _observation(7000, 30, 30, 30),
            _observation(7000, 30, 30, 30),
        ]
    )

    result = settle_page(page, max_rounds=4)

    assert result["complete"] is True
    assert result["scroll_height"] == 7000
    assert result["loaded_image_count"] == 30


def test_settle_reports_timeout_instead_of_inventing_completion() -> None:
    page = FakePage([_observation(5000, 20, 20, 0)] * 3)

    result = settle_page(page, max_rounds=3)

    assert result["complete"] is False
    assert "image" in str(result["incomplete_reason"])
