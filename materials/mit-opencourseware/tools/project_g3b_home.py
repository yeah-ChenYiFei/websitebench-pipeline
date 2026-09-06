"""Project distinct homepage cards from the hash-bound G3-B raw SSR body."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import tempfile
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit


SITE = Path(__file__).resolve().parents[1]
CLONE = SITE / "clone"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump_atomic(path: Path, value: object, *, compact: bool = False) -> None:
    payload = (json.dumps(value, ensure_ascii=False, separators=(",", ":")) if compact else json.dumps(value, ensure_ascii=False, indent=2)) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(name, path)


def normalized(parts: list[str]) -> str:
    return " ".join(" ".join(parts).split())


class Cards(HTMLParser):
    FIELD_CLASSES = {
        "course-level": "level",
        "course-card-title": "title",
        "course-card-instructors": "instructors",
        "course-card-topics": "topics",
        "name": "name",
        "occupation": "occupation",
        "occupation-location": "location",
        "story-body": "story_body",
    }

    def __init__(self, kind: str) -> None:
        super().__init__(convert_charrefs=True)
        self.kind = kind
        self.active = False
        self.depth = 0
        self.stack: list[tuple[str, str | None]] = []
        self.current: dict[str, object] = {}
        self.rows: list[dict[str, object]] = []

    def is_root(self, tag: str, attrs: dict[str, str]) -> bool:
        classes = set(attrs.get("class", "").split())
        return (
            tag == "div" and "course-card" in classes
            if self.kind == "course"
            else tag == "a" and "testimonial-link" in classes
        )

    def field(self, attrs: dict[str, str], inherited: str | None) -> str | None:
        classes = set(attrs.get("class", "").split())
        for marker, field in self.FIELD_CLASSES.items():
            if marker in classes:
                return field
        return inherited

    def begin(self, tag: str, attrs: dict[str, str]) -> None:
        self.active = True
        self.depth = 1
        self.current = {"fields": defaultdict(list), "links": [], "image_source_url": "", "image_alt": ""}
        self.stack = [(tag, None)]
        if tag == "a" and attrs.get("href"):
            self.current["root_href"] = urljoin("https://ocw.mit.edu/", attrs["href"])

    def handle_starttag(self, tag: str, attrs_list) -> None:
        attrs = {key: value or "" for key, value in attrs_list}
        if not self.active:
            if self.is_root(tag, attrs):
                self.begin(tag, attrs)
            return
        inherited = self.stack[-1][1] if self.stack else None
        field = self.field(attrs, inherited)
        if tag == "a" and attrs.get("href"):
            absolute = urljoin("https://ocw.mit.edu/", html.unescape(attrs["href"]))
            self.current["links"].append({"field": field, "url": absolute})
        if tag == "img" and attrs.get("src") and not self.current["image_source_url"]:
            self.current["image_source_url"] = urljoin("https://ocw.mit.edu/", html.unescape(attrs["src"]))
            self.current["image_alt"] = attrs.get("alt", "")
        if tag not in VOID:
            self.depth += 1
            self.stack.append((tag, field))

    def handle_endtag(self, tag: str) -> None:
        if not self.active or tag in VOID:
            return
        if self.stack:
            self.stack.pop()
        self.depth -= 1
        if self.depth == 0:
            fields = {key: normalized(value) for key, value in self.current["fields"].items()}
            self.current["fields"] = fields
            self.rows.append(dict(self.current))
            self.active = False
            self.current = {}
            self.stack = []

    def handle_data(self, data: str) -> None:
        if self.active and self.stack and self.stack[-1][1] and data.strip():
            self.current["fields"][self.stack[-1][1]].append(data)


class Promotions(HTMLParser):
    """Project the four cards inside the source promo carousel in source order."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.active = False
        self.depth = 0
        self.field: str | None = None
        self.fields: defaultdict[str, list[str]] = defaultdict(list)
        self.current: dict[str, str] = {}
        self.rows: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs_list) -> None:
        attrs = {key: value or "" for key, value in attrs_list}
        classes = set(attrs.get("class", "").split())
        if not self.active:
            if tag == "div" and "carousel-item" in classes:
                self.active = True
                self.depth = 1
                self.field = None
                self.fields = defaultdict(list)
                self.current = {}
            return
        if tag not in VOID:
            self.depth += 1
        if tag == "h2":
            self.field = "title"
        elif tag == "h3":
            self.field = "subtitle"
        elif tag == "img" and attrs.get("src") and "image_source_url" not in self.current:
            self.current["image_source_url"] = urljoin("https://ocw.mit.edu/", html.unescape(attrs["src"]))
            self.current["image_alt"] = attrs.get("alt", "")
        elif tag == "a" and attrs.get("href") and attrs["href"].startswith(("http://", "https://")):
            self.current["source_url"] = html.unescape(attrs["href"])
            self.field = "cta_text"

    def handle_endtag(self, tag: str) -> None:
        if not self.active or tag in VOID:
            return
        if tag in {"h2", "h3", "a"}:
            self.field = None
        self.depth -= 1
        if self.depth == 0:
            row = {key: normalized(value) for key, value in self.fields.items()}
            row.update(self.current)
            self.rows.append(row)
            self.active = False
            self.field = None

    def handle_data(self, data: str) -> None:
        if self.active and self.field and data.strip():
            self.fields[self.field].append(data)


def local_route(url: str, pages: dict[str, object]) -> str | None:
    path = unquote(urlsplit(url).path)
    candidates = (path, path + "/" if not path.endswith("/") else path, path.rstrip("/") or "/")
    return next((candidate for candidate in candidates if candidate in pages), None)


def execute() -> dict[str, object]:
    report_path = SITE / "source-current" / "g3b-home-content-projection-v2" / "report.json"
    if report_path.exists():
        raise SystemExit(f"create-only projection already exists: {report_path}")
    data_path = CLONE / "site-data.json"
    index = load(CLONE / "content-index.json")
    data = load(data_path)
    home = index["routes"]["/"]
    raw_path = SITE / home["raw_path"]
    raw = raw_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == home["raw_sha256"]
    text = raw.decode("utf-8", errors="replace")

    course_parser = Cards("course")
    course_parser.feed(text)
    courses: dict[str, dict[str, object]] = {}
    for row in course_parser.rows:
        course_links = [local_route(link["url"], data["pages"]) for link in row["links"]]
        path = next((path for path in course_links if path and data["pages"][path]["family"] == "course-overview"), None)
        if not path or path in courses:
            continue
        fields = row["fields"]
        courses[path] = {
            "path": path, "title": fields.get("title", ""), "level": fields.get("level", ""),
            "instructors": fields.get("instructors", ""), "topics": fields.get("topics", ""),
            "image_source_url": row["image_source_url"], "image_alt": row["image_alt"],
            "source_text_sha256": hashlib.sha256("\n".join(fields.values()).encode()).hexdigest(),
        }

    # At the frozen 1440px viewport the xl carousel is authoritative.  Each
    # source carousel item contains three cards; retaining this order makes the
    # default and next states reproducible instead of sorting route slugs.
    xl_start = text.index('<div id="testimonial-carousel-xl"')
    xl_end = text.index('<div id="testimonial-carousel-xs-sm"', xl_start)
    story_parser = Cards("story")
    story_parser.feed(text[xl_start:xl_end])
    stories: dict[str, dict[str, object]] = {}
    story_order: list[str] = []
    for row in story_parser.rows:
        path = local_route(str(row.get("root_href", "")), data["pages"])
        if not path or data["pages"][path]["family"] != "story-detail" or path in stories:
            continue
        fields = row["fields"]
        full = str(fields.get("story_body", ""))
        teaser = re.split(r"\s+By\s+[A-Z]", full, maxsplit=1)[0].strip()
        if not teaser:
            teaser = full.split(".", 1)[0].strip() + "."
        stories[path] = {
            "path": path, "name": fields.get("name", ""),
            "occupation": fields.get("occupation", ""), "location": fields.get("location", ""),
            "teaser": teaser, "full_story_text_sha256": hashlib.sha256(full.encode()).hexdigest(),
            "image_source_url": row["image_source_url"], "image_alt": row["image_alt"],
        }
        story_order.append(path)

    required_courses = {
        path for path, row in data["pages"].items()
        if row["family"] == "course-overview" and (str(row["page_id"]).startswith("featured-") or str(row["page_id"]).startswith("new-"))
    }
    required_stories = {path for path, row in data["pages"].items() if row["family"] == "story-detail"}
    assert len(required_courses) == 16
    # Home has sixteen card identities; G1 separately proved fifteen complete
    # course archives (the Election Resource Hub card has no course archive).
    assert required_courses <= set(courses), sorted(required_courses - set(courses))
    assert len(required_stories) == 13 and required_stories <= set(stories), sorted(required_stories - set(stories))

    promo_start = text.index('<div id="promo-carousel"')
    promo_end = text.index('<div class="home-page-content"', promo_start)
    promo_parser = Promotions()
    promo_parser.feed(text[promo_start:promo_end])
    promotions = promo_parser.rows
    assert [row["title"] for row in promotions] == [
        'MIT Learn: "a whole new front door to the Institute"',
        "MIT OpenCourseWare To Go",
        "Chalk Radio: a podcast about inspired teaching at MIT",
        "Come invent with us!",
    ]
    assert all(row.get("subtitle") and row.get("source_url") and row.get("image_source_url") and row.get("cta_text") for row in promotions)
    assert all(row["image_source_url"] in data["asset_url_map"] for row in promotions)
    assert story_order[:6] == [
        "/stories/adrian-pastor/", "/stories/john-della-costa/", "/stories/freesia-gaul/",
        "/stories/omar-alshehri/", "/stories/gustavo-barboza/", "/stories/sok-danica/",
    ]

    projection = {
        "schema_version": "mit-ocw.g3b-home-content-projection.v2",
        "capture_id": data["capture_id"], "created_at": "2026-09-03T10:00:00Z",
        "source_raw_path": home["raw_path"], "source_raw_sha256": home["raw_sha256"],
        "method": "stdlib-htmlparser course-card/testimonial-link/promo-carousel field projection-v2; xl story order at frozen 1440px viewport",
        "closure": {"status": "closed", "course_card_instances": 16, "distinct_course_identities": 16, "complete_course_archives": 15, "story_cards": 13, "promotions": 4},
        "courses": {path: courses[path] for path in sorted(required_courses)},
        "stories": {path: stories[path] for path in sorted(required_stories)},
        "story_order": story_order,
        "story_batches": {"default": story_order[:3], "carousel-second-batches": story_order[3:6]},
        "promotions": promotions,
        "promotion_states": {"default": 0, "carousel-second-batches": 1},
        "generic_substitution": False,
    }
    dump_atomic(report_path, projection)
    data["g3b_home_content"] = {
        "report": report_path.relative_to(SITE).as_posix(),
        "courses": projection["courses"], "stories": projection["stories"],
        "story_order": projection["story_order"], "story_batches": projection["story_batches"],
        "promotions": promotions, "promotion_states": projection["promotion_states"], "status": "closed",
    }
    dump_atomic(data_path, data, compact=True)
    return {"status": "closed", **projection["closure"], "report": report_path.relative_to(SITE).as_posix()}


def main() -> None:
    argparse.ArgumentParser().parse_args()
    print(json.dumps(execute(), indent=2))


if __name__ == "__main__":
    main()
