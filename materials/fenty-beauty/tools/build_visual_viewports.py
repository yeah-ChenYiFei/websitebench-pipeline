"""Create deterministic top-viewport rasters from retained full-page evidence."""

from __future__ import annotations

from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "materials/fenty-beauty/artifacts/offline-clone/visual-compare/viewports"

PAIRS = {
    "home-desktop": (
        "materials/fenty-beauty/source-current/2026-08-19.fenty-stability-r1/rows/home-desktop-frame-1-4686493e3d/screenshot.png",
        "materials/fenty-beauty/artifacts/offline-clone/browser/candidate-visual-desktop/fenty-candidate-visual-desktop-home-desktop.png",
        (1440, 900),
    ),
    "home-mobile": (
        "materials/fenty-beauty/source-current/2026-08-19.fenty-stability-r1/rows/home-mobile-frame-1-5e413fd5a7/screenshot.png",
        "materials/fenty-beauty/artifacts/offline-clone/browser/candidate-visual-mobile/fenty-candidate-visual-mobile-home-mobile.png",
        (390, 844),
    ),
    "catalog-desktop": (
        "materials/fenty-beauty/source-current/2026-08-19.fenty-stability-r1/rows/catalog-desktop-frame-1-eabb383fa7/screenshot.png",
        "materials/fenty-beauty/artifacts/offline-clone/browser/candidate-visual-desktop/fenty-candidate-visual-desktop-catalog-desktop.png",
        (1440, 900),
    ),
    "foundation-desktop": (
        "materials/fenty-beauty/source-current/2026-08-19.fenty-stability-r1/rows/foundation-desktop-frame-1-0be58fcc49/screenshot.png",
        "materials/fenty-beauty/artifacts/offline-clone/browser/candidate-visual-desktop/fenty-candidate-visual-desktop-foundation-desktop.png",
        (1440, 900),
    ),
    "powder-desktop": (
        "materials/fenty-beauty/source-current/2026-08-19.fenty-stability-r1/rows/powder-desktop-frame-1-08bcb314e9/screenshot.png",
        "materials/fenty-beauty/artifacts/offline-clone/browser/candidate-visual-desktop/fenty-candidate-visual-desktop-powder-desktop.png",
        (1440, 900),
    ),
    "signin-desktop": (
        "materials/fenty-beauty/source-current/2026-08-19.fenty-stability-r1/rows/signin-desktop-frame-1-50c6ffe55c/screenshot.png",
        "materials/fenty-beauty/artifacts/offline-clone/browser/candidate-visual-desktop/fenty-candidate-visual-desktop-signin-desktop.png",
        (1440, 900),
    ),
    "help-desktop": (
        "materials/fenty-beauty/source-current/2026-08-19.fenty-stability-r1/rows/help-desktop-frame-1-dfc5b50c00/screenshot.png",
        "materials/fenty-beauty/artifacts/offline-clone/browser/candidate-visual-desktop/fenty-candidate-visual-desktop-help-desktop.png",
        (1440, 900),
    ),
    "not-found-desktop": (
        "materials/fenty-beauty/source-current/2026-08-19.fenty-stability-r1/rows/not-found-desktop-frame-1-ad85547c45/screenshot.png",
        "materials/fenty-beauty/artifacts/offline-clone/browser/candidate-visual-desktop/fenty-candidate-visual-desktop-not-found-desktop.png",
        (1440, 900),
    ),
}


def main() -> None:
    for checkpoint, (source_path, candidate_path, viewport) in PAIRS.items():
        width, height = viewport
        for side, relative in (("source", source_path), ("candidate", candidate_path)):
            source = ROOT / relative
            destination = OUT / side / f"{checkpoint}.png"
            destination.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(source) as image:
                if image.width < width or image.height < height:
                    raise RuntimeError(f"{relative} is smaller than {width}x{height}")
                image.crop((0, 0, width, height)).save(destination, format="PNG", optimize=False)
    print(f"wrote {len(PAIRS) * 2} viewport rasters to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
