"""Generate deterministic synthetic seed photos (SVG) for the craigslist clone.

All images are locally authored, license-clean, deterministic placeholders
matching the seeded posting catalog; no remote or third-party asset is used.
"""

from pathlib import Path

OUT = Path(__file__).resolve().parent.parent.parent / "clone" / "static" / "assets" / "seed-photos"
OUT.mkdir(parents=True, exist_ok=True)

PALETTES = {
    "apt": ["#f2d8b3", "#c9a87c", "#8a6f4d"],
    "house": ["#b8c9a8", "#7d9b76", "#4f6d4a"],
    "room": ["#d8c7e0", "#a98bb5", "#6f4f7a"],
    "condo": ["#bcd4e0", "#7fa3b5", "#4a6b7d"],
    "bike": ["#e0c9b0", "#8a5f3c", "#3c3c3c"],
    "table": ["#d6b98a", "#8a6f4d", "#5a4630"],
    "laptop": ["#c0c0c0", "#6b6b6b", "#2e2e2e"],
    "cottage": ["#a8c8d8", "#6f9aa8", "#3f5f6a"],
}


def scene(kind: str, name: str, palette: list[str], label: str) -> str:
    bg, mid, fg = palette
    if kind == "room":
        body = f"""
  <rect x="0" y="0" width="640" height="480" fill="{bg}"/>
  <rect x="40" y="40" width="560" height="400" fill="#ffffff" stroke="{fg}" stroke-width="4"/>
  <rect x="90" y="120" width="200" height="90" fill="{mid}" stroke="{fg}" stroke-width="3"/>
  <rect x="110" y="260" width="180" height="140" fill="{mid}" stroke="{fg}" stroke-width="3"/>
  <circle cx="330" cy="150" r="60" fill="{mid}" stroke="{fg}" stroke-width="3"/>
  <rect x="420" y="80" width="120" height="140" fill="{mid}" stroke="{fg}" stroke-width="3"/>
  <rect x="420" y="80" width="60" height="140" fill="#ffffff" opacity="0.35"/>
"""
    elif kind == "house":
        body = f"""
  <rect x="0" y="0" width="640" height="480" fill="#dce8ef"/>
  <rect x="0" y="330" width="640" height="150" fill="{mid}"/>
  <polygon points="120,220 320,80 520,220" fill="{fg}"/>
  <rect x="150" y="220" width="340" height="180" fill="{bg}" stroke="{fg}" stroke-width="4"/>
  <rect x="290" y="300" width="70" height="100" fill="{fg}"/>
  <rect x="180" y="250" width="80" height="60" fill="#bfe0ff" stroke="{fg}" stroke-width="3"/>
  <rect x="380" y="250" width="80" height="60" fill="#bfe0ff" stroke="{fg}" stroke-width="3"/>
  <circle cx="100" cy="120" r="40" fill="#fff3b0"/>
"""
    elif kind == "condo":
        body = f"""
  <rect x="0" y="0" width="640" height="480" fill="#e8eef2"/>
  <rect x="120" y="40" width="400" height="420" fill="{bg}" stroke="{fg}" stroke-width="4"/>
  <rect x="150" y="80" width="120" height="90" fill="#bfe0ff" stroke="{fg}" stroke-width="3"/>
  <rect x="300" y="80" width="120" height="90" fill="#bfe0ff" stroke="{fg}" stroke-width="3"/>
  <rect x="150" y="200" width="120" height="90" fill="#bfe0ff" stroke="{fg}" stroke-width="3"/>
  <rect x="300" y="200" width="120" height="90" fill="#bfe0ff" stroke="{fg}" stroke-width="3"/>
  <rect x="150" y="320" width="120" height="90" fill="#bfe0ff" stroke="{fg}" stroke-width="3"/>
  <rect x="300" y="320" width="120" height="90" fill="#bfe0ff" stroke="{fg}" stroke-width="3"/>
"""
    elif kind == "bike":
        body = f"""
  <rect x="0" y="0" width="640" height="480" fill="#eef2ee"/>
  <circle cx="220" cy="300" r="90" fill="none" stroke="{fg}" stroke-width="12"/>
  <circle cx="460" cy="300" r="90" fill="none" stroke="{fg}" stroke-width="12"/>
  <line x1="220" y1="300" x2="340" y2="220" stroke="{mid}" stroke-width="10"/>
  <line x1="340" y1="220" x2="460" y2="300" stroke="{mid}" stroke-width="10"/>
  <line x1="340" y1="220" x2="300" y2="360" stroke="{mid}" stroke-width="10"/>
  <line x1="460" y1="300" x2="300" y2="360" stroke="{fg}" stroke-width="8"/>
  <rect x="330" y="180" width="24" height="40" fill="{fg}" rx="4"/>
"""
    elif kind == "table":
        body = f"""
  <rect x="0" y="0" width="640" height="480" fill="#f4efe6"/>
  <rect x="90" y="220" width="460" height="30" fill="{mid}" stroke="{fg}" stroke-width="4"/>
  <rect x="130" y="250" width="16" height="150" fill="{fg}"/>
  <rect x="500" y="250" width="16" height="150" fill="{fg}"/>
  <rect x="360" y="150" width="70" height="70" fill="{bg}" stroke="{fg}" stroke-width="4" rx="6"/>
  <rect x="190" y="150" width="70" height="70" fill="{bg}" stroke="{fg}" stroke-width="4" rx="6"/>
"""
    elif kind == "laptop":
        body = """
  <rect x="0" y="0" width="640" height="480" fill="#ececec"/>
  <rect x="150" y="120" width="340" height="230" fill="#2e2e2e" rx="12"/>
  <rect x="170" y="140" width="300" height="190" fill="#5f9ea0" rx="4"/>
  <rect x="120" y="350" width="400" height="22" fill="#6b6b6b" rx="8"/>
"""
    elif kind == "cottage":
        body = f"""
  <rect x="0" y="0" width="640" height="480" fill="#cfe3ee"/>
  <rect x="0" y="300" width="640" height="180" fill="#8fb8c8"/>
  <polygon points="180,180 340,90 500,180" fill="{fg}"/>
  <rect x="200" y="180" width="280" height="150" fill="{bg}" stroke="{fg}" stroke-width="4"/>
  <rect x="320" y="240" width="50" height="90" fill="{fg}"/>
  <rect x="225" y="210" width="70" height="50" fill="#bfe0ff" stroke="{fg}" stroke-width="3"/>
  <circle cx="120" cy="110" r="45" fill="#fff3b0"/>
  <path d="M0 360 Q 80 320 160 360 T 320 360 T 480 360 T 640 360" fill="none" stroke="#5d8494" stroke-width="3"/>
"""
    else:
        body = f"""
  <rect x="0" y="0" width="640" height="480" fill="{bg}"/>
  <rect x="40" y="40" width="560" height="400" fill="{mid}" stroke="{fg}" stroke-width="4" rx="8"/>
  <circle cx="320" cy="240" r="90" fill="{fg}" opacity="0.6"/>
"""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480" viewBox="0 0 640 480" role="img" aria-label="{label}">
  <title>{label}</title>
{body}
  <text x="16" y="470" font-family="Helvetica, Arial, sans-serif" font-size="13" fill="#666">{label}</text>
</svg>
"""


def main() -> None:
    specs = [
        ("apt-annex-1", "apt", "living room in the annex"),
        ("apt-annex-2", "apt", "annex bedroom"),
        ("apt-annex-3", "apt", "annex kitchen"),
        ("apt-kensington-1", "room", "kensington studio"),
        ("apt-yorkville-1", "condo", "yorkville condo"),
        ("apt-yorkville-2", "condo", "yorkville building"),
        ("apt-leslieville-1", "room", "leslieville bedroom"),
        ("apt-leslieville-2", "apt", "leslieville living room"),
        ("apt-leslieville-3", "apt", "leslieville kitchen"),
        ("apt-corktown-1", "room", "corktown bedroom"),
        ("apt-corktown-2", "apt", "corktown apartment"),
        ("apt-cityplace-1", "condo", "cityplace condo"),
        ("apt-cityplace-2", "condo", "cityplace view"),
        ("house-roncy-1", "house", "roncesvalles house"),
        ("house-roncy-2", "house", "roncesvalles backyard"),
        ("apt-northyork-1", "room", "north york basement"),
        ("apt-liberty-1", "condo", "liberty village unit"),
        ("apt-liberty-2", "condo", "liberty village terrace"),
        ("apt-stlawrence-1", "room", "st lawrence studio"),
        ("apt-beaches-1", "apt", "the beaches apartment"),
        ("room-kensington-1", "room", "kensington room"),
        ("room-annex-1", "room", "annex room"),
        ("room-parkdale-1", "room", "parkdale room"),
        ("condo-ye-1", "condo", "yonge eglinton condo"),
        ("house-eastyork-1", "house", "east york semi"),
        ("cottage-muskoka-1", "cottage", "muskoka cottage"),
        ("bike-1", "bike", "vintage road bike"),
        ("table-1", "table", "mid-century dining set"),
        ("laptop-1", "laptop", "macbook pro"),
    ]
    for name, kind, label in specs:
        palette = PALETTES.get(kind, PALETTES["apt"])
        (OUT / f"{name}.svg").write_text(scene(kind, name, palette, label), encoding="utf-8")
    print(f"wrote {len(specs)} seed photos to {OUT}")


if __name__ == "__main__":
    main()
