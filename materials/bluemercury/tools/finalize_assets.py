from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
import urllib.request
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
EXTRAS = {
    "skinceuticals-c-e-ferulic.jpg": "https://cdn.shopify.com/s/files/1/0283/0185/2747/files/variant_images-size-DefaultTitle-635494263008-1_grande.jpg?v=1781791334",
    "skinceuticals-c-e-ferulic-2.jpg": "https://cdn.shopify.com/s/files/1/0283/0185/2747/files/variant_images-size-DefaultTitle-635494263008-3.jpg?v=1786139356&width=450",
    "skinceuticals-c-e-ferulic-3.jpg": "https://cdn.shopify.com/s/files/1/0283/0185/2747/files/variant_images-size-DefaultTitle-635494263008-2.1.jpg?v=1786634517&width=450",
    "juanaforbluemercury-lt.woff2": "https://cdn.shopify.com/s/files/1/0283/0185/2747/t/1606/assets/juanaforbluemercury-lt.woff2",
    "neuehaasunicaforblue.woff2": "https://cdn.shopify.com/s/files/1/0283/0185/2747/t/1606/assets/neuehaasunicaforblue.woff2",
}
CURRENT_CATALOG_EXTRAS = {
    "skinceuticals-c-e-ferulic-4.jpg": "https://cdn.shopify.com/s/files/1/0283/0185/2747/files/variant_images-size-DefaultTitle-635494263008-4.jpg?v=1786139357&width=450",
    "skinceuticals-c-e-ferulic-5.jpg": "https://cdn.shopify.com/s/files/1/0283/0185/2747/files/variant_images-size-DefaultTitle-635494263008-5.jpg?v=1786139359&width=450",
}
ROOT_EXTRAS = {
    "home-hero-m61-desktop.jpg": "https://bluemercury.com/cdn/shop/files/2026-07-site-back-to-routine-hp-hero-des-2.jpg",
    "home-hero-m61-mobile.jpg": "https://bluemercury.com/cdn/shop/files/2026-07-site-back-to-routine-hp-hero-mob-2.jpg?v=1784582596&width=900",
}
CURRENT_ROOT_EXTRAS = {
    "home-hero-chantecaille.jpg": "https://cdn.shopify.com/s/files/1/0283/0185/2747/files/2026_08_ad204-02_chantecaille_vm_lifestyle_store-window-banner_02-site-hp-hero-half-des_1.jpg?v=1787185697&width=1700",
    "chantecaille-brand-hero.png": "https://bluemercury.com/cdn/shop/files/chantecaille-brand-hero.png?v=1650642295&width=1500",
    "home-hero-fall-desktop.jpg": "https://cdn.shopify.com/s/files/1/0283/0185/2747/files/2026-07-site-back-to-routine-hp-hero-des.jpg?v=1784582100&width=1700",
    "home-hero-fall-mobile.jpg": "https://cdn.shopify.com/s/files/1/0283/0185/2747/files/2026-07-site-back-to-routine-hp-hero-mob.jpg?v=1784582099&width=900",
}


def ensure_asset(source_path: Path, runtime_path: Path, url: str) -> None:
    if source_path.exists():
        source_body = source_path.read_bytes()
        if not runtime_path.exists() or hashlib.sha256(runtime_path.read_bytes()).digest() != hashlib.sha256(source_body).digest():
            runtime_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, runtime_path)
        return
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent":"WebsiteBenchAssetCapture/1.0"}), timeout=30) as response:
        body = response.read(25_000_001)
    if len(body) > 25_000_000:
        raise ValueError(f"asset exceeds 25 MB: {url}")
    source_path.write_bytes(body)
    runtime_path.write_bytes(body)

def main() -> None:
    extra_source = ROOT / "source-assets" / "2026-08-19.extras"
    current_source = ROOT / "source-assets" / "2026-08-20.playwright-r3"
    assets_root = ROOT / "clone" / "static" / "assets"
    runtime_dir = assets_root / "catalog"
    extra_source.mkdir(parents=True, exist_ok=True); current_source.mkdir(parents=True, exist_ok=True); runtime_dir.mkdir(parents=True, exist_ok=True)
    for name, url in EXTRAS.items():
        source_path, runtime_path = extra_source / name, runtime_dir / name
        ensure_asset(source_path, runtime_path, url)
    for name, url in CURRENT_CATALOG_EXTRAS.items():
        source_path, runtime_path = current_source / name, runtime_dir / name
        ensure_asset(source_path, runtime_path, url)
    for name, url in ROOT_EXTRAS.items():
        source_path, runtime_path = extra_source / name, assets_root / name
        ensure_asset(source_path, runtime_path, url)
    for name, url in CURRENT_ROOT_EXTRAS.items():
        source_path, runtime_path = current_source / name, assets_root / name
        ensure_asset(source_path, runtime_path, url)
    url_by_name = {}
    for provenance_path in sorted((ROOT / "source-assets").rglob("*provenance.json")):
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        url_by_name.update({row.get("name"):row.get("url") for row in provenance.get("results", []) if row.get("name")})
    url_by_name.update(EXTRAS); url_by_name.update(CURRENT_CATALOG_EXTRAS); url_by_name.update(ROOT_EXTRAS); url_by_name.update(CURRENT_ROOT_EXTRAS)
    assets=[]
    runtime_files = list(runtime_dir.iterdir()) + [assets_root / name for name in {*ROOT_EXTRAS, *CURRENT_ROOT_EXTRAS}]
    for runtime in sorted(runtime_files, key=lambda path: path.as_posix()):
        if not runtime.is_file(): continue
        source=ROOT/"source-assets"/"2026-08-19.catalog"/runtime.name
        if not source.exists():
            candidates = sorted((ROOT / "source-assets").rglob(runtime.name), reverse=True)
            if candidates: source = candidates[0]
            else: source = extra_source/runtime.name
        body=runtime.read_bytes()
        mime_type="font/woff2" if runtime.suffix.lower() == ".woff2" else (mimetypes.guess_type(runtime.name)[0] or "application/octet-stream")
        dimensions=None
        if mime_type.startswith("image/"):
            with Image.open(runtime) as image: dimensions={"width":image.width,"height":image.height}
        capture_id = "2026-08-20.playwright-r3" if "2026-08-20.playwright-r3" in source.as_posix() else "2026-08-19.ea1-ea2"
        assets.append({"id":"bluemercury."+hashlib.sha256(runtime.name.encode()).hexdigest()[:16],"priority":"p0","required":True,"source_path":source.relative_to(ROOT).as_posix(),"runtime_path":runtime.relative_to(ROOT).as_posix(),"bytes":len(body),"sha256":hashlib.sha256(body).hexdigest(),"mime_type":mime_type,"dimensions":dimensions,"referenced_by":["candidate:clone/app.py","candidate:clone/static/site.css"],"evidence_kind":"current-direct","source_url":url_by_name.get(runtime.name),"capture_id":capture_id})
    manifest={"schema_version":"offline-clone.assets.v1","snapshot_id":"2026-08-20.bluemercury.r3","created_at":"2026-08-20T16:00:00Z","remote_runtime_policy":"forbidden","closure_status":"declared","no_assets_reason":None,"assets":assets}
    (ROOT/"source-assets"/"manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print(json.dumps({"assets":len(assets),"bytes":sum(a["bytes"] for a in assets),"missing_source":sum(not (ROOT/a["source_path"]).exists() for a in assets)}))

if __name__=="__main__": main()
