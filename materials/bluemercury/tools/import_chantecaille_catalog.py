#!/usr/bin/env python3
"""Normalize the captured Chantecaille collection and localize primary images."""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import shutil
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-json", type=Path, required=True)
    parser.add_argument("--source-assets", type=Path, required=True)
    parser.add_argument("--runtime-assets", type=Path, required=True)
    parser.add_argument("--products-out", type=Path, required=True)
    parser.add_argument("--map-out", type=Path, required=True)
    parser.add_argument("--provenance-out", type=Path, required=True)
    parser.add_argument("--asset-prefix", default="chantecaille")
    parser.add_argument("--source-url", default="https://bluemercury.com/collections/chantecaille/products.json?limit=250")
    parser.add_argument("--workers", type=int, default=4)
    return parser.parse_args()


def safe_filename(index: int, handle: str, source_url: str, prefix: str) -> str:
    suffix = Path(urllib.parse.urlparse(source_url).path).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = mimetypes.guess_extension("image/jpeg") or ".jpg"
    slug = re.sub(r"[^a-z0-9-]+", "-", handle.casefold()).strip("-")[:82]
    safe_prefix = re.sub(r"[^a-z0-9-]+", "-", prefix.casefold()).strip("-") or "catalog"
    return f"{safe_prefix}-{index:03d}-{slug}{suffix}"


def resized_url(source_url: str) -> str:
    parsed = urllib.parse.urlsplit(source_url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(key, value) for key, value in query if key != "width"]
    query.append(("width", "600"))
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment)
    )


def normalize_product(product: dict) -> dict:
    images = [image.get("src") for image in product.get("images", []) if image.get("src")]
    variants = [
        {
            "id": variant["id"],
            "title": variant.get("title") or "Default Title",
            "sku": variant.get("sku") or "",
            "available": bool(variant.get("available")),
            "price": str(variant.get("price") or "0.00"),
            "compare_at_price": variant.get("compare_at_price"),
        }
        for variant in product.get("variants", [])
    ]
    return {
        "id": product["id"],
        "title": product["title"],
        "handle": product["handle"],
        "vendor": product.get("vendor") or "Chantecaille",
        "product_type": product.get("product_type") or "Beauty Product",
        "published_at": product.get("published_at"),
        "tags": list(product.get("tags") or []),
        "url": f"https://bluemercury.com/products/{product['handle']}",
        "variants": variants,
        "images": images,
    }


def download_one(
    index: int,
    product: dict,
    source_assets: Path,
    runtime_assets: Path,
    asset_prefix: str,
) -> dict:
    images = product.get("images") or []
    if not images:
        return {"handle": product["handle"], "status": "no-image"}
    source_url = images[0]
    filename = safe_filename(index, product["handle"], source_url, asset_prefix)
    request_url = resized_url(source_url)
    request = urllib.request.Request(
        request_url,
        headers={"User-Agent": "WebsiteBenchAssetCapture/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
    source_path = source_assets / filename
    runtime_path = runtime_assets / filename
    source_path.write_bytes(body)
    shutil.copyfile(source_path, runtime_path)
    return {
        "handle": product["handle"],
        "name": filename,
        "url": request_url,
        "bytes": len(body),
        "status": "downloaded",
    }


def main() -> int:
    args = parse_args()
    source_document = json.loads(args.source_json.read_text(encoding="utf-8"))
    products = [normalize_product(product) for product in source_document.get("products", [])]
    if not products:
        raise ValueError("captured collection contains no products")
    args.source_assets.mkdir(parents=True, exist_ok=True)
    args.runtime_assets.mkdir(parents=True, exist_ok=True)
    for path in (args.products_out, args.map_out, args.provenance_out):
        path.parent.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 6))) as executor:
        futures = {
            executor.submit(
                download_one,
                index,
                product,
                args.source_assets,
                args.runtime_assets,
                args.asset_prefix,
            ): product["handle"]
            for index, product in enumerate(products)
        }
        for future in as_completed(futures):
            handle = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append(
                    {"handle": handle, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}
                )

    results.sort(key=lambda row: row["handle"])
    image_map = {
        row["handle"]: row["name"]
        for row in results
        if row.get("status") == "downloaded"
    }
    args.products_out.write_text(
        json.dumps(
            {
                "authority": "anonymous-read-only",
                "source_url": args.source_url,
                "count": len(products),
                "products": products,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    args.map_out.write_text(json.dumps(image_map, indent=2), encoding="utf-8")
    args.provenance_out.write_text(
        json.dumps({"schema_version": "bluemercury.asset-provenance.v1", "results": results}, indent=2),
        encoding="utf-8",
    )
    downloaded = sum(row.get("status") == "downloaded" for row in results)
    failed = sum(row.get("status") == "failed" for row in results)
    print(json.dumps({"products": len(products), "images_downloaded": downloaded, "failed": failed}))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
