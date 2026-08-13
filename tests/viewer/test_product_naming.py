from __future__ import annotations

from websitebench.viewer.cli import build_parser


def test_viewer_repository_argument_uses_current_product_name() -> None:
    parser = build_parser()
    repo_root = next(
        action
        for action in parser._actions
        if action.dest == "repo_root"
    )

    assert repo_root.help == "WebsiteBench repository root"
