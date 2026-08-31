#!/usr/bin/env python3
"""Generate the exact, site-specific Harbor v2 draft case/task authoring set."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HIDDEN = ROOT / "harbor" / "instances" / "autotrader" / "fixtures" / "hidden"


def observation(identifier: str, selector: dict[str, object]) -> dict[str, object]:
    return {
        "id": identifier,
        "kind": "visible",
        "selector": selector,
        "comparator": {"type": "exact"},
    }


def main() -> None:
    cases: list[dict[str, object]] = []
    tasks: list[dict[str, object]] = []

    t1_routes = [
        "/",
        "/cars",
        "/cars/used",
        "/cars/new",
        "/cars/sell-my-car",
        "/secure/signin",
        "/secure/signin?mode=local",
        "/secure/register",
        "/password-recovery",
        "/vans",
        "/bikes",
        "/motorhomes",
        "/caravans",
        "/trucks",
        "/farm",
        "/plant",
        "/car-reviews",
        "/value-my-car",
        "/help",
        "/external-link?label=Finance%20provider",
    ]
    for index, route in enumerate(t1_routes, 1):
        task_id = f"t1-{index:03d}"
        cases.append(
            {
                "id": f"T1-{index:03d}",
                "tier": "T1",
                "kind": "http",
                "timeout_sec": 60,
                "task_id": task_id,
            }
        )
        tasks.append(
            {
                "id": task_id,
                "timeout_sec": 60,
                "actions": [{"op": "goto", "path": route}],
                "observations": [observation(f"t1-{index:03d}-body", {"css": "body"})],
            }
        )

    makes = ["Ford", "BMW", "Volkswagen"]
    postcodes = ["SW1A 1AA", "M1 1AE", "B1 1TB", "LS1 1UR", "BS1 4ST"]
    task_number = 21
    for level, count in (("L1", 35), ("L2", 50), ("L3", 80)):
        for index in range(1, count + 1):
            make = makes[(index - 1) % len(makes)]
            postcode = postcodes[(index - 1) % len(postcodes)]
            task_id = f"T{task_number:03d}"
            task_number += 1
            actions: list[dict[str, object]] = []

            if level == "L1":
                actions.extend(
                    [
                        {"op": "goto", "path": f"/cars/used?make={make}&price=60000"},
                        {"op": "click", "selector": {"css": "article.card:first-of-type h2 a"}},
                    ]
                )
            else:
                actions.extend(
                    [
                        {"op": "goto", "path": "/"},
                        {"op": "click", "selector": {"role": "button", "name": "Buy"}},
                        {"op": "fill", "selector": {"css": "input[name='postcode']"}, "value": postcode},
                        {"op": "select", "selector": {"css": "select[name='make']"}, "value": make},
                        {"op": "click", "selector": {"role": "button", "name": "More options"}},
                        {"op": "click", "selector": {"text": "Search 449,032 cars"}},
                        {"op": "wait_for", "selector": {"css": "article.card"}, "state": "visible"},
                    ]
                )
                if level == "L3":
                    actions.extend(
                        [
                            {"op": "select", "selector": {"css": "select[name='sort']"}, "value": "price-low"},
                            {"op": "click", "selector": {"role": "button", "name": "Search cars"}},
                            {"op": "wait_for", "selector": {"css": "article.card"}, "state": "visible"},
                            {"op": "click", "selector": {"css": "article.card:first-of-type button[data-save]"}},
                            {"op": "click", "selector": {"css": "article.card:first-of-type button[data-compare]"}},
                        ]
                    )
                actions.append({"op": "click", "selector": {"css": "article.card:first-of-type h2 a"}})

            cases.append(
                {
                    "id": f"T2-{level}-{index:03d}",
                    "tier": "T2",
                    "level": level,
                    "kind": "journey",
                    "timeout_sec": 120,
                    "task_id": task_id,
                }
            )
            tasks.append(
                {
                    "id": task_id,
                    "timeout_sec": 120,
                    "actions": actions,
                    "observations": [
                        observation(f"t2-{level.lower()}-{index:03d}-detail", {"css": ".gallery"}),
                        observation(f"t2-{level.lower()}-{index:03d}-heading", {"css": "h1"}),
                    ],
                }
            )

    api_paths = [
        "/__websitebench/health",
        "/healthz",
        "/api/search",
        "/api/search?make=Ford",
        "/api/search?make=BMW",
        "/api/search?make=Volkswagen",
        "/api/search?price=15000",
        "/api/search?year=2022",
        "/api/search?mileage=30000",
        "/api/search?body=Hatchback",
        "/api/search?body=SUV",
        "/api/search?sort=price-low",
        "/api/search?sort=price-high",
        "/api/search?keyword=Fiesta",
        "/api/search?keyword=no-such-vehicle-zzzz",
    ]
    for index, path in enumerate(api_paths, 1):
        task_id = f"t3-{index:03d}"
        capture = f"t3-response-{index:03d}"
        cases.append(
            {
                "id": f"T3-{index:03d}",
                "tier": "T3",
                "kind": "api",
                "timeout_sec": 60,
                "task_id": task_id,
            }
        )
        tasks.append(
            {
                "id": task_id,
                "timeout_sec": 60,
                "actions": [{"op": "api", "path": path, "method": "GET", "capture_as": capture}],
                "observations": [
                    {
                        "id": f"t3-{index:03d}-status",
                        "kind": "api_status",
                        "capture_as": capture,
                        "comparator": {"type": "exact"},
                    }
                ],
            }
        )

    assert len(cases) == 200
    assert len(tasks) == 200
    manifest = {
        "schema_version": "websitebench.harbor.case-manifest.v1",
        "manifest_id": "autotrader-cases",
        "site_id": "autotrader",
        "status": "draft",
        "dsl_version": "websitebench.harbor.neutral-dsl.v1",
        "cases": cases,
    }
    task_suite = {
        "schema_version": "websitebench.harbor.task-suite.v1",
        "suite_id": "autotrader-tasks",
        "site_id": "autotrader",
        "dsl_version": "websitebench.harbor.playwright-dsl.v1",
        "tasks": tasks,
    }
    HIDDEN.mkdir(parents=True, exist_ok=True)
    (HIDDEN / "case-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (HIDDEN / "task-suite.json").write_text(json.dumps(task_suite, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cases": len(cases), "tasks": len(tasks), "status": "draft"}))


if __name__ == "__main__":
    main()
