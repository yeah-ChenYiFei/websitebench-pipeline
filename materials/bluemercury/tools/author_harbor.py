#!/usr/bin/env python3
"""Author Bluemercury's deterministic draft Harbor suites from local facts."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
INSTANCE = REPO / "harbor" / "instances" / "bluemercury"
HIDDEN = INSTANCE / "fixtures" / "hidden"
PRODUCTS_PATH = REPO / "materials" / "bluemercury" / "clone" / "static" / "products.json"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def id_slug(value: str, limit: int = 45) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized[:limit].rstrip("-") or "product"


def goto_task(task_id: str, route: str, selector: str, observation_id: str) -> dict:
    return {
        "id": task_id,
        "timeout_sec": 45,
        "actions": [{"op": "goto", "path": route}],
        "observations": [{
            "id": observation_id,
            "kind": "text",
            "selector": {"css": selector},
            "comparator": {"type": "normalized_exact"},
        }],
    }


def product_task(task_id: str, product: dict, index: int) -> dict:
    return {
        "id": task_id,
        "timeout_sec": 60,
        "actions": [{"op": "goto", "path": f"/products/{product['handle']}"}],
        "observations": [
            {
                "id": f"product-title-{index:03d}",
                "kind": "text",
                "selector": {"css": ".product-detail h1"},
                "comparator": {"type": "normalized_exact"},
            },
            {
                "id": f"product-price-{index:03d}",
                "kind": "text",
                "selector": {"css": ".product-detail .price"},
                "comparator": {"type": "normalized_exact"},
            },
        ],
    }


def cart_task(task_id: str, product: dict, index: int) -> dict:
    quantity = 1 + (index % 3)
    return {
        "id": task_id,
        "timeout_sec": 90,
        "actions": [
            {"op": "goto", "path": f"/products/{product['handle']}"},
            {"op": "fill", "selector": {"css": "#quantity"}, "value": str(quantity)},
            {"op": "click", "selector": {"css": "#add-to-bag"}},
            {"op": "goto", "path": "/cart"},
        ],
        "observations": [
            {
                "id": f"bag-product-{index:03d}",
                "kind": "text",
                "selector": {"css": ".cart-row h2"},
                "comparator": {"type": "normalized_exact"},
            },
            {
                "id": f"bag-count-{index:03d}",
                "kind": "text",
                "selector": {"css": ".bag-count"},
                "comparator": {"type": "normalized_exact"},
            },
        ],
    }


def checkout_task(task_id: str, product: dict, index: int, scenario: str) -> dict:
    actions = [
        {"op": "goto", "path": f"/products/{product['handle']}"},
        {"op": "fill", "selector": {"css": "#quantity"}, "value": "1"},
        {"op": "click", "selector": {"css": "#add-to-bag"}},
        {"op": "goto", "path": "/cart"},
        {"op": "click", "selector": {"css": "#checkout-button"}},
        {"op": "fill", "selector": {"css": "#email"}, "value": f"shopper{index:03d}@example.test"},
        {"op": "fill", "selector": {"css": "#first_name"}, "value": "Jamie"},
        {"op": "fill", "selector": {"css": "#last_name"}, "value": f"Local{index:03d}"},
        {"op": "fill", "selector": {"css": "#address"}, "value": f"{100 + index} Sandbox Avenue"},
        {"op": "fill", "selector": {"css": "#city"}, "value": "Testville"},
        {"op": "fill", "selector": {"css": "#state"}, "value": "NY"},
        {"op": "fill", "selector": {"css": "#postal_code"}, "value": "10001"},
        {"op": "select", "selector": {"css": "#scenario"}, "value": scenario},
        {"op": "click", "selector": {"css": "#place-order"}},
    ]
    if scenario == "sandbox-approved":
        observations = [
            {
                "id": f"approved-heading-{index:03d}",
                "kind": "text",
                "selector": {"css": ".confirmation h1"},
                "comparator": {"type": "normalized_exact"},
            },
            {
                "id": f"approved-url-{index:03d}",
                "kind": "url",
                "comparator": {"type": "regex", "pattern": ".*/orders/BM-[0-9]+$"},
            },
        ]
    else:
        outcome = "declined" if scenario == "sandbox-declined" else "retryable"
        observations = [
            {
                "id": f"{outcome}-alert-{index:03d}",
                "kind": "text",
                "selector": {"css": "[role='alert']"},
                "comparator": {"type": "regex", "pattern": f".*{outcome}.*"},
            },
            {
                "id": f"{outcome}-checkout-{index:03d}",
                "kind": "visible",
                "selector": {"css": "#checkout-form"},
                "comparator": {"type": "exact"},
            },
        ]
    return {"id": task_id, "timeout_sec": 120, "actions": actions, "observations": observations}


RUNNER_ASSERTIONS = [
    "assert (root / 'executable').is_file()",
    "assert (root / 'clone' / 'app.py').is_file()",
    "assert (root / 'backend' / 'runtime.json').is_file()",
    "assert json.loads((root / 'backend' / 'runtime.json').read_text())['site']['id'] == 'bluemercury'",
    "assert json.loads((root / 'backend' / 'runtime.json').read_text())['payments']['stripe_test'] is None",
    "assert [x['id'] for x in json.loads((root / 'backend' / 'runtime.json').read_text())['payments']['local_sandbox']['scenarios']] == ['sandbox-approved', 'sandbox-declined', 'sandbox-retry']",
    "assert len(json.loads((root / 'clone' / 'static' / 'products.json').read_text())['products']) == 250",
    "products=json.loads((root / 'clone' / 'static' / 'products.json').read_text())['products']; assert len({x['handle'] for x in products}) == 250",
    "assert len(json.loads((root / 'clone' / 'static' / 'catalog-image-map.json').read_text())) == 249",
    "text='\\n'.join((root / 'clone' / p).read_text(errors='ignore') for p in ['app.py','static/site.css']); assert 'https://' not in text and 'http://' not in text",
    "assert json.loads((root / 'backend' / 'runtime.json').read_text())['database']['filename'] == 'bluemercury.sqlite3'",
    "assert (root / 'clone' / 'backend' / 'site_backend_integration.py').is_file()",
    "assert '/__websitebench/health' in (root / 'clone' / 'app.py').read_text()",
    "assert '@media' in (root / 'clone' / 'static' / 'site.css').read_text()",
    "assert (root / 'compile.sh').is_file() and os.access(root / 'compile.sh', os.X_OK)",
]


def author_runners() -> list[dict]:
    runner_dir = HIDDEN / "runners"
    runner_dir.mkdir(parents=True, exist_ok=True)
    checks = []
    for index, assertion in enumerate(RUNNER_ASSERTIONS, start=1):
        identifier = f"bluemercury-static-{index:03d}"
        path = runner_dir / f"check-{index:03d}.py"
        source = (
            "#!/usr/bin/python3\n"
            "import json\nimport os\nfrom pathlib import Path\n"
            "root = Path(os.environ['WEBSITEBENCH_CANDIDATE_ROOT']).resolve()\n"
            f"{assertion}\n"
        )
        path.write_text(source, encoding="utf-8")
        path.chmod(0o755)
        checks.append({"id": identifier, "kind": "static", "runner": f"runners/check-{index:03d}.py", "timeout_sec": 30})
    return checks


def main() -> None:
    payload = json.loads(PRODUCTS_PATH.read_text(encoding="utf-8"))
    products = payload.get("products", payload)
    eligible = [item for item in products if item.get("variants") and item["variants"][0].get("available")]
    if len(products) != 250 or len(eligible) < 165:
        raise SystemExit("catalog does not satisfy the frozen Harbor authoring contract")

    tasks: list[dict] = []
    cases: list[dict] = []
    direct_routes = [
        ("home", "/", ".hero h1"),
        ("skincare", "/collections/skin-care", ".catalog-head h1"),
        ("new-arrivals", "/collections/new-arrivals", ".catalog-head h1"),
        ("bestsellers", "/collections/best-sellers", ".catalog-head h1"),
        ("makeup", "/collections/makeup", ".catalog-head h1"),
        ("hair", "/collections/hair", ".catalog-head h1"),
        ("bath-body", "/collections/bath-body", ".catalog-head h1"),
        ("fragrance", "/collections/fragrances", ".catalog-head h1"),
        ("sun", "/collections/suncare", ".catalog-head h1"),
        ("gifts", "/collections/gifts", ".catalog-head h1"),
        ("sale", "/collections/sale", ".catalog-head h1"),
        ("search-serum", "/search?q=serum&type=product", "h1"),
        ("search-cleanser", "/search?q=cleanser&type=product", "h1"),
        ("search-zero", "/search?q=zzzz-no-match&type=product", "h1"),
        ("empty-cart", "/cart", "h1"),
        ("rewards", "/pages/bluerewards", "h1"),
        ("brands", "/pages/brands", "h1"),
        ("shipping", "/pages/shipping-returns", "h1"),
        ("account-boundary", "/account/login", "h1"),
        ("not-found", "/offline-missing-page", "h1"),
    ]
    for index, (suffix, route, selector) in enumerate(direct_routes, start=1):
        task_id = f"bm-t1-{index:03d}-{suffix}"
        tasks.append(goto_task(task_id, route, selector, f"t1-{index:03d}-heading"))
        cases.append({"id": f"bm-case-t1-{index:03d}", "tier": "T1", "kind": "http", "timeout_sec": 60, "task_id": task_id})

    cursor = 0
    for index in range(1, 36):
        product = eligible[cursor]
        cursor += 1
        task_id = f"bm-t2-l1-{index:03d}-{id_slug(product['handle'])}"
        tasks.append(product_task(task_id, product, index))
        cases.append({"id": f"bm-case-t2-l1-{index:03d}", "tier": "T2", "level": "L1", "kind": "journey", "timeout_sec": 90, "task_id": task_id})

    for index in range(1, 51):
        product = eligible[cursor]
        cursor += 1
        task_id = f"bm-t2-l2-{index:03d}-{id_slug(product['handle'])}"
        tasks.append(cart_task(task_id, product, index))
        cases.append({"id": f"bm-case-t2-l2-{index:03d}", "tier": "T2", "level": "L2", "kind": "journey", "timeout_sec": 120, "task_id": task_id})

    scenarios = ["sandbox-approved", "sandbox-declined", "sandbox-retry"]
    for index in range(1, 81):
        product = eligible[cursor]
        cursor += 1
        scenario = scenarios[(index - 1) % len(scenarios)]
        task_id = f"bm-t2-l3-{index:03d}-{id_slug(product['handle'])}"
        tasks.append(checkout_task(task_id, product, index, scenario))
        cases.append({"id": f"bm-case-t2-l3-{index:03d}", "tier": "T2", "level": "L3", "kind": "journey", "timeout_sec": 180, "task_id": task_id})

    checks = author_runners()
    for index, check in enumerate(checks, start=1):
        cases.append({"id": f"bm-case-t3-{index:03d}", "tier": "T3", "kind": "cicd", "timeout_sec": 45, "cicd_check_id": check["id"]})

    write_json(HIDDEN / "task-suite.json", {
        "dsl_version": "websitebench.harbor.playwright-dsl.v1",
        "schema_version": "websitebench.harbor.task-suite.v1",
        "site_id": "bluemercury",
        "suite_id": "bluemercury-tasks",
        "tasks": tasks,
    })
    write_json(HIDDEN / "cicd-suite.json", {
        "checks": checks,
        "schema_version": "websitebench.harbor.cicd-suite.v1",
        "site_id": "bluemercury",
        "suite_id": "bluemercury-cicd",
    })
    write_json(HIDDEN / "case-manifest.json", {
        "cases": cases,
        "dsl_version": "websitebench.harbor.neutral-dsl.v1",
        "manifest_id": "bluemercury-cases",
        "schema_version": "websitebench.harbor.case-manifest.v1",
        "site_id": "bluemercury",
        "status": "draft",
    })
    print(json.dumps({"products": len(products), "eligible": len(eligible), "tasks": len(tasks), "checks": len(checks), "cases": len(cases), "status": "draft"}, sort_keys=True))


if __name__ == "__main__":
    main()
