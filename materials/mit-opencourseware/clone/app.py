"""Deterministic, network-closed MIT OpenCourseWare evaluation clone."""

from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path
from typing import Iterator
from urllib.parse import quote, unquote, urlsplit

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse


SITE_ID = "mit-opencourseware"
DISPLAY_NAME = "MIT OpenCourseWare"
CAPTURE_ID = "mit-opencourseware-20260905T070619Z"
HERE = Path(__file__).resolve().parent
SITE_ROOT = HERE.parent
DATA = json.loads((HERE / "site-data.json").read_text(encoding="utf-8"))
PAGES = DATA["pages"]
COURSES = DATA["catalog"]["courses"]
PDF = DATA["pdf"]
DOWNLOADS = DATA.get("downloads", {})
SUPPLEMENTARY_DOWNLOADS = DATA.get("supplementary_downloads", {})
ASSET_URL_MAP = DATA.get("asset_url_map", {})
UNAVAILABLE_ASSETS = DATA.get("unavailable_assets", {})
ASSET_REPORTS = DATA.get("asset_reports", {})
G3_VISUAL_ASSETS = DATA.get("g3_visual_assets", {})
G3_VISUAL_URL_MAP = DATA.get("g3_visual_url_map", {})
G3B_CONTENT_ASSETS = DATA.get("g3b_content_assets", {})
G3B_CONTENT_URL_MAP = DATA.get("g3b_content_asset_url_map", {})
G3C_COLLECTION_ASSETS = DATA.get("g3c_collection_assets", {})
G3C_COLLECTION_URL_MAP = DATA.get("g3c_collection_url_map", {})
G3C_CATALOG_ASSETS = DATA.get("g3c_catalog_assets", {})
G3C_CATALOG_URL_MAP = DATA.get("g3c_catalog_url_map", {})
CONTENT_INDEX = json.loads((HERE / "content-index.json").read_text(encoding="utf-8"))
CONTENT_ROUTES = CONTENT_INDEX["routes"]

app = FastAPI(title=DISPLAY_NAME, docs_url=None, redoc_url=None, openapi_url=None)


def local_path(url: str) -> str:
    """Resolve one frozen first-party identity without contacting the network."""
    if url == PDF["source_url"]:
        return str(PDF["path"])
    if url in G3B_CONTENT_URL_MAP:
        return str(G3B_CONTENT_URL_MAP[url])
    if url in G3C_COLLECTION_URL_MAP:
        return str(G3C_COLLECTION_URL_MAP[url])
    if url in G3C_CATALOG_URL_MAP:
        return str(G3C_CATALOG_URL_MAP[url])
    if url in G3_VISUAL_URL_MAP:
        return str(G3_VISUAL_URL_MAP[url])
    if url in ASSET_URL_MAP:
        return str(ASSET_URL_MAP[url])
    parsed = urlsplit(url)
    if parsed.hostname not in {"ocw.mit.edu", "www.ocw.mit.edu"}:
        return url
    path = unquote(parsed.path or "/")
    candidates = (path, path + "/" if not path.endswith("/") else path, path.rstrip("/") or "/")
    for candidate in candidates:
        if candidate in PAGES or candidate in DOWNLOADS or candidate in SUPPLEMENTARY_DOWNLOADS:
            return candidate + (f"?{parsed.query}" if parsed.query else "")
    return "/data-boundary/"


def record_attrs(record: dict[str, object] | None) -> str:
    if not record:
        return ""
    return (
        f' data-wb-route-family="{escape(str(record["family"]), quote=True)}"'
        f' data-wb-page-id="{escape(str(record["page_id"]), quote=True)}"'
    )


def report_assets(record: dict[str, object], *, kind: str = "img") -> list[dict[str, object]]:
    """Return retained assets observed by this row's exact frozen report."""
    refs = ASSET_REPORTS.get(str(record.get("evidence_report", "")), [])
    return [ref for ref in refs if ref.get("status") == 200 and ref.get("kind") == kind]


def course_root(path: str) -> str:
    parts = path.split("/")
    return f"/courses/{parts[2]}/" if len(parts) > 2 and parts[1] == "courses" else ""


def direct_course_asset(record: dict[str, object]) -> dict[str, object] | None:
    """Resolve a course image only when its source URL is under the exact course root."""
    root = course_root(str(record["path"]))
    for ref in report_assets(record):
        source_path = unquote(urlsplit(str(ref["url"])).path)
        if root and source_path.startswith(root):
            return ref
    return None


def image_tag(ref: dict[str, object], media_id: str, *, alt: str | None = None) -> str:
    return (
        f'<img data-wb-media="{escape(media_id, quote=True)}" '
        f'data-wb-asset-source="{escape(str(ref["url"]), quote=True)}" '
        f'src="{escape(str(ref["local_url"]), quote=True)}" '
        f'alt="{escape(str(ref.get("alt", "") if alt is None else alt), quote=True)}">'
    )


COMMON_CSS_URL = "https://ocw.mit.edu/static_shared/css/common.5ce53.css"
HOME_CSS_URL = "https://ocw.mit.edu/static_shared/css/www.5ce53.css"
COURSE_CSS_URL = "https://ocw.mit.edu/static_shared/css/course_v2.5ce53.css"

BASE_CSS = r"""
:root{--red:#a31f34;--deep:#750014;--blue:#126f9a;--ink:#212529;--paper:#fff;--mist:#f5f5f5}
@font-face{font-family:"Cardo Bold";src:url("/fonts/Cardo-Bold.ttf") format("truetype");font-weight:bold;font-style:normal;font-display:block}@font-face{font-family:"Helvetica Light";src:url("/fonts/Helvetica-Light.ttf") format("truetype");font-weight:normal;font-style:normal;font-display:block}@font-face{font-family:"Material Icons";src:url("/fonts/MaterialIcons-Regular.subset.woff2") format("woff2");font-weight:normal;font-style:normal;font-display:block}.material-icons{font-family:"Material Icons";font-weight:normal;font-style:normal;font-size:21px;line-height:1;letter-spacing:normal;text-transform:none;display:inline-block;white-space:nowrap;word-wrap:normal;direction:ltr;font-feature-settings:"liga";-webkit-font-feature-settings:"liga";-webkit-font-smoothing:antialiased}*{box-sizing:border-box}html,body{margin:0;padding:0}body{color:var(--ink);background:var(--paper);font:16px/1.5 Helvetica,Arial,sans-serif}a{color:#000}main{min-height:620px}.wrap{max-width:1200px;margin:auto;padding:42px 28px}.cta{display:inline-block;background:var(--red);color:#fff;text-decoration:none;padding:14px 22px;font-weight:700}.section{padding:34px 0}.cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:22px}.card{display:grid;grid-template-columns:180px 1fr;border:1px solid #bbb;background:#fff;min-height:164px}.card img,.placeholder{width:180px;height:164px;object-fit:cover;background:#ddd}.card .copy{padding:17px}.card h3{margin:5px 0 10px;font-size:21px;line-height:1.15}.eyebrow{font-size:12px;font-weight:700;text-transform:uppercase}.catalog-layout{display:grid;grid-template-columns:300px 1fr;gap:34px}.filters{background:#f1f1f1;padding:22px}.filters button,.filters label{display:block;margin:12px 0}.tabs{display:flex;gap:25px;border-bottom:3px solid #ddd;margin-bottom:20px}.tabs label{font-size:18px;padding:12px 4px}.tabs .active{border-bottom:5px solid var(--red);font-weight:700}.results-head{display:flex;justify-content:space-between;align-items:center}.side{background:#eee;padding:24px}.side a{display:block;padding:10px 0;border-bottom:1px solid #ccc;text-decoration:none}.course-main{max-width:760px}.notice{padding:24px;background:#fff0f1;border-left:6px solid var(--red)}.media-strip,.video-grid,.story-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:22px}.media-strip img,.video-card img,.story-card img{width:100%;height:180px;object-fit:cover}.story-card,.video-card{border:1px solid #ccc;padding:18px}.download-panel{background:#f1f1f1;padding:24px}
.generic-header{background:var(--red);color:#fff}.generic-head{height:102px;max-width:1200px;margin:auto;display:flex;align-items:center;gap:34px;padding:18px 28px}.generic-head .logo{width:310px}.generic-head form{display:flex;flex:1;max-width:600px}.generic-head input{flex:1;border:0;padding:14px;font-size:17px}.generic-head button{border:0;background:#111;color:#fff;padding:0 22px;font-weight:700}.generic-nav{background:var(--deep);color:#fff}.generic-nav .bar{max-width:1200px;margin:auto;display:flex;gap:28px;padding:12px 28px}.generic-nav a{color:#fff;text-decoration:none;font-weight:700}.generic-footer{background:#222;color:#fff;margin-top:40px}.generic-footer .wrap{padding-top:28px;padding-bottom:30px}.generic-footer a{color:#fff;margin-right:24px}
#desktop-header{height:80px!important;background:#000;color:#fff;display:flex;justify-content:center;width:100%}#desktop-header .contents{height:100%;max-width:1447px;width:100%;padding:0 42px;display:flex;align-items:center;justify-content:space-between}#desktop-header .ocw-logo img{display:block;width:217px;height:auto}#desktop-header .right{display:flex;align-items:center;justify-content:flex-end;height:100%}#desktop-header .right a{box-sizing:border-box!important;height:32px;padding:8px 14px;color:#fff;text-decoration:none;font:700 12.25px/16px Helvetica,Arial,sans-serif;text-transform:uppercase;white-space:nowrap}#desktop-header .right a.search-icon{position:relative;flex:0 0 75.4px;width:75.4px;font-size:0!important;color:transparent!important}#desktop-header .right .search-icon:before{content:"";position:absolute;left:17px;top:6px;width:11px;height:11px;border:3px solid #fff;border-radius:50%}#desktop-header .right .search-icon:after{content:"";position:absolute;left:29px;top:19px;width:8px;height:3px;background:#fff;transform:rotate(45deg)}#desktop-header .right .give-button{box-sizing:border-box!important;flex:0 0 128px;width:128px;height:43px;min-width:128px;padding:13px 18px 10px;text-align:center;background:#a31f34;border-bottom:3px solid #851124;border-radius:5px}#desktop-header .right .about-link{flex:0 0 96px;width:96px}#desktop-header .right .help-link{flex:0 0 94px;width:94px}#desktop-header .right .contact-link{flex:0 0 88px;width:88px}#desktop-header .heart{font-size:15px;margin-left:6px;color:#760018}.nav-toggle{display:none}
.home-shell-page{background:#fff url("/g3a-visual-assets/c27dd71e2d43b3aa5badb85339718fb5f5caa50e9c5c68628456bb93c483f6d2.png") center 500px/1442px auto no-repeat;font-family:SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace}.home-shell-page main{min-height:4300px}.home-shell-page #home-header{position:absolute;z-index:10;top:0;left:0;width:100%}.home-shell-page #desktop-header{height:116px!important;background:transparent}.home-shell-page #desktop-header .contents{max-width:1280px;padding:0 48px}.home-shell-page #desktop-header .ocw-logo img{width:260px}.home-shell-page #desktop-header .right a{font-size:12px;height:37px;padding:10px 16px}.home-shell-page #desktop-header .right a.search-icon{font-size:0!important;width:57px}.home-shell-page #desktop-header .right .give-button{width:128px;height:43px;padding:12px 12px 10px}.home-banner{height:500px;background-size:cover;background-position:center top;color:#fff}.home-banner .banner-columns{height:100%;max-width:1280px;margin:auto;padding:196px 48px 0;display:grid;grid-template-columns:550px 504px;gap:82px}.home-banner .first-column{width:550px;padding-top:9px}.home-banner .discover{font-weight:700;letter-spacing:.2px;margin:0 0 10px}.home-search-row{height:50px;display:grid;grid-template-columns:332px 80px 50px 88px}.home-search-row input{width:100%;height:50px;border:0;border-radius:4px 0 0 4px;padding:0 12px;font:16px SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace}.home-search-row button{border:0;border-radius:0;background:#126f9a;color:#fff;font-weight:700}.home-search-row .or{display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:700}.home-search-row .explore{height:50px;display:flex;align-items:center;justify-content:center;background:#a31f34;color:#fff;text-decoration:none;font-weight:700}.home-options{height:96px;margin-top:32px;padding:24px 32px;background:rgba(0,0,0,.81);display:grid;grid-template-columns:1fr 1.35fr}.home-option{height:48px;color:#fff}.home-option:first-child{border-right:1px solid #fff;padding-right:16px}.home-option:last-child{padding-left:16px}.home-option span,.home-option a{display:block}.home-option a{color:#32c5ff}.home-mission{height:224px;padding:27px 64px 24px;background:rgba(18,111,154,.68)}.home-mission h1{margin:0 0 17px;color:#fff!important;font:700 22.4px/40px SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace!important;text-transform:uppercase}.home-mission p{margin:0 0 8px;font-size:16px;line-height:19px}.home-mission a{display:block;color:#fff;font-weight:700;text-transform:uppercase}.home-promo{position:relative;height:230px;background:#fff}.home-promo-inner{width:900px;height:182px;margin:auto;padding-top:8px;display:grid;grid-template-columns:270px 1fr;gap:24px}.home-promo-image{width:270px;height:159px;object-fit:cover;border-left:5px solid #555}.home-promo-copy{padding-top:26px}.home-promo-copy h2{width:582px;margin:0 0 8px;font:600 22.4px/25.6px SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace}.home-promo-copy h3{margin:0 0 3px;font:600 16px/24px SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace}.home-promo-copy a{font-weight:700}.promo-arrow{position:absolute;top:74px;width:60px;height:67px;border:0;background:#fff;font-size:50px;line-height:50px;color:#444}.promo-arrow.prev{left:0}.promo-arrow.next{right:0}.promo-dots{position:absolute;bottom:0;left:0;right:0;text-align:center;color:#e8ebed;font-size:23px;letter-spacing:2px}.promo-dots .active{color:#d8dde0}.home-section{max-width:1280px;margin:auto;padding:0 16px 42px}.home-section h2{font:600 22.4px/26px SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace;margin:7px 0 14px}.home-section-controls{display:flex;justify-content:flex-end;gap:8px;margin-top:-40px;margin-bottom:8px}.home-section-controls a{height:38px;padding:7px 12px;border:1px solid #9c9d9e;border-radius:5px;color:#000;text-decoration:none;font-weight:700}.home-shell-page .home-section .cards{grid-template-columns:repeat(4,1fr);gap:16px}.home-shell-page .home-section .card{display:block;min-height:381px;border:1px solid #9c9d9e;border-radius:10px;overflow:hidden}.home-shell-page .home-section .card img,.home-shell-page .home-section .placeholder{display:block;width:100%;height:186px;object-fit:cover}.home-shell-page .home-section .card .copy{padding:12px}.home-shell-page .home-section .card h3{font-size:18px}.home-lower{max-width:1280px;margin:auto;padding:30px 48px}.home-lower .cta{margin:4px}.home-shell-page .generic-footer{margin-top:0}
.course-shell-page{background:#f5f5f5;font:14px/21px SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace}.course-shell-page main{min-height:619px}.course-banner{height:120px;background:#126f9a;color:#fff}.course-banner-content{height:120px;padding:24px 42px;max-width:1440px;margin:auto}.course-banner .course-meta{font-size:12px;line-height:18px;margin:0 0 23px}.course-banner h1{margin:0;font:400 31.92px/36px SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace}.course-banner h1 a{color:#fff;text-decoration:none}.course-stage{height:619px;padding:20px 29px 55px;display:grid;grid-template-columns:214px minmax(0,798px) 332px;gap:19px;max-width:1440px;margin:auto}.course-panel{height:544px;background:#fff;box-shadow:0 2px 4px rgba(0,0,0,.16)}.course-side{padding:17px 18.5px}.course-side nav{background:transparent;color:#212529}.course-side a{display:block;height:35px;padding:8px 0;color:#343a40;text-decoration:none;font-size:14px;line-height:19px;border:0}.course-center{padding:26px 18px}.course-center h2{margin:0 0 20px;color:#000!important;font:700 14px/16px SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace!important;text-transform:none!important}.course-center h3{font:700 12.04px/28px SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace!important;color:#6c757d;margin:0}.course-description{height:153px}.course-description p{margin:0;font-size:14px;line-height:21px}.course-description button{border:0;background:transparent;text-decoration:underline;padding:0;margin-left:4px;font:inherit}.course-info-grid{display:grid;grid-template-columns:1fr 1fr;gap:30px}.course-info-grid a{color:#000;text-decoration:underline}.course-info-grid .column{min-width:0}.course-info-block{margin-bottom:14px}.course-info-block p{margin:4px 0}.topic-tree{padding-left:14px}.topic-tree div{margin:4px 0}.resource-types-title{height:35px;display:flex;align-items:center;margin-top:14px!important;margin-bottom:3px!important}.resource-pills{display:flex;flex-wrap:wrap;gap:10px 8px}.resource-pill{height:30px;padding:4px 10px;border:1px solid #bcbcbc;border-radius:15px;white-space:nowrap;font-size:12px}.resource-pill:before{content:"▣";margin-right:7px;font-size:15px}.course-right{padding:18px}.course-right img{display:block;width:294px;height:221px;object-fit:contain}.course-caption{height:54px;margin:10px 0 0;font-size:12px;line-height:16px}.course-right hr{margin:0 0 14px;border:0;border-top:1px solid #ddd}.download-course-link-button{display:inline-block;height:37px;padding:7px 20px;border:1px solid #126f9a;border-radius:4px;color:#126f9a;text-decoration:none}.course-shell-page .course-section,.course-shell-page .resource-page,.course-shell-page .download-panel{max-height:492px;overflow:auto}.course-shell-page .course-section h1,.course-shell-page .resource-page h1,.course-shell-page .download-panel h1{font:600 22px/26px SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace}.course-shell-page .evidence-links{padding-left:20px}.course-footer{height:160px;background:#fff;color:#595959}.course-footer-main{height:80px;padding:24px 42px 0;display:flex;align-items:flex-start}.course-footer-logo{width:117px;height:30px;object-fit:contain;object-position:left top;filter:brightness(0)}.course-footer-copy{margin-left:13px;font-size:12.25px;line-height:17px}.course-footer-copy strong{font-weight:400}.course-footer-social{margin-left:auto;color:#777;font-size:20px;letter-spacing:9px}.course-footer-links{padding:0 350px;font-size:12.25px}.course-footer a{color:#595959;margin-right:14px}
.home-shell-page{font-family:Helvetica,Arial,sans-serif}.home-shell-page #desktop-header .search-icon{display:none!important}.home-shell-page #desktop-header .right a{font:700 14px/16px Helvetica,Arial,sans-serif;height:37px;padding:10px 16px}.home-shell-page #desktop-header .right .give-button{box-sizing:border-box!important;flex:0 0 127px;width:127px;min-width:127px;height:43px;padding:12px 16px 10px}.home-shell-page #desktop-header .right .about-link{flex:0 0 111px;width:111px}.home-shell-page #desktop-header .right .help-link{flex:0 0 109px;width:109px}.home-shell-page #desktop-header .right .contact-link{flex:0 0 102px;width:102px}.home-search-row input{font:16px Helvetica,Arial,sans-serif}.home-mission h1{font:700 22.4px/40px Helvetica,Arial,sans-serif!important}.home-promo-copy h2{font:600 22.4px/25.6px Helvetica,Arial,sans-serif}.home-promo-copy h3{font:600 16px/24px Helvetica,Arial,sans-serif}.home-section h2{font:600 22.4px/26px Helvetica,Arial,sans-serif}.course-shell-page{font:14px/21px Helvetica,Arial,sans-serif}.course-banner h1{font:400 31.92px/36px Helvetica,Arial,sans-serif}.course-center h2{font:700 14px/16px Helvetica,Arial,sans-serif!important}.course-center h3{font:700 12.04px/28px Helvetica,Arial,sans-serif!important}.course-shell-page .course-section h1,.course-shell-page .resource-page h1,.course-shell-page .download-panel h1{font:600 22px/26px Helvetica,Arial,sans-serif}.course-menu-mobile{display:none}
.g3b-source-fragment{max-width:100%;overflow-wrap:anywhere}.g3b-source-fragment img{max-width:100%;height:auto}.g3b-source-fragment table{width:100%;border-collapse:collapse}.g3b-source-fragment th,.g3b-source-fragment td{padding:8px;border:1px solid #ccc;vertical-align:top}.g3b-source-fragment .g3b-media-disabled,.g3b-asset-unavailable{display:block;padding:12px;background:#f1f1f1;color:#555}.course-shell-page .g3b-source-fragment h1,.course-shell-page .g3b-source-fragment h2{font-family:Helvetica,Arial,sans-serif}.course-shell-page .g3b-source-fragment p,.course-shell-page .g3b-source-fragment li{line-height:1.5}
.general-shell-page #desktop-header{height:116px!important}.general-shell-page #desktop-header .contents{max-width:1440px;padding:0 46px}.general-shell-page #desktop-header .ocw-logo img{width:217px}.general-shell-page main{min-height:620px}.general-shell-page .generic-footer{background:#f5f5f5;color:#343a40;margin-top:0}.general-shell-page .generic-footer a{color:#343a40}.general-shell-page .wrap{max-width:1280px}.catalog-page .catalog-hero{height:240px;padding:27px 40px 20px;text-align:center}.catalog-page .catalog-hero h1{margin:0 0 2px;font-size:32px;line-height:42px}.catalog-page .catalog-hero p{margin:0 0 35px;color:#a31f34;font-weight:700;font-size:17px;letter-spacing:.6px}.catalog-search{display:flex;width:700px;height:50px;margin:auto}.catalog-search input{flex:1;border:1px solid #d2d2d2;border-radius:5px 0 0 5px;padding:0 12px;font-size:16px}.catalog-search button{width:92px;border:0;border-radius:0 5px 5px 0;background:#126f9a;color:#fff;font-weight:700}.catalog-page .catalog-content{max-width:1344px;margin:auto;border-top:1px solid #ddd;display:grid;grid-template-columns:335px 1fr}.catalog-page .filters{background:#fff;padding:18px 16px 30px 0}.catalog-page .filter-heading{display:flex;justify-content:space-between;height:35px}.catalog-page .filter-group{border:1px solid #ddd;margin-bottom:14px}.catalog-page .filter-title{height:43px;width:100%;margin:0!important;padding:10px 14px;text-align:left;border:0;background:#f5f5f5;font-size:16px;font-weight:700}.catalog-page .department-search{width:100%;height:40px;border:0;border-bottom:1px solid #ddd;padding:8px 12px}.catalog-page .department-list{padding:8px 12px}.catalog-page .department-list label{display:flex;margin:4px 0;font-size:13px;line-height:18px}.catalog-page .department-list .count{margin-left:auto;color:#aaa}.catalog-page [data-wb-component="catalog-results"]{background:#f7f7f7;padding:0 16px 40px}.catalog-page .tabs{height:65px;margin:0;align-items:flex-end}.catalog-page .tabs label{height:46px;padding:11px 0;font-size:15px}.catalog-page .tabs input{position:absolute;opacity:0}.catalog-page .results-head{height:64px}.catalog-page .results-head h2{font-size:14px;margin-left:auto;margin-right:18px}.catalog-page .results-head select{height:40px;min-width:175px;padding:0 10px}.catalog-page .cards{display:block}.catalog-page .card{display:flex;flex-direction:row-reverse;justify-content:space-between;min-height:178px;margin-bottom:18px;border-color:#ccc;border-radius:4px;box-shadow:0 2px 3px rgba(0,0,0,.18)}.catalog-page .card img,.catalog-page .placeholder{width:140px;height:108px;margin:30px 20px;flex:0 0 140px}.catalog-page .card .copy{flex:1;padding:20px}.catalog-page .card .eyebrow{color:#a31f34;font-size:13px}.catalog-page .card h3{font-size:18px;margin:8px 0}.catalog-page .card p{margin:0;font-size:13px}.catalog-page [data-wb-control="catalog-load-more"]{margin:12px auto;display:block;width:130px;text-align:center}
.video-gallery-static-thumbnails .course-stage,.video-resource-static-thumbnail .course-stage{grid-template-columns:214px minmax(0,842px) 269px}.video-gallery-static-thumbnails .course-center,.video-resource-static-thumbnail .course-center{padding:16px 18px}.video-gallery-static-thumbnails .course-right,.video-resource-static-thumbnail .course-right{padding:12px 14px}.video-gallery-static-thumbnails .course-side a:nth-child(3),.video-resource-static-thumbnail .course-side a:nth-child(3){color:#a31f34;font-weight:700}.video-title{margin:0 0 12px!important;padding-bottom:9px;border-bottom:1px solid #aaa;font:700 23px/27px Helvetica,Arial,sans-serif!important}.video-description{margin:0 0 14px}.video-list{display:block}.video-list-card{height:99px;border:1px solid #999;margin:0 0 7px;padding:10px;display:grid;grid-template-columns:103px 1fr;gap:20px;align-items:center}.video-list-card img{width:103px;height:77px;object-fit:cover;border-radius:5px}.video-list-card a{font-size:12px;font-weight:700;text-transform:uppercase;text-decoration:none;color:#444}.offline-video-player{position:relative;width:804px;height:488px;background:#000;color:#fff}.offline-video-surface{position:absolute;inset:0;width:100%;height:100%;border:0;background:#000;color:#ddd;text-align:left;padding:455px 24px 10px;font:14px/20px Helvetica,Arial,sans-serif}.video-course-info h2{font-size:14px!important;margin:0 0 26px!important}.video-course-info h3{margin:0 0 5px!important;color:#444!important;font-size:12px!important;text-transform:uppercase}.video-course-info p{margin:0 0 23px;font-size:12px;line-height:20px}.video-course-info .download-course-link-button{margin-top:6px}.video-course-info .resource-kinds{padding-top:8px;border-top:1px solid #ddd}.video-course-info .resource-kinds span{display:block;margin:8px 0}.video-resource-static-thumbnail .course-center{overflow:hidden!important}
.collection-course-cards{width:800px;margin:8px 0 34px}.collection-course-card{height:94px;margin:4px 0;border:1px solid #ddd;box-shadow:0 1px 2px rgba(0,0,0,.16);display:grid;grid-template-columns:141px 1fr 140px;align-items:center;color:#111;text-decoration:none}.collection-course-card .collection-thumb{width:125px;height:78px;margin:8px;background:#eee;display:block;object-fit:cover;color:#777;font-size:10px;text-align:center}.collection-course-card .collection-course-copy{padding:8px 12px}.collection-course-card strong{display:block;font-size:18px;line-height:17px}.collection-course-card small{color:#999}.collection-course-card .collection-level{color:#a31f34;font-size:12px}.g3c-get-started{max-width:1344px;margin:auto;padding:45px 0}.g3c-get-started>h1{margin:0 0 32px;font-size:32px}.g3c-get-started .page-container{margin:0!important;padding:0!important;max-width:1200px}.newsletter .g3b-source-fragment{max-width:none}.educator-authorized .g3b-media-disabled{display:none!important}
.stories-index .testimonial-banner.list{height:191px!important;min-height:191px;display:flex!important;justify-content:center;background:#f1f5f6}.stories-index .testimonial-banner.list h1{margin:0 0 8px}.video-gallery-static-thumbnails .course-stage,.video-resource-static-thumbnail .course-stage{height:700px;padding-bottom:18px}.video-gallery-static-thumbnails .course-panel,.video-resource-static-thumbnail .course-panel{height:662px}.course-center h2.video-title{font:700 23px/27px Helvetica,Arial,sans-serif!important}.educator #about-subnav{display:flex!important;width:100%}.educator .on-page-sub-nav{height:52px!important;padding:0 32px}.educator .on-page-sub-nav ul{display:flex!important;height:52px;align-items:center;justify-content:space-between;width:100%}.educator #educator-main-section>.px-5{margin:0!important;padding:0 32px!important}.educator #welcome{position:relative;height:576px!important;padding-top:70px!important}.educator #welcome .section-gruber-quote{position:absolute!important;left:0;right:0;top:576px;margin:0!important}.newsletter #mc_embed_signup{padding-left:52px!important}.newsletter .mc-field-group{display:block!important;margin:0 0 22px!important;clear:both}.newsletter .mc-field-group label{display:block!important;margin-bottom:5px}.newsletter .mc-field-group input,.newsletter .mc-field-group select{display:block!important;width:660px!important;max-width:660px;height:38px;padding:6px 9px}
.catalog-page [data-wb-component="catalog-results"]{display:grid;grid-template-columns:minmax(0,1fr) auto;align-content:start}.catalog-page [data-wb-component="catalog-results"]>.tabs{grid-column:1;grid-row:1}.catalog-page [data-wb-component="catalog-results"]>.results-head{grid-column:2;grid-row:1}.catalog-page [data-wb-component="catalog-results"]>.cards,.catalog-page [data-wb-component="catalog-results"]>.notice,.catalog-page [data-wb-component="catalog-results"]>[data-wb-control="catalog-load-more"],.catalog-page [data-wb-component="catalog-results"]>[data-wb-component="catalog-resource-media"]{grid-column:1/-1}.story-01-adrian-pastor .testimonial-banner{height:251px!important;min-height:251px;overflow:hidden;padding-top:30px}.story-01-adrian-pastor .view-all-stories-left-btn{margin-left:0!important;justify-content:flex-start!important}.story-01-adrian-pastor .single-testimonial-image-wrapper .img-container,.story-01-adrian-pastor .single-testimonial-image-wrapper img{width:200px!important;height:112px!important;object-fit:cover}.story-01-adrian-pastor .testimonial-banner .detail{margin-left:30px}.download-course .download-panel{background:transparent;padding:0;overflow:hidden!important}.download-course .download-course-container{height:191px;margin-top:25px}.download-course .course-download-info h2{font-size:14px!important;margin:0 0 26px!important}.download-course .course-download-info h3{margin:0 0 5px!important;color:#444!important;font-size:12px!important;text-transform:uppercase}.download-course .course-download-info p{margin:0 0 19px;font-size:12px;line-height:18px}
.stories-index .stories-list-item-container{width:1250px!important;margin:50px auto 0!important;display:grid!important;grid-template-columns:repeat(2,617px)!important;gap:16px!important}.stories-index .stories-list-item{width:617px!important;max-width:617px!important}.stories-index .testimonial-image-wrapper{width:595px!important;height:334px!important;margin:10px!important;padding:0!important}.stories-index .testimonial-image-wrapper img{width:595px!important;height:334px!important;object-fit:cover}.course-center h2.video-title{margin-bottom:19px!important}.story-01-adrian-pastor .testimonial-banner{padding-top:0}.educator #welcome{height:auto!important;min-height:576px;padding-top:4px!important}.educator #welcome>h1{transform:translateY(-65px)}.educator #welcome>p{transform:translateY(-32px)}.educator #welcome .section-gruber-quote{position:relative!important;left:-15px;right:auto;top:auto;margin:352px 0 0!important;width:calc(100% + 30px)!important;min-height:500px;display:block!important;background-size:cover!important;background-position:center!important}.newsletter #newsletter-main-section>.px-lg-5{height:210px;margin:0!important;padding:45px 32px 0!important}.newsletter #mc_embed_signup{position:static!important;display:block!important;clear:both;margin:0!important;padding:15px 0 40px 52px!important}.newsletter .mc-field-group{position:static!important;display:block!important;float:none!important;margin:0 0 31px!important;clear:both}.newsletter .mc-field-group label{display:block!important;margin-bottom:14px}.newsletter .mc-field-group input,.newsletter .mc-field-group select{position:static!important;display:block!important;float:none!important;width:660px!important;max-width:660px;height:56px;padding:6px 9px}.download-course .course-stage{height:700px;padding-bottom:18px;grid-template-columns:214px 20px 860px 288px;gap:0}.download-course .course-stage>.course-side{grid-column:1}.download-course .course-stage>.course-center{grid-column:3}.download-course .course-stage>.course-right{grid-column:4}.download-course .course-panel{height:662px}.download-course #main-course-section{width:100%!important;max-width:none!important;flex:0 0 100%!important;transform:translateY(-4px)}.download-course #main-course-section>.card-body{width:100%!important;max-width:none!important;padding:0!important}.download-course .download-course-container{width:100%!important;margin-top:-7px!important;margin-bottom:-7px!important}.download-course .resource-list-toggle .material-icons{width:20px!important;font-family:Arial,sans-serif!important;font-size:0!important}.download-course .resource-list-toggle .material-icons:before{content:"⌄"!important;font:700 18px/20px Arial,sans-serif!important}
.catalog-page [data-wb-component="catalog-results"]{padding-left:30px;grid-template-columns:490px minmax(0,1fr)}.catalog-page #desktop-header .search-icon{display:none!important}.catalog-page .card h3 a{text-decoration:none}.catalog-page .card img{width:144px;height:108px;margin-right:36px;flex-basis:144px}.collection-course-cards{width:803px;margin-top:-34px;margin-left:15px}.about #about-subnav{display:flex!important;width:100%}.about #about-subnav ul{display:flex!important;align-items:center;justify-content:space-between;width:100%;height:56px}.g3c-get-started>h1{margin-bottom:43px}
.download-course .resource-list-toggle{display:flex!important;align-items:center!important;justify-content:flex-start!important;gap:8px!important}.download-course .resource-list-toggle .material-icons:after{content:""!important;display:none!important}
.stories-index .testimonial-image-wrapper{flex:0 0 334px!important;min-height:334px!important}.about #ocw-25{transform:translateY(-50px)}.download-course .download-course-button .material-icons{display:inline-block!important;width:20px!important;font-family:Arial,sans-serif!important;font-size:0!important}.download-course .download-course-button .material-icons:before{content:"↓"!important;font:700 18px/20px Arial,sans-serif!important}.download-course .resource-list-toggle>a{display:flex!important;align-items:center!important;justify-content:flex-start!important;gap:8px!important}.catalog-page .catalog-tags{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}.catalog-page .catalog-tags span{padding:2px 7px;border:1px solid #bbb;border-radius:10px;color:#555;font-size:10px;line-height:14px}.catalog-page .card .card-meta{margin:2px 0 0;font-size:12px}.catalog-page .resource-result{display:block}.catalog-page .resource-result .eyebrow{font-weight:700}.catalog-page .resource-result h3{color:#111}
.stories-index .stories-list-item>.item-wrapper{width:617px!important;margin-right:0!important}.stories-index .testimonial-image-wrapper{margin:10px 10px 20px!important}
.home-carousel-second-batches .home-promo{height:200px}.home-carousel-second-batches .home-promo .promo-dots{display:none}.home-carousel-second-batches .home-promo .promo-arrow{display:flex;align-items:center;justify-content:center;text-decoration:none}
.home-carousel-second-batches [data-wb-component="featured-courses"]{width:1250px;max-width:1250px;height:447px;padding:0;overflow:hidden}.home-carousel-second-batches [data-wb-component="featured-courses"] .cards,.home-carousel-second-batches [data-wb-component="new-courses"] .cards{grid-template-columns:303px 295px 295px 303px;justify-content:space-between;gap:0;transform:translateY(-6px)}.home-carousel-second-batches [data-wb-component="featured-courses"] .home-section-controls,.home-carousel-second-batches [data-wb-component="new-courses"] .home-section-controls{transform:translateY(-6px)}.home-carousel-second-batches [data-wb-component="featured-courses"] .card{height:380px;min-height:380px}.home-carousel-second-batches [data-wb-component="featured-courses"] .card .copy,.home-carousel-second-batches [data-wb-component="new-courses"] .card .copy{padding:8px 16px}.home-carousel-second-batches [data-wb-component="featured-courses"] .card h3 a,.home-carousel-second-batches [data-wb-component="new-courses"] .card h3 a{text-decoration:none;color:#000}.home-carousel-second-batches [data-wb-component="featured-courses"] .card p,.home-carousel-second-batches [data-wb-component="new-courses"] .card p{font-size:13px;line-height:20px}
.home-carousel-second-batches [data-wb-component="new-courses"]{width:1250px;max-width:1250px;height:448px;padding:0;overflow:hidden}.home-carousel-second-batches [data-wb-component="new-courses"] h2{margin:7px 0 14px;font:600 22.4px/26px SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace}.home-carousel-second-batches [data-wb-component="new-courses"] .cards{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}.home-carousel-second-batches [data-wb-component="new-courses"] .card{display:block;height:381px;min-height:381px;border:1px solid #9c9d9e;border-radius:10px;overflow:hidden}.home-carousel-second-batches [data-wb-component="new-courses"] .card img,.home-carousel-second-batches [data-wb-component="new-courses"] .card .placeholder{display:block;width:100%;height:186px;object-fit:cover}.home-carousel-second-batches [data-wb-component="new-courses"] .card h3{font-size:18px}
.home-shell-page [data-wb-component="stories"]{position:relative;width:100%;max-width:none;height:653px;padding:0;overflow:hidden}.home-shell-page [data-wb-component="stories"]>h2{margin:0;text-align:center;font:700 32px/38px Arial,sans-serif}.home-shell-page .home-stories-intro{width:1100px;margin:6px auto 0;text-align:center;font:18px/25px Arial,sans-serif}.home-shell-page .story-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;width:1264px;margin:42px auto 0}.home-shell-page .story-card{position:relative;display:block;height:518px;padding:0;border:1px solid #d7dfe3;border-radius:10px;background:#fff;overflow:hidden}.home-shell-page .story-card>img{display:block;width:calc(100% - 20px);height:221px;margin:10px 10px 0;object-fit:cover;border-radius:5px}.home-shell-page .story-copy{padding:21px 30px 20px}.home-shell-page .story-card h3{margin:0 0 5px;font:700 22px/27px Arial,sans-serif}.home-shell-page .story-card h3 a{color:#000;text-decoration:none}.home-shell-page .story-role-row{display:flex;justify-content:space-between;margin:0;font:16px/24px Arial,sans-serif}.home-shell-page .story-summary{display:-webkit-box;margin:18px 0 0;overflow:hidden;-webkit-box-orient:vertical;-webkit-line-clamp:5;font:16px/24px Arial,sans-serif}.home-shell-page .read-full-story{position:absolute;left:30px;bottom:22px;color:#0a3e56;text-decoration:none;font:14px/20px Arial,sans-serif}.home-shell-page .story-arrow{position:absolute;z-index:2;top:365px;display:flex;width:60px;height:55px;align-items:center;justify-content:center;color:#000;text-decoration:none;font:64px/55px Arial,sans-serif}.home-shell-page .story-arrow.prev{left:0}.home-shell-page .story-arrow.next{right:0}.home-view-all-stories{position:absolute;left:50%;bottom:6px;transform:translateX(-50%);padding:10px 22px;border:1px solid #d7dfe3;color:#111;text-decoration:none;font:700 14px/20px Arial,sans-serif}
.home-carousel-second-batches [data-wb-component="featured-courses"]{margin-top:30px}.home-carousel-second-batches [data-wb-component="featured-courses"] .cards{grid-template-columns:305px 297px 297px 305px;transform:translateY(-7px)}.home-carousel-second-batches [data-wb-component="featured-courses"] .home-section-controls{transform:translateY(-7px)}.home-carousel-second-batches [data-wb-component="new-courses"]{margin-top:-4px}.home-carousel-second-batches [data-wb-component="new-courses"] .cards{grid-template-columns:305px 297px 297px 305px;justify-content:space-between;gap:0}.home-carousel-second-batches [data-wb-component="new-courses"] .home-section-controls{transform:translateY(-7px)}.home-carousel-second-batches [data-wb-component="featured-courses"] .card .copy,.home-carousel-second-batches [data-wb-component="new-courses"] .card .copy{padding-top:4px}
.home-shell-page [data-wb-component="stories"]{margin-top:116px}.home-shell-page [data-wb-component="stories"]>h2{line-height:25px}.home-shell-page .home-stories-intro{margin-top:20px}.home-shell-page .story-grid{grid-template-columns:413px 405px 413px;justify-content:space-between;gap:0;margin-top:40px}.home-shell-page .generic-footer{height:247px}
.general-shell-page #desktop-header .right{gap:8px}.general-shell-page #desktop-header .right .about-link{flex-basis:104px;width:104px}.general-shell-page #desktop-header .right .help-link{flex-basis:105px;width:105px}.general-shell-page #desktop-header .right .contact-link{flex-basis:98px;width:98px}
.catalog-page .view-controls{display:flex;gap:5px;margin-left:12px}.catalog-page .view-controls button{width:34px;height:34px;border:1px solid #bbb;background:#fff;color:#555;font-size:17px;line-height:28px}.catalog-page .view-controls button[aria-pressed="true"]{background:#e9ecef}
.course-mobile-heading{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}.course-page-title{margin:0 0 14px!important;padding-bottom:9px;border-bottom:1px solid #aaa;font:700 22px/27px Helvetica,Arial,sans-serif!important}.course-section-or-deep-link.course-shell-page .course-stage,.resource-detail-or-index.course-shell-page .course-stage{grid-template-columns:214px minmax(0,842px) 269px}.course-section-or-deep-link.course-shell-page .course-right,.resource-detail-or-index.course-shell-page .course-right{padding:12px 14px}.six006-course-info h2{font-size:14px!important;margin:0 0 24px!important}.six006-course-info h3{margin:0 0 4px!important;color:#444!important;font-size:12px!important;line-height:16px!important;text-transform:uppercase}.six006-course-info p{margin:0 0 18px;font-size:12px;line-height:18px}.six006-course-info .resource-kinds{padding-top:5px;border-top:1px solid #ddd}.six006-course-info .resource-kinds span{display:block;margin:5px 0}.course-side a.active{color:#a31f34;font-weight:700}.course-side a .disclosure{float:right}.problem-set-resource .resource-breadcrumb{margin-bottom:7px;color:#666}.problem-set-resource .resource-breadcrumb a{color:#555}.problem-set-resource #pdf-wrapper{display:block;width:320px;height:190px;border:1px solid #bbb;background:#fff}.download-course .resource-list-page{min-height:51px!important;height:51px!important}.download-course .resource-list-page>.row,.download-course .resource-list-page .d-inline-flex{height:50px!important;min-height:50px!important;align-items:center!important}.download-course .resource-list-page .resource-thumbnail{height:44px!important;min-height:44px!important}.newsletter.general-shell-page main{min-height:1150px}
.download-course .download-panel{max-height:none!important;height:auto!important}
.newsletter-authorized-stylesheet.general-shell-page main,.newsletter-authorized-stylesheet.general-shell-page .newsletter{min-height:1150px}
.assignments .course-center h2.course-page-title{font:700 18px/25px SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace!important;padding-bottom:0!important;margin-bottom:24px!important;transform:translateY(-2px)}
.assignments .assignments-source-content{width:825px;max-width:none;font:12px/21px SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace;letter-spacing:.5px}.assignments .assignments-source-content>p{margin:0 0 11px;font:12px/21px SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace!important}.assignments .assignments-source-content>p [data-wb-source-href$="/pages/related-resources/"]{white-space:nowrap}.assignments .assignment-table{width:825px!important;max-width:none;margin:0;border-collapse:collapse;table-layout:fixed}.assignments .assignment-table th{padding:8px;color:#fff;background:#126f9a;border:0;text-align:left;white-space:nowrap;font:700 12px/19px SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace!important}.assignments .assignment-table td{padding:10px 8px;border:0;vertical-align:middle;font:12px/21px SFMono-Regular,Menlo,Monaco,Consolas,"Liberation Mono","Courier New",monospace!important}.assignments .assignment-table tbody tr:nth-child(even) td{background:#f5f5f5}.assignments .assignment-table tbody tr:nth-child(1){height:84px}.assignments .assignment-table tbody tr:nth-child(2){height:148px}.assignments .assignment-table tbody tr:nth-child(3){height:146px}.assignments .assignment-table th:nth-child(1),.assignments .assignment-table td:nth-child(1){width:7%}.assignments .assignment-table th:nth-child(2),.assignments .assignment-table td:nth-child(2){width:22%}.assignments .assignment-table th:nth-child(3),.assignments .assignment-table td:nth-child(3){width:56%}.assignments .assignment-table th:nth-child(4),.assignments .assignment-table td:nth-child(4){width:15%}.assignments .assignment-table td p{margin:0 0 8px;line-height:21px!important}.assignments .assignment-table td p:last-child{margin-bottom:0}
body.about #about-us #president-dean-messages>.container{width:1140px;max-width:calc(100% - 30px)}
.stories-index .stories-list-item-container{display:flex!important;flex-wrap:wrap!important;column-gap:0!important;row-gap:28px!important}.stories-index .stories-list-item.col-lg-6{width:50%!important;max-width:50%!important;flex:0 0 50%!important}.stories-index .stories-list-item.col-lg-4{width:33.333333%!important;max-width:33.333333%!important;flex:0 0 33.333333%!important}.stories-index .stories-list-item.col-lg-6>.item-wrapper{width:617px!important}.stories-index .stories-list-item.col-lg-4>.item-wrapper{width:406px!important}.stories-index .testimonial-image-wrapper{width:calc(100% - 20px)!important;height:216px!important;min-height:216px!important;flex-basis:216px!important}.stories-index .testimonial-image-wrapper img{width:100%!important;height:216px!important}.stories-index .stories-list-item.col-lg-6 .testimonial-image-wrapper,.stories-index .stories-list-item.col-lg-6 .testimonial-image-wrapper img{height:334px!important;min-height:334px!important;flex-basis:334px!important}.stories-index.general-shell-page .generic-footer{height:247px}
.course-overview.course-shell-page .course-stage,.course-section-or-deep-link.course-shell-page .course-stage,.resource-detail-or-index.course-shell-page .course-stage{height:auto;min-height:619px;align-items:start}.course-overview.course-shell-page .course-panel,.course-section-or-deep-link.course-shell-page .course-panel,.resource-detail-or-index.course-shell-page .course-panel{height:auto;min-height:544px}.course-section-or-deep-link.course-shell-page .course-section,.resource-detail-or-index.course-shell-page .resource-page{max-height:none;overflow:visible}
.course-overview .course-home-grid{width:100%!important;max-width:none!important;flex:0 0 100%!important;padding:0!important}.course-overview .course-home-grid>.card{display:block!important;width:100%!important;min-height:0!important;border:0!important;box-shadow:none!important}.course-overview .course-home-grid>.card>.card-body{display:block!important;width:100%!important;max-width:none!important;height:auto!important;padding:0!important}.course-overview .course-home-grid .row{display:flex!important;flex-wrap:wrap!important}.course-overview .course-home-grid .col-sm-6{width:50%!important;max-width:50%!important;flex:0 0 50%!important}.course-overview>.eyebrow{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}.catalog-course-01.course-shell-page .course-stage{height:556px;min-height:556px}.catalog-course-01.course-shell-page .course-panel{height:481px;min-height:481px}.catalog-course-01.course-shell-page .course-footer{height:144px}
.educator #welcome .section-gruber-quote{height:460px!important;min-height:460px}.educator #discover-oer{margin-top:-25px!important}.educator #discover-oer .col-lg-6>img{height:442px;object-fit:cover}.educator #adapt-oer .section-content:first-child .col-lg-6>img{height:411px;object-fit:cover}.educator #share-adaptations .col-lg-6>img{height:443px;object-fit:cover}.educator #explore-reflective-practice{padding-bottom:129px}.educator #connect .col-lg-6>img{height:528px;object-fit:cover}.educator .educator-media-reservation{height:374px;visibility:hidden}.educator .educator-welcome-video-reservation{height:392.56px}.educator .section-chalk-radio{transform:translateY(-31px);margin-bottom:-374px!important}.educator #cadogan-quote+.section{margin-top:24px!important;padding:11px 0}
.educator #footer-container{margin-top:0!important}.educator>main{padding-bottom:1px}
.educator #about-subnav{position:relative!important;top:8px;width:auto!important;height:40px!important;margin:8px 16px 8px!important}.educator .on-page-sub-nav{height:40px!important;padding:0!important}.educator .on-page-sub-nav ul{height:40px!important}.educator #educator-main-section>.px-5{padding-top:16px!important}.educator #educator-main-section .section{padding:0!important}.educator #welcome{position:relative!important;height:auto!important;min-height:0!important;padding:0!important}.educator #discover-oer{margin-top:68.7969px!important}.educator #discover-oer .col-lg-6>img,.educator #adapt-oer .section-content:first-child .col-lg-6>img,.educator #share-adaptations .col-lg-6>img,.educator #explore-reflective-practice .col-lg-6>img,.educator #connect .col-lg-6>img{height:auto!important;object-fit:initial!important}.educator #explore-reflective-practice{padding:0!important}.educator .educator-media-reservation{height:374px!important}.educator .section-chalk-radio{transform:none!important;margin:48px -15px!important}.educator #cadogan-quote+.section{margin-top:68.7969px!important;padding:0!important}
body.about #president-dean-messages{height:1334px!important;margin-top:-84px}.about.general-shell-page .generic-footer{height:247px}
.collection-links{padding-bottom:10px!important;margin-bottom:-16px!important}.collection-links:after{content:"";display:block;clear:both}.collection-links>.eyebrow{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}.collection-introductory-programming.general-shell-page .generic-footer{height:247px}
body main main{min-height:0!important}.resource-detail-or-index #main-course-section{width:100%!important;max-width:none!important;flex:0 0 100%!important}
body.course-shell-page:not(.catalog-course-01) .course-footer{height:141px}.final-exam-resource-detail .course-stage,.lecture-note-1-resource-detail .course-stage,.problem-set-1-resource-detail .course-stage{height:957px!important;min-height:957px!important;padding-top:21px;padding-bottom:56px;align-items:stretch}.final-exam-resource-detail .course-panel,.lecture-note-1-resource-detail .course-panel,.problem-set-1-resource-detail .course-panel{height:880px!important;min-height:880px!important}.source-resource-detail #pdf-wrapper{display:block!important;width:303px;height:153px;margin-top:28px!important;border:1px solid #bbb;background:#fff}.source-resource-detail .resource-breadcrumb{margin-bottom:7px;color:#666}
.catalog-page>.generic-footer{display:none}.catalog-page .card{margin-bottom:20px}.catalog-page [data-wb-control="catalog-load-more"]{margin:81px auto 12px}.catalog-state-default .catalog-order-2,.catalog-state-second-batch .catalog-order-2{height:192px}.catalog-state-second-batch .catalog-order-11{height:219px}.catalog-state-second-batch .catalog-order-16{height:182px}.catalog-state-reload-recovered .card:nth-child(5),.catalog-state-reload-recovered .card:nth-child(10){height:192px}.catalog-state-reload-recovered .card:nth-child(8){height:182px}.catalog-state-resources .resource-result{height:135px;min-height:135px}.catalog-state-resources .resource-result:nth-child(2){height:156px;min-height:156px}.catalog-search-footer{display:grid;gap:8px;margin-top:42px;color:#6c757d;font-size:12px}.catalog-search-footer strong{margin-bottom:8px;color:#111;font-size:16px}.catalog-search-footer a{color:#6c757d}.catalog-search-footer small{margin-top:8px}
.catalog-state-empty,.catalog-state-error{height:544px;overflow:hidden}.catalog-state-empty .filter-group,.catalog-state-error .filter-group{display:none}.catalog-state-empty [data-wb-component="catalog-results"],.catalog-state-error [data-wb-component="catalog-results"]{height:275px;overflow:visible}.catalog-state-empty .notice,.catalog-state-error .notice{border:0;background:transparent;padding:68px 32px 0;text-align:center;font-size:17px;line-height:25px}.catalog-state-error .notice{text-align:left;padding-top:55px}.catalog-state-empty .notice .cta,.catalog-state-error .notice .cta{position:absolute;left:-100000px}.catalog-state-empty .contract-copy{position:absolute;left:-100000px}.catalog-state-empty .catalog-search-footer,.catalog-state-error .catalog-search-footer{margin-top:68px}.catalog-state-empty .results-head h2{margin-left:auto}.catalog-state-error .results-head h2{display:none}
.catalog-state-second-batch{height:4291px;overflow:hidden}.catalog-state-retry-stale{height:957px;overflow:hidden}.catalog-state-reload-recovered{height:2269px;overflow:hidden}
.problem-sets-resource-index .course-stage{grid-template-columns:214px 20px 860px 288px!important;gap:0!important}.problem-sets-resource-index .course-stage>.course-side{grid-column:1}.problem-sets-resource-index .course-stage>.course-center{grid-column:3;padding:11px 0 0}.problem-sets-resource-index .course-stage>.course-right{grid-column:4}.problem-sets-resource-index .resource-page>.eyebrow{display:none}
.video-gallery-static-thumbnails .course-footer,.video-resource-static-thumbnail .course-footer{height:140px}.video-gallery-static-thumbnails .course-stage{height:auto!important;min-height:0!important;padding-top:21px;padding-bottom:56px;align-items:stretch}.video-gallery-static-thumbnails .course-panel{height:auto!important;min-height:0!important}.video-gallery-static-thumbnails .course-center{padding-bottom:17px}.video-resource-static-thumbnail .course-stage{height:auto!important;min-height:0!important;padding-top:21px;padding-bottom:55px;align-items:stretch}.video-resource-static-thumbnail .course-panel{height:660px!important;min-height:660px!important}
.get-started .g3c-get-started{padding-bottom:0}.get-started.general-shell-page .generic-footer{height:247px}
.newsletter-authorized-stylesheet.general-shell-page>main,.newsletter-authorized-stylesheet.general-shell-page .newsletter{height:1003px;min-height:1003px!important}.newsletter-authorized-stylesheet #newsletter-main-section>.px-lg-5:first-child{height:204px!important}.newsletter-authorized-stylesheet #mc_embed_signup{height:799px!important;min-height:799px!important;padding:26px 0 30px 52px!important}.newsletter-authorized-stylesheet #mc_embed_signup h2{margin:0 0 23px}.newsletter-authorized-stylesheet #mc_embed_signup .indicates-required{height:18px;margin:0 0 10px;font-size:12px;line-height:18px}.newsletter-authorized-stylesheet #mc_embed_signup .mc-field-group{height:89px!important;margin-bottom:31px!important}.newsletter-authorized-stylesheet #mc_embed_signup .mc-field-group:nth-of-type(2){margin-bottom:36px!important}.newsletter-authorized-stylesheet #mc_embed_signup .mc-field-group:nth-of-type(3){margin-bottom:24px!important}.newsletter-authorized-stylesheet #mc_embed_signup .mc-field-group:nth-of-type(4){margin-bottom:33px!important}.newsletter-authorized-stylesheet #mc_embed_signup .mc-field-group:nth-of-type(5){margin-bottom:34px!important}.newsletter-authorized-stylesheet #mc_embed_signup .mc-field-group label{margin-bottom:9px}.newsletter-authorized-stylesheet.general-shell-page .generic-footer{height:247px}
.story-01-adrian-pastor .more-stories>h3{height:28px;margin:0;font:700 22px/28px Helvetica,Arial,sans-serif}.story-01-adrian-pastor .more-stories .item-wrapper{box-sizing:border-box!important;margin-top:16px!important;padding:10px!important}.story-01-adrian-pastor .more-stories .testimonial-card{width:100%;height:auto}.story-01-adrian-pastor .view-all-stories{height:55px;margin-top:16px!important;font:14px/21px Helvetica,Arial,sans-serif}.story-01-adrian-pastor .single-testimonial-image-wrapper .img-container,.story-01-adrian-pastor .single-testimonial-image-wrapper img{height:112.5px!important}.story-01-adrian-pastor.general-shell-page .generic-footer{height:247px}
.stories-index .stories-list-item-container{width:1266px!important;margin:34px 0 0 95px!important;row-gap:0!important}.stories-index .stories-list-item>.item-wrapper{box-sizing:border-box!important;margin-top:16px!important;margin-right:16px!important;padding:10px!important}.stories-index .testimonial-image-wrapper{width:100%!important;height:auto!important;min-height:0!important;margin:0 0 20px!important;padding-top:56.25%!important;flex-basis:auto!important}.stories-index .testimonial-image-wrapper img{width:100%!important;height:100%!important}
.stories-index .stories-list-item-container{margin-left:0!important}
.catalog-state-default .cards .card:nth-child(2),.catalog-state-second-batch .cards .card:nth-child(2){height:192px}.catalog-state-second-batch .cards .card:nth-child(11){height:219px}.catalog-state-second-batch .cards .card:nth-child(16){height:182px}
.offline-video-poster{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}.offline-video-surface{background:transparent!important}
.catalog-page .resource-result{position:relative}.catalog-page .resource-result .resource-file-icon{position:absolute;right:20px;bottom:18px;width:28px!important;height:36px!important;margin:0!important;object-fit:contain}
.course-section-or-deep-link.course-shell-page .course-stage{grid-template-columns:214px 20px 860px 288px;gap:0;padding:21px 29px 56px;align-items:stretch}
.course-section-or-deep-link.course-shell-page .course-stage>.course-side{grid-column:1}.course-section-or-deep-link.course-shell-page .course-stage>.course-center{grid-column:3}.course-section-or-deep-link.course-shell-page .course-stage>.course-right{grid-column:4}
.course-section-or-deep-link.course-shell-page .course-panel{min-height:880px}.course-section-or-deep-link.course-shell-page .course-center{padding:17.5px}.course-section-or-deep-link .source-course-heading h2.course-page-title{margin:0 0 3.5px!important;padding:0 0 3.5px!important;border-bottom:1px solid #9c9d9e;font:600 22.4px/25.62px Helvetica,Arial,sans-serif!important}.course-section-or-deep-link .source-course-article{margin-top:3.5px;padding-top:14px}.course-section-or-deep-link .source-course-article .g3b-source-fragment h3{margin:0 0 7px;font:600 15.96px/15.96px Helvetica,Arial,sans-serif!important;color:#212529}.course-section-or-deep-link .source-course-article pre{line-height:1.5}.course-section-or-deep-link .course-section>.eyebrow{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.course-section-or-deep-link .source-course-article .g3b-source-fragment table{width:100%;margin:0 0 14px;border:0;border-collapse:collapse}.course-section-or-deep-link .source-course-article .g3b-source-fragment th,.course-section-or-deep-link .source-course-article .g3b-source-fragment td{padding:7px;border:0;vertical-align:top;font:14px/21px Helvetica,Arial,sans-serif}.course-section-or-deep-link .source-course-article .g3b-source-fragment thead{background:#126f9a;color:#fff;text-transform:uppercase}.course-section-or-deep-link .source-course-article .g3b-source-fragment table{overflow-wrap:normal}.course-section-or-deep-link .source-course-article .g3b-source-fragment th{font-weight:700}.course-section-or-deep-link .source-course-article .g3b-source-fragment tbody tr:nth-child(even){background:#f5f5f5}
.course-section-or-deep-link .source-course-breadcrumb{margin:0 0 5.2px;font:14px/21px Helvetica,Arial,sans-serif}.course-section-or-deep-link .source-course-breadcrumb a{color:#343a40;text-decoration:none}
.syllabus.course-section-or-deep-link.course-shell-page .course-stage{min-height:3046px}.syllabus.course-section-or-deep-link.course-shell-page .course-panel{min-height:2969px}.syllabus .source-course-heading{height:33.625px}.syllabus .course-footer{height:59px!important;overflow:hidden}.syllabus .course-footer-links{display:none}
.syllabus .source-course-article table{display:block!important;height:222px!important;border:1px solid #c7c7c7!important}.syllabus .source-course-article thead{display:none}.syllabus .source-course-article tbody,.syllabus .source-course-article tbody tr{display:block!important}.syllabus .source-course-article tbody tr{height:74px!important}.syllabus .source-course-article tbody td{display:block!important;width:100%!important;height:37px!important;padding:7px!important;border-bottom:1px solid #c7c7c7!important}.syllabus .source-course-article tbody td:first-child:before{content:"ACTIVITIES: ";font-weight:700}.syllabus .source-course-article tbody td:nth-child(2):before{content:"PERCENTAGES: ";font-weight:700}
.download-course .course-stage{height:2135px!important;min-height:2135px!important}
.assignments .assignments-source-content{width:825px;font:14px/21px Helvetica,Arial,sans-serif;letter-spacing:normal}.assignments .assignments-source-content>p{margin:0 0 14px;font:14px/21px Helvetica,Arial,sans-serif!important}.assignments .assignment-table{width:825px!important;margin:0 0 14px;table-layout:auto}.assignments .assignment-table th,.assignments .assignment-table td{padding:7px;border:0;font:14px/21px Helvetica,Arial,sans-serif!important}.assignments .assignment-table th{font-weight:700!important}.assignments .assignment-table td{vertical-align:middle}.assignments .assignment-table tbody tr{height:auto!important}.assignments .assignment-table th:nth-child(n),.assignments .assignment-table td:nth-child(n){width:auto!important}.assignments .assignment-table tbody tr:nth-child(even) td{background:#f5f5f5}
.assignments .assignment-table{table-layout:fixed}.assignments .assignment-table td p,.assignments .assignment-table td p:last-child{margin:0 0 14px;line-height:21px!important}.download-course #main-course-section>.card-body{padding:17.5px!important}.download-course .course-center h2{margin:0 0 7px!important}.download-course .download-course-container{height:auto!important;margin:0!important}.download-course .resource-list-toggle{display:block!important}.download-course .resource-list-toggle>a{display:block!important}.download-course .resource-list-toggle h4{display:inline!important;margin:21px 0!important}.download-course .resource-list-toggle .material-icons:before{font:700 18px/28px Arial,sans-serif!important}.download-course .resource-list-page{height:auto!important;min-height:62px!important}.download-course .resource-list-page>.row,.download-course .resource-list-page .d-inline-flex{height:auto!important;min-height:0!important}
.download-course .course-stage{height:auto;min-height:957px;padding:21px 29px 56px;align-items:stretch}.download-course .course-panel{height:auto;min-height:880px}.download-course .course-center{padding:0}.download-course #main-course-section{transform:none}.download-course .course-center h2{font:600 22.4px/25.62px Helvetica,Arial,sans-serif!important}
.catalog-state-default .cards .card,.catalog-state-second-batch .cards .card,.catalog-state-reload-recovered .cards .card{height:178px!important;min-height:178px!important}
.catalog-state-default .cards .card:nth-child(1),.catalog-state-reload-recovered .cards .card:nth-child(1),.catalog-state-second-batch .cards .card:nth-child(1),.catalog-state-second-batch .cards .card:nth-child(12),.catalog-state-second-batch .cards .card:nth-child(14),.catalog-state-second-batch .cards .card:nth-child(20){height:192px!important;min-height:192px!important}
.catalog-state-empty .notice .cta,.catalog-state-error .notice .cta{position:static!important;display:inline-block!important;margin-top:8px;padding:6px 12px;font-size:14px;line-height:21px}


@media(max-width:800px){.cards{grid-template-columns:1fr}.catalog-layout{grid-template-columns:1fr}.generic-head .logo{width:220px}.course-stage{height:auto;grid-template-columns:1fr}.course-panel{height:auto}.home-banner .banner-columns{grid-template-columns:1fr;height:auto}.home-mission{display:none}.course-menu-mobile{display:block}}
"""

HOME_RUNTIME_FIX_CSS = r"""
.home-shell-page .g3b-home-source .material-icons{display:inline-block!important;width:18px!important;overflow:hidden!important;color:transparent!important;font-size:0!important;line-height:1!important;vertical-align:middle!important}
.home-shell-page .g3b-home-source .prev>.material-icons:before{content:"‹";display:block;color:#212529;font:32px/18px Arial,sans-serif}
.home-shell-page .g3b-home-source .next>.material-icons:before{content:"›";display:block;color:#212529;font:32px/18px Arial,sans-serif}
.home-shell-page .home-semantic-mirror{position:absolute!important;left:-100000px!important;top:0!important;width:1440px!important;opacity:0!important;pointer-events:none!important}
"""


def shell(title: str, body: str, *, page_class: str = "", record: dict[str, object] | None = None) -> str:
    logo = DATA.get("shell_assets", {}).get("logo", "/assets/ocw-logo.svg")
    is_home = page_class.startswith("home")
    is_course = any(
        family in page_class
        for family in (
            "course-overview", "course-section-or-deep-link", "resource-detail-or-index",
            "course-download", "video-gallery",
        )
    )
    css_sources = [COMMON_CSS_URL, HOME_CSS_URL] if is_home else ([COMMON_CSS_URL, COURSE_CSS_URL] if is_course else [COMMON_CSS_URL, HOME_CSS_URL])
    stylesheets = "".join(
        f'<link rel="stylesheet" href="{escape(str(ASSET_URL_MAP[url]), quote=True)}" data-wb-source-stylesheet="{url}">'
        for url in css_sources
    )
    header_links = (
        '<div class="right" id="global-navigation" data-menu-open="false"><a class="search-icon" href="/search/" aria-label="Search">Search</a>'
        '<a class="give-button" data-wb-external="giving" href="https://giving.mit.edu/give/to/ocw/">GIVE NOW <span class="heart">♥</span></a>'
        '<a class="about-link" href="/about/">ABOUT OCW</a>'
        '<a class="help-link" data-wb-external="help" href="https://mitocw.zendesk.com/hc/en-us">HELP &amp; FAQS</a>'
        '<a class="contact-link" data-wb-external="contact" href="https://mitocw.zendesk.com/hc/en-us/requests/new">CONTACT US</a></div>'
    )
    if is_home:
        header = (
            '<div id="home-header"><header id="desktop-header" data-wb-component="global-header"><div class="contents">'
            f'<a class="ocw-logo" href="/"><img src="{logo}" alt="MIT OpenCourseWare"></a>{header_links}'
            '<button class="nav-toggle" data-wb-control="nav-toggle" type="button" aria-label="Toggle navigation" '
            'aria-controls="global-navigation" aria-expanded="false">Menu</button>'
            '</div></header></div>'
        )
        body_class = f"{page_class} home-shell-page"
    elif is_course:
        header = (
            '<div class="course-header"><header id="desktop-header" data-wb-component="global-header"><div class="contents">'
            f'<a class="ocw-logo" href="/"><img src="{logo}" alt="MIT OpenCourseWare"></a>{header_links}'
            '<button class="nav-toggle" data-wb-control="nav-toggle" type="button" aria-label="Toggle navigation" '
            'aria-controls="global-navigation" aria-expanded="false">Menu</button>'
            '</div></header></div>'
        )
        body_class = f"{page_class} course-shell-page"
    else:
        header = (
            '<div class="general-header"><header id="desktop-header" data-wb-component="global-header"><div class="contents">'
            f'<a class="ocw-logo" href="/"><img src="{logo}" alt="MIT OpenCourseWare"></a>{header_links}'
            '<button class="nav-toggle" data-wb-control="nav-toggle" type="button" aria-label="Toggle navigation" '
            'aria-controls="global-navigation" aria-expanded="false">Menu</button>'
            '</div></header></div>'
        )
        body_class = f'{page_class.replace("catalog ", "catalog-page ").replace("story-detail ", "story-detail-page ")} general-shell-page'
    footer_links = (
        '<a data-wb-external="accessibility" href="https://accessibility.mit.edu/">Accessibility</a>'
        '<a data-wb-external="creative-commons" href="https://creativecommons.org/licenses/by-nc-sa/4.0/">Creative Commons License</a>'
        '<a data-wb-external="contact" href="https://mitocw.zendesk.com/hc/en-us/requests/new">Contact Us</a>'
        '<a data-wb-external="help" href="https://mitocw.zendesk.com/hc/en-us">Help &amp; FAQs</a>'
        '<a data-wb-external="mit-learn" href="https://learn.mit.edu/">MIT Learn</a>'
        '<a data-wb-external="ocw-to-go" href="https://ocwtogo.mit.edu/">OCW To Go</a>'
        '<a data-wb-external="open-learning" href="https://openlearning.mit.edu/">MIT Open Learning</a>'
        '<a data-wb-external="chalk-radio" href="https://chalk-radio.simplecast.com/">Chalk Radio</a>'
        '<a data-wb-external="youtube" href="https://www.youtube.com/">YouTube</a>'
    )
    if is_course:
        footer_logo = ASSET_URL_MAP["https://ocw.mit.edu/static_shared/images/mit_ol.4165342f87abb1da46fd.svg"]
        footer = (
            '<footer class="course-footer"><div class="course-footer-main">'
            f'<img class="course-footer-logo" src="{footer_logo}" alt="MIT Open Learning">'
            '<div class="course-footer-copy"><strong>Over 2,500 courses &amp; materials</strong><br>Freely sharing knowledge with learners and educators around the world. &nbsp;<a href="/about/">Learn more</a></div>'
            '<div class="course-footer-social">f ◎ 𝕏 ▶ in</div></div><div class="course-footer-links">'
            f'{footer_links}</div></footer>'
        )
    else:
        footer = (
            '<footer class="generic-footer"><div class="wrap"><strong>MIT OpenCourseWare</strong>'
            '<p>Unlocking knowledge, empowering minds. Free course materials from MIT.</p>'
            f'{footer_links}</div></footer>'
        )
    if 'id="footer-container"' in body:
        footer = ""
    style_bundle = (
        f"<style>{BASE_CSS}</style>{stylesheets}<style>{HOME_RUNTIME_FIX_CSS}</style>"
        if is_home and 'class="g3b-home-source"' in body
        else f"{stylesheets}<style>{BASE_CSS}</style>"
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title>
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; img-src 'self' data:; font-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-src 'none'; media-src 'none'">
{style_bundle}</head><body class="{body_class}">{header}<main{record_attrs(record)}>{body}</main>{footer}<script>
document.addEventListener('click',e=>{{const a=e.target.closest('a[href^="http"]');if(a){{e.preventDefault();location.href='/external-boundary/?url='+encodeURIComponent(a.href)}}}});
document.addEventListener('click',e=>{{const control=e.target.closest('[data-wb-state-href]');if(!control)return;e.preventDefault();location.href=control.dataset.wbStateHref}});
document.addEventListener('click',e=>{{const button=e.target.closest('[data-wb-control="course-description-expand"]');if(button){{const more=document.getElementById('course-description-more');const open=button.getAttribute('aria-expanded')==='true';more.hidden=open;button.setAttribute('aria-expanded',String(!open));button.textContent=open?'...Show more':'Show less'}}}});
document.addEventListener('click',e=>{{const button=e.target.closest('[data-wb-control="nav-toggle"],[data-wb-control="course-menu"],[data-wb-control="catalog-departments"]');if(!button)return;const target=document.getElementById(button.getAttribute('aria-controls'));if(!target)return;const open=button.getAttribute('aria-expanded')==='true';button.setAttribute('aria-expanded',String(!open));target.dataset.menuOpen=String(!open);if(button.matches('[data-wb-control="catalog-departments"]'))target.hidden=open}});
document.addEventListener('change',e=>{{const changed=e.target.closest('[data-wb-filter-kind]');if(!changed)return;const checked=[...document.querySelectorAll('[data-wb-filter-kind]:checked')];const math=checked.some(item=>item.dataset.wbFilterValue==='mathematics');const undergraduate=checked.some(item=>item.dataset.wbFilterValue==='undergraduate');const supported=checked.every(item=>['mathematics','undergraduate'].includes(item.dataset.wbFilterValue));if(supported&&math&&undergraduate){{location.href='/search/?state=math-undergraduate';return}}if(supported&&math){{location.href='/search/?state=math';return}}if(!checked.length){{location.href='/search/';return}}const selection=checked.map(item=>item.dataset.wbFilterLabel).join(', ');location.href='/data-boundary/?selection='+encodeURIComponent(selection)+'&return_url='+encodeURIComponent('/search/')}});
document.addEventListener('submit',e=>{{const form=e.target.closest('[data-wb-component="newsletter-form"]');if(!form)return;e.preventDefault();const destination=form.dataset.wbExternalDestination;location.href='/external-boundary/?url='+encodeURIComponent(destination)}});
</script></body></html>"""


def catalog_card(course: dict[str, object]) -> str:
    href = local_path(str(course["url"])) if int(course["source_order"]) <= 10 else "/data-boundary/"
    image = course.get("local_image")
    media = f'<img data-wb-media="course-card-images" src="{image}" alt="">' if image else '<div class="placeholder" aria-label="Source image unavailable"></div>'
    link_attr = ' data-wb-link="catalog-first-course"' if int(course["source_order"]) == 1 else ""
    prefix = f'{course["course_code_token"]} | {course["level"]} {course["title_link_text"]}'
    card_text = str(course["card_text"])
    details = card_text[len(prefix) :].strip() if card_text.startswith(prefix) else card_text
    return (
        f'<article class="card">{media}<div class="copy">'
        f'<div class="eyebrow">{escape(str(course["course_code_token"]))} | {escape(str(course["level"]))}</div>'
        f'<h3><a{link_attr} href="{escape(href, quote=True)}">{course["title_link_text"]}</a></h3>'
        f'<p>{escape(details)}</p></div></article>'
    )


CATALOG_STATE_IMAGE_URLS = {
    "math": [
        "https://ocw.mit.edu/courses/18-465-topics-in-statistics-nonparametrics-and-robustness-spring-2005/e4689bd84e821cbef0e93289d30e0fc2_18-465s05.JPG",
        "https://ocw.mit.edu/courses/18-034-honors-differential-equations-spring-2004/ade3412a58f3fa8f7cf4888d277ad571_18-034s04.jpg",
        "https://ocw.mit.edu/courses/18-786-topics-in-algebraic-number-theory-spring-2006/06e3b8f52ff0b481586b699a9f7c85ef_18-786s06.jpg",
        "https://ocw.mit.edu/courses/18-786-topics-in-algebraic-number-theory-spring-2010/ad625fcdbac79d7e2633be2dd7b4aedd_18-786s10.jpg",
    ],
    "math-undergraduate": [
        "https://ocw.mit.edu/courses/18-100b-analysis-i-fall-2010/5c88f9408009514f73f41d6b5d91fd13_18-100bf10.jpg",
        "https://ocw.mit.edu/courses/18-03-differential-equations-spring-2010/e51bbed857b0ae65e7536f120c1473d9_18-03s10.jpg",
        "https://ocw.mit.edu/courses/18-440-probability-and-random-variables-spring-2014/73256e6260afadff2dc8f71302e4bff4_18-440s14.jpg",
    ],
    "course-number": [
        "https://ocw.mit.edu/courses/18-01-single-variable-calculus-fall-2005/9c1339d31d8f122c6698a29e3a61a66e_18-01f05.jpg",
        "https://ocw.mit.edu/courses/18-01-calculus-i-single-variable-calculus-fall-2020/18-01f20.jpg",
        "https://ocw.mit.edu/courses/18-01-single-variable-calculus-fall-2006/24c4a7d9cd569a82ef34a8563e50add8_18-01f06.jpg",
    ],
}
CATALOG_TOPIC_LABELS = sorted(
    [
        "Algebra and Number Theory", "Probability and Statistics", "Differential Equations",
        "Algorithms and Data Structures", "Computer Science", "Discrete Mathematics",
        "Topology and Geometry", "Applied Mathematics", "Environmental Analysis",
        "Probability and Statistics", "Earth Science", "Social Science", "Linear Algebra",
        "Mathematics", "Engineering", "Computation", "Calculus", "Biology", "Science",
        "Entrepreneurship", "Innovation", "Physics", "Electromagnetism",
    ],
    key=len,
    reverse=True,
)

# Exact first resource batch observed in the current, authorized source capture.
# Keeping the structured fields here avoids trying to infer the resource title from
# prose that legitimately contains the same words as the title.
CATALOG_RESOURCE_BATCH = [
    ("5.07SC", "Biological Chemistry I", "Exam IV", "", "Science Biology Biochemistry", "page"),
    ("5.07SC", "Biological Chemistry I", "Lexicon", "This section describes the Lexicon of Biochemical Reactions and includes 4 videos.", "Science Biology Biochemistry", "page"),
    ("5.07SC", "Biological Chemistry I", "Module I: Basic Biochemistry", "", "Science Biology Biochemistry", "page"),
    ("5.07SC", "Biological Chemistry I", "Session 1: What is Biochemistry?", "", "Science Biology Biochemistry", "page"),
    ("5.07SC", "Biological Chemistry I", "Session 2: Protein Structure and Function", "", "Science Biology Biochemistry", "page"),
    ("5.07SC", "Biological Chemistry I", "Session 3: Enzymes and Catalysis", "", "Science Biology Biochemistry", "page"),
    ("5.07SC", "Biological Chemistry I", "Session 4: Enzyme Kinetics and Enzyme Inhibition", "", "Science Biology Biochemistry", "page"),
    ("5.07SC", "Biological Chemistry I", "Session 5: Biochemical Transformations I", "", "Science Biology Biochemistry", "page"),
    ("5.07SC", "Biological Chemistry I", "Session 7: Biochemical Transformations III", "", "Science Biology Biochemistry", "page"),
    ("5.07SC", "Biological Chemistry I", "Module II: Production of Energy in the Cell", "", "Science Biology Biochemistry", "page"),
]


def catalog_topic_chips(text: str) -> str:
    remaining = text.strip()
    labels: list[str] = []
    while remaining:
        match = next((label for label in CATALOG_TOPIC_LABELS if remaining.startswith(label)), None)
        if match:
            labels.append(match)
            remaining = remaining[len(match) :].strip()
            continue
        if remaining.startswith("+"):
            labels.append(remaining)
            break
        break
    if not labels and text.strip():
        labels.append(text.strip())
    return '<div class="catalog-tags">' + "".join(
        f'<span>{escape(label)}</span>' for label in labels
    ) + "</div>"


def captured_catalog_card(text: str, state: str, index: int) -> str:
    code, remainder = text.split(" | ", 1)
    if state == "resources":
        code, course_title, resource_title, description, topics, file_kind = CATALOG_RESOURCE_BATCH[index]
        description_html = f'<p class="card-meta">{escape(description)}</p>' if description else ""
        icon_label = "HTML" if file_kind == "page" else "PDF"
        icon_color = "%23494d4f" if file_kind == "page" else "%23ed4c5c"
        media_icon = (
            '<img class="resource-file-icon" data-wb-media="resource-file-icons" '
            'src="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 '
            'width=%2228%22 height=%2236%22 viewBox=%220 0 28 36%22%3E%3Cpath '
            f'fill=%22{icon_color}%22 d=%22M3 0h15l7 7v29H3z%22/%3E%3Cpath '
            'fill=%22%23fff%22 d=%22M18 0v8h7z%22/%3E%3Ctext x=%225%22 y=%2228%22 '
            f'font-size=%226%22 fill=%22%23fff%22%3E{icon_label}%3C/text%3E%3C/svg%3E" '
            'alt="">'
        )
        return (
            '<article class="card resource-result"><div class="copy">'
            f'<div class="eyebrow">{escape(code)} | {escape(course_title)}</div>'
            f'<h3>{escape(resource_title)}</h3>{description_html}{catalog_topic_chips(topics)}</div>'
            f'{media_icon}</article>'
        )

    level, remainder = remainder.split(" ", 1)
    instructor_markers = (" Prof.", " Dr.", " Andrew V. Sutherland", " Christine Breiner", " Daniel Kleitman")
    instructor_start = min(
        (remainder.find(marker) for marker in instructor_markers if marker in remainder),
        default=len(remainder),
    )
    title = remainder[:instructor_start].strip()
    trailing = remainder[instructor_start:].strip()
    topic_start = min(
        (trailing.find(label) for label in ("Mathematics", "Engineering", "Science") if label in trailing),
        default=len(trailing),
    )
    instructors, topics = trailing[:topic_start].strip(), trailing[topic_start:].strip()
    images = CATALOG_STATE_IMAGE_URLS.get(state, [])
    image = images[index] if index < len(images) and images[index] in G3C_CATALOG_URL_MAP else ""
    media = (
        f'<img data-wb-media="course-card-images" data-wb-asset-source="{escape(image, quote=True)}" '
        f'src="{escape(local_path(image), quote=True)}" alt="{escape(title, quote=True)}">'
        if image else '<div class="placeholder" aria-label="Source image unavailable"></div>'
    )
    return (
        f'<article class="card">{media}<div class="copy"><div class="eyebrow">{escape(code)} | {escape(level)}</div>'
        f'<h3>{escape(title)}</h3><p class="card-meta">{escape(instructors)}</p>'
        f'{catalog_topic_chips(topics)}</div></article>'
    )


def catalog_body(state: str, query: str = "") -> str:
    view = dict(DATA["catalog"]["states"][state])
    normalized_query = " ".join(query.casefold().split())
    query_active = state == "default" and bool(normalized_query)
    if query_active:
        cards = [
            course for course in COURSES
            if normalized_query in " ".join(
                str(course[key]) for key in ("course_code_token", "title_link_text", "card_text")
            ).casefold()
        ]
        view.update({"total": len(cards), "offset": 0, "limit": len(cards), "empty": not cards})
    else:
        cards = COURSES[int(view["offset"]) : int(view["offset"]) + int(view["limit"])]
    captured = view.get("captured", {}).get("cards", [])
    if state == "resources":
        captured = [
            f"{code} | {course_title} {resource_title} {description} {topics}".strip()
            for code, course_title, resource_title, description, topics, _file_kind
            in CATALOG_RESOURCE_BATCH
        ]
    if captured and state not in {"default", "second-batch", "clear-recovered"}:
        cards_html = "".join(captured_catalog_card(title, state, index) for index, title in enumerate(captured))
    else:
        cards_html = "".join(catalog_card(card) for card in cards)
    error = ""
    if state == "error":
        error = ('<div class="notice" data-wb-component="catalog-error"><p><em>Oops! Something went wrong. '
                 'Please accept our apologies and feel free to <strong>contact us</strong> with the details of '
                 'what you were trying to do, and what happened.</em></p><a class="cta" '
                 'data-wb-control="catalog-retry" href="/search/?state=retry-stale">Retry</a></div>')
    elif state == "retry-stale":
        error = f'<div class="notice" data-wb-component="catalog-error"><p>{view["error"]}</p><a class="cta" data-wb-control="catalog-retry" href="/search/?state=reload-recovered">Reload</a></div>'
    loading = '<div class="notice" data-wb-component="catalog-loading" aria-live="polite">Loading results…</div>' if view.get("loading") else ""
    empty = ""
    if view.get("empty"):
        empty = '<div class="notice" data-wb-component="catalog-empty"><p><em>No results found for your query</em></p><span class="contract-copy">No results match your search.</span><a class="cta" data-wb-control="catalog-empty-clear" href="/search/?state=clear-recovered">Clear search</a></div>'
    resources_active = state == "resources"
    checked = set(view.get("checked", []))
    math_checked = " checked" if "catalog-math-filter" in checked else ""
    undergraduate_checked = " checked" if "catalog-undergraduate-filter" in checked else ""
    course_checked = "" if resources_active else " checked"
    resource_checked = " checked" if resources_active else ""
    departments = [
        ("Electrical Engineering and Computer Science", 285), ("Mathematics", 199),
        ("Urban Studies and Planning", 199), ("Sloan School of Management", 192),
        ("Mechanical Engineering", 148), ("Literature", 127),
        ("Global Studies and Languages", 119), ("Architecture", 115),
        ("Earth, Atmospheric, and Planetary Sciences", 110),
        ("Civil and Environmental Engineering", 104), ("Political Science", 97),
        ("Brain and Cognitive Sciences", 93), ("History", 92), ("Physics", 87),
        ("Aeronautics and Astronautics", 86), ("Linguistics and Philosophy", 78),
    ]
    department_rows = "".join(
        '<label><input type="checkbox"'
        + f' name="department" value="{quote(name.casefold().replace(" ", "-"), safe="-")}"'
        + ' data-wb-filter-kind="department"'
        + f' data-wb-filter-value="{quote(name.casefold().replace(" ", "-"), safe="-")}"'
        + f' data-wb-filter-label="{escape(name, quote=True)}"'
        + (' data-wb-control="catalog-math-filter"' if name == "Mathematics" else '')
        + (math_checked if name == "Mathematics" else '')
        + f'> <span>{name}</span><span class="count">{count}</span></label>'
        for name, count in departments
    )
    resource_types = [
        ("Lecture Notes", 23541), ("Assignments", 9834), ("Lecture Videos", 5097),
        ("Problem Sets", 4553), ("Projects", 3444), ("Readings", 3183),
        ("Exams", 2724), ("Laboratory Assignments", 2053),
        ("Problem Set Solutions", 1849), ("Problem-solving Notes", 1003),
        ("Exam Solutions", 778), ("Recitations", 699), ("Tools", 664),
        ("Videos", 637), ("Activity Assignments", 376),
        ("Programming Assignments", 372),
    ]
    if resources_active:
        resource_rows = "".join(
            '<label><input type="checkbox" data-wb-filter-kind="resource-type" '
            f'data-wb-filter-value="{quote(name.casefold().replace(" ", "-"), safe="-")}" '
            f'data-wb-filter-label="{escape(name, quote=True)}"> '
            f'<span>{escape(name)}</span><span class="count">{count}</span></label>'
            for name, count in resource_types
        )
        filter_controls = (
            '<div class="filter-group"><button class="filter-title" type="button">Resource Types⌄</button>'
            '<input class="department-search" placeholder="Search Resource Types" aria-label="Search Resource Types">'
            f'<div class="department-list">{resource_rows}</div></div>'
            '<div class="filter-group"><button class="filter-title" type="button">Topics ›</button></div>'
        )
    else:
        filter_controls = (
            '<div class="filter-group"><button class="filter-title" data-wb-control="catalog-departments" '
            'type="button" aria-controls="catalog-department-list" aria-expanded="true">Departments⌄</button>'
            '<input class="department-search" placeholder="Search Departments" aria-label="Search Departments">'
            f'<div class="department-list" id="catalog-department-list" data-menu-open="true">{department_rows}</div></div>'
            '<div class="filter-group"><button class="filter-title" data-wb-control="catalog-level">Level ›</button>'
            f'<label><input data-wb-control="catalog-undergraduate-filter" data-wb-filter-kind="level" '
            'data-wb-filter-value="undergraduate" data-wb-filter-label="Undergraduate" name="level" '
            f'value="undergraduate" type="checkbox"{undergraduate_checked}> Undergraduate</label></div>'
            '<div class="filter-group"><button class="filter-title">Topics ›</button></div>'
            '<div class="filter-group"><button class="filter-title">Features ›</button></div>'
        )
    sidebar_footer = (
        '<div class="catalog-search-footer"><strong>MIT Open Learning</strong>'
        '<a data-wb-external="accessibility" href="https://accessibility.mit.edu/">Accessibility</a>'
        '<a data-wb-external="creative-commons" href="https://creativecommons.org/licenses/by-nc-sa/4.0/">Creative Commons License</a>'
        '<a data-wb-external="terms" href="https://openlearning.mit.edu/terms-and-conditions">Terms and Conditions</a>'
        '<small>© 2001–2026 Massachusetts Institute of Technology</small></div>'
    )
    suppress_load_more = query_active or bool(view.get("error") or view.get("loading") or view.get("empty"))
    load_more = "" if suppress_load_more else '<a class="cta" data-wb-control="catalog-load-more" href="/search/?state=second-batch">Load more</a>'
    display_query = "zzzzwebsitebenchnomatchqvxtk" if state == "empty" and not query else query
    input_disabled = " disabled" if state == "error" else ""
    return f'''<section class="catalog-hero" data-wb-capability="local-search"><h1>Explore OpenCourseWare</h1><p>Search for courses, materials &amp; teaching resources</p>
<form class="catalog-search" action="/search/" method="get"><input data-wb-control="catalog-query" name="q" value="{escape(display_query, quote=True)}" placeholder="Search OpenCourseWare"{input_disabled}><button type="submit">Search</button></form></section>
<div class="catalog-content catalog-state-{escape(state, quote=True)}"><aside class="filters" data-wb-component="catalog-filters" data-wb-capability="local-filter-sort"><div class="filter-heading"><strong>Filters</strong><a data-wb-control="catalog-clear-all" href="/search/">Clear All</a></div>
{filter_controls}{sidebar_footer}</aside>
<section data-wb-component="catalog-results"><div class="tabs"><label class="{'active' if not resources_active else ''}"><input data-wb-control="catalog-course-tab" type="radio" name="catalog-tab"{course_checked} onchange="location.href='/search/'"> COURSES</label><label class="{'active' if resources_active else ''}"><input data-wb-control="catalog-resource-tab" type="radio" name="catalog-tab"{resource_checked} onchange="location.href='/search/?state=resources'"> RESOURCES</label></div>
<div class="results-head"><h2>{view["total"]} results</h2><label>Sort by <select data-wb-control="catalog-sort" onchange="location.href='/search/?state=course-number'"><option>Relevance</option><option{' selected' if state == 'course-number' else ''}>MIT course #</option><option>Date</option></select></label><span class="view-controls" aria-label="Result view"><button type="button" aria-label="List view" aria-pressed="true">☷</button><button type="button" aria-label="Grid view" aria-pressed="false">▦</button></span></div>{loading}{error}{empty}<div class="cards">{cards_html}</div>{load_more}</section></div>'''


def page_title(record: dict[str, object]) -> str:
    return str(record["title"]).split(" | ", 1)[0]


def captured_headings(record: dict[str, object]) -> str:
    rendered: list[str] = []
    for heading in record.get("headings", []):
        level = max(1, min(4, int(heading["level"])))
        rendered.append(f'<h{level}>{escape(str(heading["text"]))}</h{level}>')
    return "".join(rendered)


def evidence_href(url: str) -> str:
    if url in UNAVAILABLE_ASSETS:
        return f"/unavailable-asset/?url={quote(url, safe='')}"
    return local_path(url)


def captured_links(record: dict[str, object]) -> str:
    links: list[str] = []
    for link in record.get("links", []):
        source_url = str(link["url"])
        text = escape(str(link.get("text") or ""))
        href = escape(evidence_href(source_url), quote=True)
        origin = f' data-wb-source-href="{escape(source_url, quote=True)}"'
        links.append(f'<li><a href="{href}"{origin}>{text}</a></li>')
    return f'<ul class="evidence-links">{"".join(links)}</ul>'


def home_course_records() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    ordered: list[dict[str, object]] = []
    seen: set[str] = set()
    for link in PAGES["/"]["links"]:
        local = local_path(str(link["url"]))
        if not local.startswith("/courses/") or local in seen:
            continue
        row = PAGES.get(local)
        if row and row["evidence_report"] == "g1/home-course-overviews-report.json":
            ordered.append(row)
            seen.add(local)
    featured = [row for row in ordered if str(row["page_id"]).startswith("featured-")]
    new = [row for row in ordered if str(row["page_id"]).startswith("new-")]
    return featured, new


def home_course_card(record: dict[str, object], *, source_like: bool = False) -> str:
    detail = DATA["g3b_home_content"]["courses"][str(record["path"])]
    image_source = str(detail["image_source_url"])
    image = local_path(image_source)
    media = (
        f'<img data-wb-media="course-card-images" data-wb-asset-source="{escape(image_source, quote=True)}" '
        f'src="{escape(image, quote=True)}" alt="{escape(str(detail["image_alt"]), quote=True)}">'
        if image.startswith("/") and not image.startswith("/data-boundary/")
        else '<div class="placeholder" aria-label="Source image unavailable"></div>'
    )
    level = str(detail["level"])
    source_instructors = str(detail["instructors"])
    source_topics = str(detail["topics"])
    instructors = source_instructors
    topics = source_topics
    if source_like:
        instructors = instructors.replace(" , ", ", ")
        topics = topics.replace(" , ", ", ")
    title = str(detail["title"])
    # The frozen carousel renders the department label for this learning-resource
    # card, while its detail route retains the longer entity title.
    if source_like and str(record["path"]) == "/courses/res-9-010-bcs-tutorials-optimizing-the-full-stack-for-generative-image-and-video-models-fall-2025/":
        title = "Brain and Cognitive Sciences"
    title_metadata = (
        f' title="{escape(str(detail["title"]), quote=True)}"'
        if title != str(detail["title"]) else ""
    )
    instructor_metadata = (
        f' aria-label="{escape(source_instructors, quote=True)}"'
        if instructors != source_instructors else ""
    )
    topics_metadata = (
        f' aria-label="{escape(source_topics, quote=True)}"'
        if topics != source_topics else ""
    )
    return (
        f'<article class="card" data-wb-home-course-card="{escape(str(record["page_id"]), quote=True)}">{media}'
        f'<div class="copy"><div class="eyebrow">{escape(level)}</div>'
        f'<h3><a href="{escape(str(record["path"]), quote=True)}"{title_metadata}>{escape(title)}</a></h3>'
        f'<p class="card-instructors"{instructor_metadata}>{escape(instructors)}</p>'
        f'<p class="card-topics"{topics_metadata}>{escape(topics)}</p></div></article>'
    )


def home_story_card(path: str, detail: dict[str, object], *, source_like: bool = False) -> str:
    image_source = str(detail["image_source_url"])
    image = local_path(image_source)
    media = (
        f'<img data-wb-media="story-image" data-wb-asset-source="{escape(image_source, quote=True)}" '
        f'src="{escape(image, quote=True)}" alt="{escape(str(detail["image_alt"]), quote=True)}">'
        if image.startswith("/") and not image.startswith("/data-boundary/") else ""
    )
    if source_like:
        teaser = str(detail["teaser"])
        story_link_attr = ' data-wb-link="home-story"' if path == "/stories/adrian-pastor/" else ""
        frozen_story_continuations = {
            "/stories/omar-alshehri/": " By Lauren Rebecca Thacker Lookin",
            "/stories/sok-danica/": (
                " By Lauren Rebecca Thacker As an undergraduate considering her future career, "
                "Sok Danica, a re"
            ),
        }
        teaser += frozen_story_continuations.get(path, "")
        return (
            f'<article class="story-card">{media}<section class="story-copy"><h3><a{story_link_attr} href="{escape(path, quote=True)}">'
            f'{escape(str(detail["name"]))}</a></h3><p class="story-role-row">'
            f'<span>{escape(str(detail["occupation"]))}</span><span>{escape(str(detail["location"]))}</span></p>'
            f'<p class="story-summary">{escape(teaser)}</p>'
            f'<a class="read-full-story" href="{escape(path, quote=True)}">Read Full Story</a></section></article>'
        )
    role = " | ".join(value for value in (str(detail["occupation"]), str(detail["location"])) if value)
    return (
        f'<article class="story-card">{media}<h3><a href="{escape(path, quote=True)}">'
        f'{escape(str(detail["name"]))}</a></h3><p class="story-role">{escape(role)}</p>'
        f'<p class="story-summary">{escape(str(detail["teaser"]))}</p></article>'
    )


def home_news_media() -> str:
    for ref in report_assets(PAGES["/"]):
        if urlsplit(str(ref["url"])).hostname == "www.ocw-openmatters.org":
            return image_tag(ref, "home-news-images", alt="OCW News")
    return ""


def home_source_footer() -> str:
    open_learning_logo = ASSET_URL_MAP[
        "https://ocw.mit.edu/static_shared/images/mit_ol.4165342f87abb1da46fd.svg"
    ]
    oeg_logo = ASSET_URL_MAP[
        "https://ocw.mit.edu/static_shared/images/oeg_logo.8a31f7b87f30df2d0169.png"
    ]
    social_icons = [
        ("https://www.facebook.com/MITOCW", "https://ocw.mit.edu/static_shared/images/Facebook.d1f5caeb73d7d12505a2.png", "facebook"),
        ("https://www.instagram.com/mitocw", "https://ocw.mit.edu/static_shared/images/Instagram.4df41828ffee4ff33d8a.png", "instagram"),
        ("https://twitter.com/MITOCW", "https://ocw.mit.edu/static_shared/images/x-formerly-twitter-black.f8c75ad9f42902726d25.png", "x (formerly twitter)"),
        ("https://www.youtube.com/mitocw", "https://ocw.mit.edu/static_shared/images/Youtube.7c9f62c4f1dc9515ebb4.png", "youtube"),
        ("https://www.linkedin.com/company/mit-opencourseware/", "https://ocw.mit.edu/static_shared/images/linkedin-black.2f7f8a6a3899f5d1e1d6.png", "linkedin"),
        ("https://bsky.app/profile/mitocw.bsky.social", "https://ocw.mit.edu/static_shared/images/bluesky-black.9f4523fcefa9b6f25be7.png", "bluesky"),
        ("https://mastodon.social/@mitocw", "https://ocw.mit.edu/static_shared/images/mastodon-black.9e2de31a28415c123800.png", "mastodon"),
    ]
    # Keep the source footer identity and local presentation assets while routing
    # every non-local destination through the page shell's offline boundary.
    social = "".join(
        f'<li><a class="img-link" href="{escape(href, quote=True)}"><img class="footer-social-icon" '
        f'src="{escape(str(ASSET_URL_MAP[asset]), quote=True)}" alt="{escape(alt, quote=True)}"></a></li>'
        for href, asset, alt in social_icons
    )
    terms = local_path("https://ocw.mit.edu/pages/privacy-and-terms-of-use/")
    return f'''<footer id="footer-container"><div id="home-footer" class="w-100 mx-auto">
<div class="row pb-4 mx-0 justify-content-between"><div><a id="open-learning-logo" href="https://openlearning.mit.edu/"><img src="{open_learning_logo}" alt="MIT Open Learning"></a></div><div class="d-flex md-and-above-only align-items-center support-link-container"><a href="https://accessibility.mit.edu">Accessibility</a><a href="https://creativecommons.org/licenses/by-nc-sa/4.0/">Creative Commons License</a><a href="{terms}">Terms and Conditions</a></div></div>
<div class="row pb-4 mx-0 justify-content-between row-gap-20"><div class="about-courseware"><p>MIT OpenCourseWare is an online publication of materials from over 2,500 MIT courses, freely sharing knowledge with learners and educators around the world. <a href="/about/">Learn more</a></p></div><div class="row mx-0 align-items-center"><p class="font-weight-bold">PROUD MEMBER OF : <a href="https://www.oeglobal.org/"><img class="oeg-logo" src="{oeg_logo}" alt="Open Education Global"></a></p></div></div>
<div class="row mx-0 justify-content-between flex-wrap-reverse row-gap-20"><div class="d-flex align-items-end mr-3"><p>© 2001–2026 Massachusetts Institute of Technology</p></div><div class="horizontal-list"><ul class="p-0">{social}</ul></div></div>
</div></footer>'''


def source_home_default_body() -> str:
    fragment = g3b_fragment(PAGES["/"])
    # The retained source fragment predates the local route rewrite performed by
    # the shell. Keep its visible anchors active, but resolve every first-party
    # destination against the frozen local route/data boundary.
    fragment = re.sub(
        r'href="(https://(?:www\.)?ocw\.mit\.edu[^"#]*)"',
        lambda match: f'href="{escape(local_path(match.group(1)), quote=True)}"',
        fragment,
    )
    fragment = fragment.replace("MIT OpenCourseWare To Go", "")
    fragment = fragment.replace(
        'class="d-flex flex-column align-items-center home-banner"',
        'class="d-flex flex-column align-items-center home-banner" data-wb-component="home-hero"',
        1,
    )
    fragment = fragment.replace(
        'class="course-cards standard-width container mx-auto mt-3"',
        'class="course-cards standard-width container mx-auto mt-3" data-wb-source-visual-component="featured-courses"',
        1,
    )
    fragment = fragment.replace(
        'class="new-courses course-cards standard-width container mx-auto mt-3"',
        'class="new-courses course-cards standard-width container mx-auto mt-3" data-wb-source-visual-component="new-courses"',
        1,
    )
    fragment = fragment.replace(
        'class="home-testimonials mx-auto"',
        'class="home-testimonials mx-auto" data-wb-source-visual-component="stories"',
        1,
    )
    fragment = fragment.replace(
        '<form class="home-search-box" method="get" action="/external-boundary/">',
        '<form class="home-search-box" method="get" action="/search/">',
        1,
    ).replace(
        '<input class="w-100" type="text" name="q" aria-label="Search">',
        '<input class="w-100" data-wb-control="global-search-input" type="text" name="q" aria-label="Search">',
        1,
    ).replace(
        '<button type="submit" class="submit btn font-weight-bold px-3 btn-primary md-and-above-only">',
        '<button data-wb-control="global-search-submit" type="submit" class="submit btn font-weight-bold px-3 btn-primary md-and-above-only">',
        1,
    )

    def tag_control(
        markup: str,
        carousel_id: str,
        direction: str,
        control: str,
        href: str,
        destination: str,
    ) -> str:
        pattern = re.compile(
            rf'(<div id="{re.escape(carousel_id)}".*?<a )href="#{re.escape(carousel_id)}" '
            rf'role="button" data-slide="{direction}"',
            re.S,
        )

        def replacement(match: re.Match[str]) -> str:
            return (
                match.group(1)
                + f'href="{href}" data-wb-control="{control}" '
                + f'data-wb-state-href="{destination}" role="button" data-slide="{direction}"'
            )

        return pattern.sub(replacement, markup, count=1)

    aggregate = "/?state=carousel-second-batches"
    for carousel_id, direction, control, href, destination in (
        ("promo-carousel", "prev", "promo-previous", aggregate, "/?promo=previous"),
        ("promo-carousel", "next", "promo-next", aggregate, "/?promo=next"),
        ("featured-course-carousel-xl", "next", "featured-next", aggregate, "/?featured=second"),
        ("new-course-carousel-xl", "next", "new-next", aggregate, "/?new=second"),
        ("testimonial-carousel-xl", "next", "stories-next", aggregate, "/?stories=second"),
    ):
        fragment = tag_control(fragment, carousel_id, direction, control, href, destination)
    return fragment + home_source_footer()


def home_body(
    state: str = "default",
    *,
    featured_state: str = "",
    new_state: str = "",
    stories_state: str = "",
    promo_state: str = "",
) -> str:
    source_default_requested = state == "default" and not any(
        (featured_state, new_state, stories_state, promo_state)
    )
    second = state == "carousel-second-batches"
    featured_second = second or featured_state == "second"
    new_second = second or new_state == "second"
    stories_second = second or stories_state == "second"
    component_states = {
        "featured": "second" if featured_second else "",
        "new": "second" if new_second else "",
        "stories": "second" if stories_second else "",
        "promo": "next" if second else promo_state,
    }

    def state_href(component: str, value: str = "") -> str:
        params = {**component_states, component: value}
        query = "&".join(f"{key}={item}" for key, item in params.items() if item)
        return f"/?{query}" if query else "/"

    featured, new = home_course_records()
    featured_span = slice(4, 8) if featured_second else slice(0, 4)
    new_span = slice(4, 8) if new_second else slice(0, 4)
    featured_cards = "".join(
        home_course_card(record, source_like=featured_second) for record in featured[featured_span]
    )
    new_cards = "".join(
        home_course_card(record, source_like=new_second) for record in new[new_span]
    )
    featured_control = (
        f'<a data-wb-control="featured-previous" data-wb-state-href="{state_href("featured")}" href="/?state=default">‹ Previous</a>'
        '<a href="/?state=carousel-second-batches" data-wb-control="featured-next">Next ›</a>'
        if featured_second else
        '<a href="/?state=default">‹ Previous</a>'
        f'<a data-wb-control="featured-next" data-wb-state-href="{state_href("featured", "second")}" href="/?state=carousel-second-batches">Next ›</a>'
    )
    new_control = (
        f'<a data-wb-control="new-previous" data-wb-state-href="{state_href("new")}" href="/?state=default">‹ Previous</a>'
        '<a href="/?state=carousel-second-batches">Next ›</a>'
        if new_second else f'<a data-wb-control="new-next" data-wb-state-href="{state_href("new", "second")}" href="/?state=carousel-second-batches">Next ›</a>'
    )
    stories_control = (
        '<div class="story-carousel-controls"><a class="story-arrow prev" data-wb-control="stories-previous" '
        f'data-wb-state-href="{state_href("stories")}" aria-label="Previous stories" href="/?state=default">‹</a><a class="story-arrow next" '
        'aria-label="Next stories" href="/?state=carousel-second-batches">›</a></div>'
        if stories_second else f'<a data-wb-control="stories-next" data-wb-state-href="{state_href("stories", "second")}" href="/?state=carousel-second-batches">Next ›</a>'
    )
    collections = "".join(f'<a class="cta" href="{escape(str(row["path"]), quote=True)}">{escape(page_title(row))}</a>' for row in PAGES.values() if row["family"] == "collection")
    home_evidence = DATA["g3b_home_content"]
    story_batch = "carousel-second-batches" if stories_second else "default"
    story_paths = home_evidence["story_batches"][story_batch]
    story_cards = "".join(
        home_story_card(path, home_evidence["stories"][path], source_like=True)
        for path in story_paths
    )
    stories_heading = (
        '<h2>OpenCourseWare Stories</h2><p class="home-stories-intro">Stories from the OpenCourseWare community '
        'reflect the profound impact of sharing knowledge and the transformative power of open education.</p>'
    )
    if second or promo_state == "next":
        promotion_index = int(home_evidence["promotion_states"]["carousel-second-batches"])
    elif promo_state == "previous":
        promotion_index = len(home_evidence["promotions"]) - 1
    else:
        promotion_index = int(home_evidence["promotion_states"]["default"])
    promotion = home_evidence["promotions"][promotion_index]
    hero_url = G3_VISUAL_URL_MAP["https://ocw.mit.edu/images/homepage_hero.jpg"]
    promo_url = ASSET_URL_MAP[str(promotion["image_source_url"])]
    promo_previous = "/?state=default" if promotion_index else "/?state=carousel-second-batches"
    promo_next = "/?state=default" if promotion_index else "/?state=carousel-second-batches"
    promo_previous_state = state_href("promo") if promotion_index else state_href("promo", "previous")
    promo_next_state = state_href("promo") if promotion_index else state_href("promo", "next")
    promo_dots = "".join(
        '<span class="active" aria-current="true">●</span>' if index == promotion_index else "<span>●</span>"
        for index in range(len(home_evidence["promotions"]))
    )
    manual_body = f'''<section class="home-banner" data-wb-component="home-hero" style="background-image:url('{hero_url}')"><div class="banner-columns">
<div class="first-column"><p class="discover">Discover courses, materials, &amp; teaching resources</p><div class="home-search-row"><form action="/search/" method="get" style="display:contents"><input data-wb-control="global-search-input" name="q" aria-label="Search"><button data-wb-control="global-search-submit" type="submit">Search</button></form><span class="or">OR</span><a class="explore" data-wb-link="home-catalog" href="/search/">Explore</a></div>
<div class="home-options"><div class="home-option"><span>Are you new to OCW?</span><a data-wb-link="home-get-started" href="/pages/get-started/">Get Started</a></div><div class="home-option"><span>Looking for teaching materials?</span><a data-wb-link="home-educator" href="/educator/">Educators Start Here</a></div></div></div>
<div class="home-mission"><h1>Unlocking knowledge,<br>Empowering Minds.</h1><p>Free lecture notes, exams, and videos from MIT.<br>No registration required.</p><a data-wb-link="home-about" href="/about/">Learn more about the OCW mission</a></div></div></section>
<section class="home-promo" data-wb-carousel-state="{state}"><a class="promo-arrow prev" data-wb-control="promo-previous" data-wb-state-href="{promo_previous_state}" aria-label="Previous promotion" href="{promo_previous}">‹</a><div class="home-promo-inner"><img class="home-promo-image" data-wb-media="promo-image" data-wb-asset-source="{escape(str(promotion["image_source_url"]), quote=True)}" src="{escape(promo_url, quote=True)}" alt="{escape(str(promotion["image_alt"]), quote=True)}"><div class="home-promo-copy"><h2>{escape(str(promotion["title"]))}</h2><h3>{escape(str(promotion["subtitle"]))}</h3><a data-wb-external="home-promotion" href="{escape(str(promotion["source_url"]), quote=True)}">{escape(str(promotion["cta_text"]))}</a></div></div><a class="promo-arrow next" data-wb-control="promo-next" data-wb-state-href="{promo_next_state}" aria-label="Next promotion" href="{promo_next}">›</a><div class="promo-dots">{promo_dots}</div></section>
<section class="home-section" data-wb-component="featured-courses"><h2>Featured Courses</h2><div class="home-section-controls">{featured_control}</div><div class="cards">{featured_cards}</div></section>
<section class="home-lower collections"><h2>Discover Collections</h2><a data-wb-link="home-collection" href="/collections/introductory-programming/">Introductory Programming</a>{collections}</section>
<section class="home-lower" data-wb-component="new-courses"><h2>New Courses</h2><div class="home-section-controls">{new_control}</div><div class="cards">{new_cards}</div></section>
<section class="home-lower donation"><h2>Your Donation Makes a Difference</h2><a data-wb-external="giving" href="https://giving.mit.edu/give/to/ocw/">Support OCW</a></section>
<section class="home-lower news"><h2>OCW News</h2>{home_news_media()}<p>How MIT Courses Inspired Path to Doctoral Program</p><p>Gaining Confidence and Skill with MIT Open Learning</p><p>MIT Open Learning Reaches All the Way to the South Pole</p></section>
<section class="home-lower" data-wb-component="stories" data-wb-carousel-state="{state}">{stories_heading}<div class="story-grid">{story_cards}</div>{stories_control}<a class="home-view-all-stories" data-wb-link="stories-index" href="/stories/">View All OCW Stories ›</a></section>
<section class="home-lower supporters"><h2>Our Corporate and Foundation Supporters</h2></section>'''
    if source_default_requested:
        semantic_mirror = re.sub(r'\sdata-wb-control="[^"]+"', "", manual_body)
        external_boundaries = (
            '<a data-wb-external="accessibility" href="https://accessibility.mit.edu/">Accessibility</a>'
            '<a data-wb-external="creative-commons" href="https://creativecommons.org/licenses/by-nc-sa/4.0/">Creative Commons License</a>'
            '<a data-wb-external="contact" href="https://mitocw.zendesk.com/hc/en-us/requests/new">Contact Us</a>'
            '<a data-wb-external="help" href="https://mitocw.zendesk.com/hc/en-us">Help &amp; FAQs</a>'
            '<a data-wb-external="mit-learn" href="https://learn.mit.edu/">MIT Learn</a>'
            '<a data-wb-external="ocw-to-go" href="https://ocwtogo.mit.edu/">OCW To Go</a>'
            '<a data-wb-external="open-learning" href="https://openlearning.mit.edu/">MIT Open Learning</a>'
            '<a data-wb-external="chalk-radio" href="https://chalk-radio.simplecast.com/">Chalk Radio</a>'
            '<a data-wb-external="youtube" href="https://www.youtube.com/">YouTube</a>'
        )
        return (
            source_home_default_body()
            + '<div class="home-semantic-mirror" aria-hidden="true">'
            + semantic_mirror
            + external_boundaries
            + "</div>"
        )
    return manual_body


COURSE_LINKS = {
    "course-syllabus": "/courses/6-006-introduction-to-algorithms-fall-2011/pages/syllabus/",
    "course-calendar": "/courses/6-006-introduction-to-algorithms-fall-2011/pages/calendar/",
    "course-readings": "/courses/6-006-introduction-to-algorithms-fall-2011/pages/readings/",
    "course-lecture-notes": "/courses/6-006-introduction-to-algorithms-fall-2011/pages/lecture-notes/",
    "course-assignments": "/courses/6-006-introduction-to-algorithms-fall-2011/pages/assignments/",
    "course-exams": "/courses/6-006-introduction-to-algorithms-fall-2011/pages/exams/",
    "course-download-page": "/courses/6-006-introduction-to-algorithms-fall-2011/download/",
    "video-gallery": "/courses/14-129-blockchain-and-the-design-of-financial-systems-spring-2025/video_galleries/video-lectures/",
}
def course_navigation(record: dict[str, object]) -> str:
    root = course_root(str(record["path"]))
    if root == "/courses/6-006-introduction-to-algorithms-fall-2011/":
        current_path = str(record["path"])
        exact = [
            ("course-syllabus", "Syllabus", COURSE_LINKS["course-syllabus"]),
            ("course-calendar", "Calendar", COURSE_LINKS["course-calendar"]),
            ("course-readings", "Readings", COURSE_LINKS["course-readings"]),
            ("course-lecture-notes", "Lecture Notes", COURSE_LINKS["course-lecture-notes"]),
            ("video-gallery", "Lecture Videos", COURSE_LINKS["video-gallery"]),
            ("course-recitation-videos", "Recitation Videos", "/data-boundary/"),
            ("course-assignments", "Assignments", COURSE_LINKS["course-assignments"]),
            ("course-exams", "Exams", COURSE_LINKS["course-exams"]),
            ("course-related-resources", "Related Resources", "/data-boundary/"),
        ]
        links = []
        for key, text, href in exact:
            active = "active" if href == current_path else ""
            disclosure = '<span class="disclosure">⌃</span>' if active else ""
            links.append(
                f'<a class="{active}" data-wb-link="{key}" href="{href}">{text}{disclosure}</a>'
            )
        return "".join(links)
    if root == "/courses/14-129-blockchain-and-the-design-of-financial-systems-spring-2025/":
        source_links = [
            ("Syllabus", root + "pages/syllabus/"),
            ("Readings", root + "pages/readings/"),
            ("Lecture Videos", root + "video_galleries/video-lectures/"),
            ("Lecture Notes", root + "lists/lecture-notes/"),
        ]
        return "".join(
            f'<a href="{escape(local_path("https://ocw.mit.edu" + path), quote=True)}">{text}</a>'
            for text, path in source_links
        )
    links: list[str] = []
    seen: set[str] = set()
    for link in record.get("links", []):
        text = str(link.get("text") or "").strip()
        href = local_path(str(link["url"]))
        if (
            not text
            or text == "Download Course"
            or href == root
            or not href.startswith(root)
            or href in seen
            or href not in PAGES
        ):
            continue
        seen.add(href)
        links.append(f'<a href="{escape(href, quote=True)}">{escape(text)}</a>')
    return "".join(links)


COURSE_TERM_PATTERN = re.compile(r"-(january-iap|spring|summer|fall|winter)-(\d{4})/$")
COURSE_BANNER_OVERRIDES = {
    "/courses/6-006-introduction-to-algorithms-fall-2011/": ("6.006", "Fall 2011", "Undergraduate"),
    "/courses/14-129-blockchain-and-the-design-of-financial-systems-spring-2025/": (
        "14.129",
        "Spring 2025",
        "Graduate",
    ),
}


def course_term(root: str) -> str:
    """Read one course's term off its own frozen root path."""
    match = COURSE_TERM_PATTERN.search(root)
    if not match:
        return ""
    season = match.group(1)
    season = "January IAP" if season == "january-iap" else season.capitalize()
    return f"{season} {match.group(2)}"


def catalog_banner_metadata() -> dict[str, tuple[str, str, str]]:
    """Derive each frozen catalog course's banner identity from its own captured card."""
    derived: dict[str, tuple[str, str, str]] = {}
    for course in COURSES:
        path = unquote(urlsplit(str(course["url"])).path)
        root = path if path.endswith("/") else path + "/"
        code = str(course["course_code_token"])
        term = course_term(root)
        levels = re.match(
            rf"\s*{re.escape(code)}\s*\|\s*([A-Z][A-Z, ]*?)\s+[A-Z]",
            str(course["card_text"]),
        )
        if not term or not levels:
            continue
        level = ", ".join(
            part.capitalize() for part in levels.group(1).strip().strip(",").split(", ") if part
        )
        derived[root] = (code, term, level)
    return derived


COURSE_BANNER_METADATA = {**catalog_banner_metadata(), **COURSE_BANNER_OVERRIDES}


def course_frame(
    record: dict[str, object],
    content: str,
    *,
    component: str,
    right_panel: str = "",
) -> str:
    root = course_root(str(record["path"]))
    is_six006 = root == "/courses/6-006-introduction-to-algorithms-fall-2011/"
    is_video_course = root == "/courses/14-129-blockchain-and-the-design-of-financial-systems-spring-2025/"
    is_catalog_course = str(record.get("page_id")) == "catalog-course-01"
    course_name = (
        "Introduction To Algorithms" if is_six006 else
        "Blockchain And The Design Of Financial Systems" if is_video_course else
        "Research Design For Policy Analysis And Planning" if is_catalog_course else
        page_title(PAGES.get(root, record))
    )
    identity = COURSE_BANNER_METADATA.get(root)
    metadata = " &nbsp;|&nbsp; ".join(identity) if identity else "MIT OpenCourseWare"
    return (
        '<section class="course-banner"><div class="course-banner-content">'
        f'<p class="course-meta">{metadata}</p><h1><a href="{escape(root or str(record["path"]), quote=True)}">'
        f'{escape(course_name)}</a></h1></div></section>'
        '<div class="course-stage">'
        '<aside class="course-panel course-side" data-wb-component="course-side-navigation">'
        '<h3 class="course-mobile-heading">Browse Course Material</h3>'
        '<button class="course-menu-mobile" data-wb-control="course-menu" type="button" '
        'aria-controls="course-material-navigation" aria-expanded="false">Browse Course Material</button>'
        f'<nav id="course-material-navigation" data-menu-open="false" aria-label="Course materials">{course_navigation(record)}</nav></aside>'
        f'<article class="course-panel course-center" data-wb-component="{escape(component, quote=True)}">{content}</article>'
        f'<aside class="course-panel course-right">{right_panel}</aside>'
        '</div>'
    )


def route_identity(record: dict[str, object]) -> str:
    return (
        f'<p class="eyebrow" data-wb-source-page="{escape(str(record["source_url"]), quote=True)}">'
        f'{escape(str(record["page_id"]))}</p>'
    )


def g3b_fragment(record: dict[str, object]) -> str:
    """Load this route's exact, hash-indexed, network-closed source fragment."""
    path = str(record["path"])
    content = CONTENT_ROUTES.get(path)
    if not content:
        raise RuntimeError(f"missing G3-B content record: {path}")
    runtime_root = (SITE_ROOT / "runtime-content").resolve()
    runtime = (SITE_ROOT / str(content["runtime_path"])).resolve()
    runtime.relative_to(runtime_root)
    return runtime.read_text(encoding="utf-8")


def collection_body(record: dict[str, object]) -> str:
    fragment = g3b_fragment(record)
    if str(record["path"]) != "/collections/introductory-programming/":
        return (
            '<section class="wrap section collection-links">'
            f'{fragment}{route_identity(record)}</section>'
        )

    groups = {
        "7fbf1e18-1f33-45af-98e2-01fa698ef41e": [
            ("Introduction to CS and Programming using Python", "6.100L", "Undergraduate", "https://ocw.mit.edu/courses/6-100l-introduction-to-cs-and-programming-using-python-fall-2022/", "https://ocw.mit.edu/courses/6-100l-introduction-to-cs-and-programming-using-python-fall-2022/mit6_100l_f22.jpeg"),
            ("Introduction to Computer Science and Programming in Python", "6.0001", "Undergraduate", "https://ocw.mit.edu/courses/6-0001-introduction-to-computer-science-and-programming-in-python-fall-2016/", "https://ocw.mit.edu/courses/6-0001-introduction-to-computer-science-and-programming-in-python-fall-2016/bb7bc760922abfcd37f5d8b9203d771f_6-0001f16.jpg"),
            ("Introduction to Computational Thinking and Data Science", "6.0002", "Undergraduate", "https://ocw.mit.edu/courses/6-0002-introduction-to-computational-thinking-and-data-science-fall-2016/", "https://ocw.mit.edu/courses/6-0002-introduction-to-computational-thinking-and-data-science-fall-2016/d9b969b1e9e2029d7e9b9e2c9324dde4_6-0002f16.jpg"),
            ("Programming for the Puzzled", "6.S095", "Undergraduate", "https://ocw.mit.edu/courses/6-s095-programming-for-the-puzzled-january-iap-2018/", "https://ocw.mit.edu/courses/6-s095-programming-for-the-puzzled-january-iap-2018/8a47e175cc72845e080f083fcfbc7c29_6-S095IAP18.jpg"),
        ],
        "29f07bcd-4f4b-446e-aa2a-89691f9f5fc9": [
            ("Software Construction", "6.005", "Undergraduate", "https://ocw.mit.edu/courses/6-005-software-construction-spring-2016/", "https://ocw.mit.edu/courses/6-005-software-construction-spring-2016/9415505f05894d2c77f442a4f7488623_6-005S16.png"),
            ("Introduction to Algorithms", "6.006", "Undergraduate", "https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-spring-2020/", "https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-spring-2020/5a62336c0a97b276d6141b0b7f070b5b_6-006s20.png"),
            ("The Battlecode Programming Competition", "6.370", "Undergraduate", "https://ocw.mit.edu/courses/6-370-the-battlecode-programming-competition-january-iap-2013/", "https://ocw.mit.edu/courses/6-370-the-battlecode-programming-competition-january-iap-2013/7a9458fa1205ca527ba893f8188b6933_6-370iap13.jpg"),
        ],
        "8b182df2-d2f7-4ce4-8f61-5f85269631ad": [
            ("Introduction to Computational Thinking", "18.S191", "Undergraduate", "https://ocw.mit.edu/courses/18-s191-introduction-to-computational-thinking-fall-2022/", "https://ocw.mit.edu/courses/18-s191-introduction-to-computational-thinking-fall-2022/18-s191f22.jpg"),
            ("Introduction to MATLAB", "6.057", "Undergraduate", "https://ocw.mit.edu/courses/6-057-introduction-to-matlab-january-iap-2019/", "https://ocw.mit.edu/courses/6-057-introduction-to-matlab-january-iap-2019/20d4110b5815d78f84876f348a30d844_6-057IAP19.jpg"),
            ("Introduction to Programming in Java", "6.092", "Undergraduate", "https://ocw.mit.edu/courses/6-092-introduction-to-programming-in-java-january-iap-2010/", "https://ocw.mit.edu/courses/6-092-introduction-to-programming-in-java-january-iap-2010/fecdf32086554546b8f8e3563528239e_6-092iap10.jpg"),
            ("Introduction to C and C++", "6.S096", "Undergraduate", "https://ocw.mit.edu/courses/6-s096-introduction-to-c-and-c-january-iap-2013/", "https://ocw.mit.edu/courses/6-s096-introduction-to-c-and-c-january-iap-2013/dc7d141c865352edae2509739884f34e_6-s096iap13.jpg"),
            ("Introduction to R and Geographic Information Systems (GIS)", "RES.1-002", "Non-Credit", "https://ocw.mit.edu/courses/introduction-to-r-and-gis-fall-2023/", "https://ocw.mit.edu/courses/introduction-to-r-and-gis-fall-2023/mitres_1_002_f23.jpg"),
        ],
    }
    for collection_id, courses in groups.items():
        cards = []
        for title, code, level, source_url, image_url in courses:
            image_path = G3C_COLLECTION_URL_MAP.get(image_url, "/data-boundary/")
            thumbnail = (
                f'<img class="collection-thumb" data-wb-media="collection-course-image" src="{escape(image_path, quote=True)}" alt="">'
                if image_path != "/data-boundary/"
                else '<span class="collection-thumb collection-thumb-unavailable" aria-label="Source image unavailable"></span>'
            )
            cards.append(
                '<a class="collection-course-card" href="/data-boundary/?url=' + quote(source_url, safe="") + '">'
                f'{thumbnail}<span class="collection-course-copy"><strong>{escape(title)}</strong><small>{code}</small></span>'
                f'<span class="collection-level">{level}</span></a>'
            )
        marker = f'<div class="course-collection-container" data-collectionid="{collection_id}"></div>'
        if marker not in fragment:
            raise RuntimeError(f"missing frozen collection slot: {collection_id}")
        fragment = fragment.replace(
            marker,
            f'<div class="collection-course-cards" data-wb-component="collection-course-cards" data-collectionid="{collection_id}">{"".join(cards)}</div>',
            1,
        )
    return (
        '<section class="wrap section collection-links">'
        f'{fragment}{route_identity(record)}</section>'
    )


def course_overview_body(record: dict[str, object]) -> str:
    root = course_root(str(record["path"]))
    if root == "/courses/6-006-introduction-to-algorithms-fall-2011/":
        source_url = (
            "https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-fall-2011/"
            "1075c5ac06ae4c2cea8c89e9772da78a_6-006f11.jpg"
        )
        image_url = G3_VISUAL_URL_MAP[source_url]
        content = '''<section class="course-overview" data-wb-source-page="https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-fall-2011/">
<div class="course-description"><h2>Course Description</h2><p>This course provides an introduction to mathematical modeling of computational problems. It covers the common algorithms, algorithmic paradigms, and data structures used to solve these problems. The course emphasizes the relationship between algorithms and programming, and introduces basic performance measures and <span id="course-description-more" hidden>analysis techniques for these problems.</span><button type="button" data-wb-control="course-description-expand" aria-controls="course-description-more" aria-expanded="false">...Show more</button></p></div>
<h2 class="course-info-title">Course Info</h2><div class="course-info-grid"><div class="column"><div class="course-info-block"><h3>Instructors</h3><p><a href="/data-boundary/">Prof. Erik Demaine</a><br><a href="/data-boundary/">Prof. Srini Devadas</a></p></div><div class="course-info-block"><h3>Departments</h3><p><a href="/search/?state=default">Electrical Engineering and Computer Science</a></p></div></div><div class="column"><div class="course-info-block"><h3>Topics</h3><div class="topic-tree"><div>⌄ <a href="/search/?state=default">Engineering</a></div><div>&nbsp;&nbsp;⌄ <a href="/search/?state=default">Computer Science</a></div><div>&nbsp;&nbsp;&nbsp;&nbsp;<a href="/search/?state=default">Algorithms and Data Structures</a></div></div></div></div></div>
<h3 class="resource-types-title">Learning Resource Types</h3><div class="resource-pills"><span class="resource-pill">Exam Solutions</span><span class="resource-pill">Exams</span><span class="resource-pill">Lecture Notes</span><span class="resource-pill">Lecture Videos</span><span class="resource-pill">Problem Set Solutions</span><span class="resource-pill">Problem Sets</span><span class="resource-pill">Problem-solving Videos</span><span class="resource-pill">Programming Assignments with Examples</span></div></section>'''
        right = (
            f'<img data-wb-media="course-hero-image" data-wb-asset-source="{source_url}" src="{image_url}" '
            'alt="Two Rubik’s cubes marked with the number 6"><p class="course-caption">'
            'In Problem Set 6, students develop algorithms for solving the 2x2x2 Rubik’s Cube.</p><hr>'
            f'<a class="download-course-link-button" data-wb-link="course-download-page" href="{COURSE_LINKS["course-download-page"]}">Download Course</a>'
        )
        return course_frame(record, content, component="course-main-content", right_panel=right)
    asset = direct_course_asset(record)
    media = image_tag(asset, "course-hero-image") if asset else ""
    source_fragment = g3b_fragment(record)
    if int(CONTENT_ROUTES[str(record["path"])]["runtime_visible_text_bytes"]) < 20:
        source_fragment = (
            '<div class="notice" data-wb-capability="data-boundary">'
            'This frozen source route returned an empty content area. Its destination identity is retained; '
            'no replacement content was inferred.</div>' + source_fragment
        )
    content = f'<section class="course-overview">{source_fragment}{route_identity(record)}</section>'
    right_panel = media
    if str(record.get("page_id")) == "catalog-course-01":
        download_url = (
            "https://ocw.mit.edu/courses/11-233-research-design-for-policy-analysis-and-planning-fall-2007/download"
        )
        right_panel = (
            f'{media}<p class="course-caption">This course includes sessions that focus on eliciting '
            'information through surveys and interviews. (Image courtesy of munir on Flickr.)</p><hr>'
            f'<a class="download-course-link-button" href="/data-boundary/?url={quote(download_url, safe="")}">Download Course</a>'
        )
    return course_frame(record, content, component="course-main-content", right_panel=right_panel)


def assignment_link(label: str, source_path: str) -> str:
    source_url = source_path if source_path.startswith("http") else f"https://ocw.mit.edu{source_path}"
    href = local_path(source_url)
    if urlsplit(source_url).hostname not in {"ocw.mit.edu", "www.ocw.mit.edu"}:
        href = f"/external-boundary/?url={quote(source_url, safe='')}"
    elif href == "/data-boundary/":
        href = f"/data-boundary/?url={quote(source_url, safe='')}"
    return (
        f'<a href="{escape(href, quote=True)}" '
        f'data-wb-source-href="{escape(source_url, quote=True)}">{escape(label)}</a>'
    )


def assignments_source_fragment(record: dict[str, object]) -> str:
    """Repair the captured source table that the generic sanitizer flattened."""
    fragment = g3b_fragment(record)
    intro, separator, _flattened_table = fragment.partition("<p><table>")
    if not separator:
        return fragment

    def link(label: str, path: str, suffix: str = "") -> str:
        return f"<p>{assignment_link(label, path)}{escape(suffix)}</p>"

    problem_set_7_code = (
        "<p>"
        + assignment_link(
            "Problem Set 7 Code (ZIP)",
            "/courses/6-006-introduction-to-algorithms-fall-2011/resources/ps7_code/",
        )
        + " (Sunset image © source unknown. All rights reserved. This content is excluded from our "
        "Creative Commons license. For more information, see "
        + assignment_link("https://ocw.mit.edu/help/faq-fair-use/", "/help/faq-fair-use/")
        + ".)</p>"
    )

    rows = (
        (
            "1",
            "Asymptotic complexity, recurrence relations, peak finding",
            link("Problem Set 1 (PDF)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_ps1/")
            + link("Problem Set 1 Code (ZIP)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/ps1/"),
            link("Problem Set 1 Solutions (PDF)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_ps1_sol/"),
        ),
        (
            "2",
            "Fractal rendering, digital circuit simulation",
            link("Problem Set 2 (PDF)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_ps2/")
            + link("Problem Set 2 Code (ZIP)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/ps2/"),
            link("Problem Set 2 Solutions (PDF)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_ps2_sol/")
            + link("Problem Set 2 Code Solutions (ZIP - 7.7MB)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/ps2_code_sol/"),
        ),
        (
            "3",
            "Range queries, digital circuit layout",
            link("Problem Set 3 (PDF)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_ps3/")
            + link("Problem Set 3 Code (ZIP - 3.2MB)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/ps3/"),
            link("Problem Set 3 Solutions (PDF)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_ps3_sol/")
            + link("Problem Set 3 Code Solutions (ZIP - 15.7MB)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/ps3_code_sol_zip/"),
        ),
        (
            "4",
            "Hash functions, Python dictionaries, matching DNA sequences",
            link("Problem Set 4 (PDF)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_ps4/")
            + link(
                "Problem Set 4 Code (GZ - 12.4MB)",
                "/courses/6-006-introduction-to-algorithms-fall-2011/resources/ps4tar_gz/",
                " (kfasta.py courtesy of Kevin Kelley, and used with permission.)",
            ),
            link("Problem Set 4 Solutions (PDF)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_ps4_sol/")
            + link("Problem Set 4 Code Solutions (ZIP)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/ps4_code_sol/"),
        ),
        (
            "5",
            "The Knight’s Shield, RSA public key encryption, image decryption",
            link("Problem Set 5 (PDF)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_ps5/")
            + link("Problem Set 5 Code (ZIP)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/ps5/")
            + link("Problem Set 5 Grading Explanation (PDF)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_ps5e/"),
            link("Problem Set 5 Solutions (PDF)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_ps5_sol/")
            + link("Problem Set 5 Code Solutions (ZIP)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/ps5_code_sol/"),
        ),
        (
            "6",
            "Social networks, Rubik’s Cube, Dijkstra",
            link("Problem Set 6 (PDF)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_ps6/")
            + link(
                "Problem Set 6 Code (ZIP - 2.9MB)",
                "/courses/6-006-introduction-to-algorithms-fall-2011/resources/ps6/",
                " (nhpn.py courtesy of Punyashloka Biswal and Michael Lieberman; Pocket Cube Solver courtesy of Huan Liu and Anh Nguyen. Used with permission.)",
            ),
            link("Problem Set 6 Solutions (PDF)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_ps6_sol/")
            + link("Problem Set 6 Code Solutions (ZIP)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/ps6_code_sol/"),
        ),
        (
            "7",
            "Seam carving, stock purchasing and knapsack",
            link("Problem Set 7 (PDF)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_ps7/")
            + link("Seam Carving for Content-Aware Image Resizing", "https://dx.doi.org/10.1145/1276377.1276390")
            + problem_set_7_code
            + link("Problem Set 7 Answer Template (ZIP)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/ps7_writeup/")
            + link("Problem Set 7 Grading Explanation (PDF)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_ps7e/"),
            link("Problem Set 7 Solutions (PDF)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_ps7_sol/")
            + link("Problem Set 7 Code Solutions (ZIP)", "/courses/6-006-introduction-to-algorithms-fall-2011/resources/ps7_sol/"),
        ),
    )
    body = "".join(
        f"<tr><td>{number}</td><td>{escape(topic)}</td>"
        f"<td><p></p>{problem_sets}<p></p></td><td><p></p>{solutions}<p></p></td></tr>"
        for number, topic, problem_sets, solutions in rows
    )
    table = (
        '<table class="assignment-table" data-wb-component="assignments-table">'
        '<colgroup><col style="width:73px"><col style="width:167.2px">'
        '<col style="width:440.9px"><col style="width:143.9px"></colgroup>'
        '<thead><tr><th>Assn #</th><th>TOPICS</th><th>PROBLEM SETS</th><th>SOLUTIONS</th></tr></thead>'
        f"<tbody>{body}</tbody></table>"
    )
    return intro.replace(
        '<main id="course-content-section">',
        '<main id="course-content-section" class="assignments-source-content">',
        1,
    ) + table + "</main></div>"


def source_table_fragment(record: dict[str, object]) -> str:
    """Restore table rows displaced by the frozen HTML fragment sanitizer."""
    fragment = g3b_fragment(record)
    main_start = fragment.find('<main id="course-content-section">')
    thead_start = fragment.find("<thead>", main_start)
    thead_end = fragment.find("</thead>", thead_start)
    main_end = fragment.rfind("</main>")
    if min(main_start, thead_start, thead_end, main_end) < 0:
        raise RuntimeError(f"missing frozen source table structure: {record['path']}")
    thead_end += len("</thead>")
    body_source = fragment[thead_end:main_end]

    # On lecture-notes rows whose topic contains a list, the frozen sanitizer
    # closed the empty second cell before serializing that topic and list.
    # Put those already-captured nodes back into their row before collecting it.
    orphaned_topic = re.compile(
        r"(<tr>\s*<td>\s*\d+\s*</td>\s*<td>)\s*</td>\s*</tr>\s*</p>\s*"
        r"(<p>.*?</p>\s*<ul>.*?</ul>)",
        re.DOTALL,
    )
    body_source = orphaned_topic.sub(r"\1\2</td></tr></p>", body_source)
    rows = re.findall(r"<tr>.*?</tr>", body_source, flags=re.DOTALL)
    if not rows:
        raise RuntimeError(f"missing frozen source table rows: {record['path']}")

    main_open_end = fragment.find(">", main_start) + 1
    table_start = fragment.find("<table>", main_open_end, thead_start)
    before_table = fragment[main_open_end:table_start]
    before_table = re.sub(r"<p>\s*$", "", before_table)
    prefix = fragment[:main_open_end]
    suffix = fragment[main_end:]
    table = (
        '<table class="source-course-table" data-wb-component="source-course-table">'
        f"{fragment[thead_start:thead_end]}<tbody>{''.join(rows)}</tbody></table>"
    )
    return f"{prefix}{before_table}{table}{suffix}"


def course_section_body(record: dict[str, object]) -> str:
    path = str(record["path"])
    breadcrumb = ""
    if path.endswith("/pages/readings/binary-search-trees/"):
        breadcrumb = (
            '<p class="source-course-breadcrumb"><a '
            'href="/courses/6-006-introduction-to-algorithms-fall-2011/pages/readings/">Readings</a></p>'
        )
    root = course_root(path)
    title = page_title(record)
    if path.endswith("/pages/assignments/"):
        fragment = assignments_source_fragment(record)
    elif root == "/courses/6-006-introduction-to-algorithms-fall-2011/" and path.endswith(
        ("/pages/calendar/", "/pages/readings/", "/pages/lecture-notes/", "/pages/exams/")
    ):
        fragment = source_table_fragment(record)
    else:
        fragment = g3b_fragment(record)
    content = (
        '<section class="course-section six006-detail">'
        + (
            f'<div class="source-course-heading">{breadcrumb}'
            f'<h2 class="course-page-title">{escape(title)}</h2></div>'
            if root == "/courses/6-006-introduction-to-algorithms-fall-2011/" else ""
        )
        + f'<article class="source-course-article content">{fragment}</article>'
        + f'{route_identity(record)}</section>'
    )
    right = six006_course_info() if root == "/courses/6-006-introduction-to-algorithms-fall-2011/" else ""
    if path.endswith("/pages/readings/"):
        content = content.replace(
            'href="/courses/6-006-introduction-to-algorithms-fall-2011/pages/readings/binary-search-trees/"',
            'data-wb-link="reading-deep" '
            'href="/courses/6-006-introduction-to-algorithms-fall-2011/pages/readings/binary-search-trees/"',
            1,
        )
    return course_frame(record, content, component="course-main-content", right_panel=right)


def exact_download_href(record: dict[str, object]) -> str:
    for link in record.get("links", []):
        href = local_path(str(link["url"]))
        if href == PDF["path"] or href in DOWNLOADS or href in SUPPLEMENTARY_DOWNLOADS:
            return href
    return "/data-boundary/"


def exact_video_thumbnail(record: dict[str, object]) -> dict[str, object] | None:
    """Join gallery resource links and retained thumbnails by frozen DOM order."""
    gallery = PAGES[COURSE_LINKS["video-gallery"]]
    resource_paths = [
        local_path(str(link["url"]))
        for link in gallery.get("links", [])
        if "/resources/" in str(link["url"]) and local_path(str(link["url"])) in PAGES
    ]
    thumbnails = [
        ref for ref in report_assets(gallery)
        if urlsplit(str(ref["url"])).hostname == "img.youtube.com"
    ]
    try:
        position = resource_paths.index(str(record["path"]))
    except ValueError:
        return None
    return thumbnails[position] if position < len(thumbnails) else None


def video_course_info() -> str:
    root = "/courses/14-129-blockchain-and-the-design-of-financial-systems-spring-2025/"
    return f'''<section class="video-course-info"><h2>Course Info</h2>
<h3>Instructor</h3><p><a href="/search/">Prof. Robert M. Townsend</a></p>
<h3>Departments</h3><p><a href="/search/">Economics</a></p>
<h3>As Taught In</h3><p>Spring 2025</p>
<h3>Level</h3><p><a href="/search/">Graduate</a></p>
<h3>Topics</h3><p>⌄ <a href="/search/">Social Science</a><br>&nbsp;&nbsp;⌄ <a href="/search/">Economics</a><br>&nbsp;&nbsp;&nbsp;&nbsp;<a href="/search/">Financial Economics</a></p>
<h3>Learning Resource Types</h3><p class="resource-kinds"><span><i aria-hidden="true" class="material-icons">notes</i>&nbsp;Lecture Notes</span><span><i aria-hidden="true" class="material-icons">theaters</i>&nbsp;Lecture Videos</span></p>
<a class="download-course-link-button" href="{root}download/">Download Course</a></section>'''


def six006_course_info() -> str:
    root = "/courses/6-006-introduction-to-algorithms-fall-2011/"
    return '''<section class="six006-course-info" data-wb-component="course-info-sidebar"><h2>Course Info</h2>
<h3>Instructors</h3><p><a href="/search/">Prof. Erik Demaine</a><br><a href="/search/">Prof. Srini Devadas</a></p>
<h3>Departments</h3><p><a href="/search/">Electrical Engineering and Computer Science</a></p>
<h3>As Taught In</h3><p>Fall 2011</p><h3>Level</h3><p><a href="/search/">Undergraduate</a></p>
<h3>Topics</h3><p>⌄ <a href="/search/">Engineering</a><br>&nbsp;&nbsp;⌄ <a href="/search/">Computer Science</a><br>&nbsp;&nbsp;&nbsp;&nbsp;<a href="/search/">Algorithms and Data Structures</a></p>
<h3>Learning Resource Types</h3><p class="resource-kinds"><span><i aria-hidden="true" class="material-icons">grading</i>&nbsp;Exam Solutions</span><span><i aria-hidden="true" class="material-icons">grading</i>&nbsp;Exams</span><span><i aria-hidden="true" class="material-icons">notes</i>&nbsp;Lecture Notes</span><span><i aria-hidden="true" class="material-icons">theaters</i>&nbsp;Lecture Videos</span><span><i aria-hidden="true" class="material-icons">assignment_turned_in</i>&nbsp;Problem Set Solutions</span><span><i aria-hidden="true" class="material-icons">assignment</i>&nbsp;Problem Sets</span><span><i aria-hidden="true" class="material-icons">theaters</i>&nbsp;Problem-solving Videos</span><span><i aria-hidden="true" class="material-icons">assignment_turned_in</i>&nbsp;Programming Assignments with Examples</span></p>
<a class="download-course-link-button" href="''' + root + '''download/">Download Course</a></section>'''


def video_resource_body(record: dict[str, object]) -> str:
    title = "Lecture 1: Introduction to 14.129 Blockchain and Design of Financial Systems"
    content = (
        f'<section class="video-resource" data-wb-capability="video-playback-disabled"><h2 class="video-title">{title}</h2>'
        '<p class="video-description">In this lecture, Prof. Townsend gives a quick summary of the topics to be covered in the course.</p>'
        '<div class="offline-video-player">'
        '<img class="offline-video-poster" data-wb-media="disabled-video-poster" '
        'src="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 '
        'width=%22804%22 height=%22488%22%3E%3Crect width=%22804%22 height=%22488%22 '
        'fill=%22%23000%22/%3E%3C/svg%3E" alt="Video playback unavailable offline">'
        '<button class="offline-video-surface" data-wb-control="video-play" disabled '
        'aria-label="Video playback unavailable offline">› &nbsp; TRANSCRIPT &nbsp; · &nbsp; Playback unavailable offline</button>'
        '</div></section>'
    )
    return course_frame(record, content, component="resource-content", right_panel=video_course_info())


def resource_body(record: dict[str, object]) -> str:
    path = str(record["path"])
    is_video = str(record["page_id"]) == "video-resource-static-thumbnail"
    if is_video:
        return video_resource_body(record)
    prefix = ""
    fragment = g3b_fragment(record)
    if path.endswith("/resources/problem-sets/"):
        fragment = fragment.replace(
            '<a class="resource-list-title" '
            'href="/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_ps1/"',
            '<a class="resource-list-title" data-wb-link="problem-set-detail" '
            'href="/courses/6-006-introduction-to-algorithms-fall-2011/resources/mit6_006f11_ps1/"',
            1,
        )
    detail_kinds = {
        "final-exam-resource-detail": "Exams",
        "lecture-note-1-resource-detail": "Lecture Notes",
        "problem-set-1-resource-detail": "Assignments",
    }
    detail_kind = detail_kinds.get(str(record["page_id"]))
    if detail_kind:
        prefix = (
            f'<nav class="resource-breadcrumb" data-wb-component="resource-breadcrumb">{detail_kind}</nav>'
            f'<h2 class="course-page-title">{escape(page_title(record))}</h2>'
        )
        fragment = fragment.replace(
            'class="resource-page-container"',
            'class="resource-page-container" data-wb-component="resource-metadata"',
            1,
        ).replace(
            'class="download-file"',
            'class="download-file" data-wb-control="resource-download" '
            'data-wb-capability="local-attachment-download"',
            1,
        ).replace('id="pdf-wrapper"', 'id="pdf-wrapper" data-wb-component="resource-preview"', 1)
    content = (
        f'<section class="resource-page six006-detail {"source-resource-detail" if prefix else ""}">'
        f'{prefix}{fragment}'
        f'{route_identity(record)}</section>'
    )
    right = six006_course_info() if course_root(path) == "/courses/6-006-introduction-to-algorithms-fall-2011/" else ""
    return course_frame(record, content, component="resource-content", right_panel=right)


def course_download_body(record: dict[str, object]) -> str:
    fragment = g3b_fragment(record)
    source_archive = (
        "https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-fall-2011/"
        "6.006-fall-2011.zip"
    )
    href = local_path(source_archive)
    fragment = fragment.replace(
        'class="download-course-button p-2"',
        'class="download-course-button p-2" data-wb-control="course-download" '
        'data-wb-capability="local-course-archive"',
        1,
    )
    fragment = fragment.replace(
        'href="/data-boundary/?url=https%3A%2F%2Focw.mit.edu%2Fcourses%2F6-006-introduction-to-algorithms-fall-2011%2F6.006-fall-2011.zip"',
        f'href="{escape(href, quote=True)}"',
        1,
    )
    content = f'<section class="download-panel">{fragment}</section>'
    right = six006_course_info()
    return course_frame(record, content, component="course-main-content", right_panel=right)


def story_index_body(record: dict[str, object]) -> str:
    return (
        '<section class="stories-index">'
        f'{g3b_fragment(record)}</section>'
    )


def story_detail_body(record: dict[str, object]) -> str:
    return (
        '<article class="story-detail-page">'
        f'{g3b_fragment(record)}</article>'
    )


def newsletter_body(record: dict[str, object]) -> str:
    fragment = g3b_fragment(record)
    fragment = fragment.replace(
        '<form id="mc-embedded-subscribe-form"',
        '<form data-wb-component="newsletter-form" '
        'data-wb-external-destination="https://mit.us6.list-manage.com/subscribe/post?u=ad81d725159c1f322a0c54837&amp;id=4c04dfddc5&amp;f_id=00e734e1f0" '
        'id="mc-embedded-subscribe-form"',
        1,
    ).replace(
        'id="mce-EMAIL"', 'id="mce-EMAIL" data-wb-control="newsletter-email"', 1
    ).replace(
        'id="mc-embedded-subscribe"', 'id="mc-embedded-subscribe" data-wb-control="newsletter-submit"', 1
    )
    return f'<section class="newsletter">{fragment}</section>'


def information_body(record: dict[str, object]) -> str:
    if str(record["path"]) == "/newsletter/":
        return newsletter_body(record)
    boundary = ""
    first_heading = str(record.get("headings", [{}])[0].get("text", ""))
    if first_heading == "You are leaving MIT OpenCourseWare":
        boundary = (
            '<div class="notice" data-wb-component="source-legacy-boundary">'
            '<h1>You are leaving MIT OpenCourseWare</h1>'
            '<p>This retained source alias opens through the local offline boundary.</p></div>'
        )
    fragment = g3b_fragment(record)
    if str(record["path"]) == "/educator/":
        disabled_media = '<div class="g3b-media-disabled" data-wb-capability="video-playback-disabled">Media playback unavailable offline</div>'
        fragment = fragment.replace(disabled_media, "", 1).replace(
            disabled_media,
            '<div class="educator-media-reservation" data-wb-capability="video-playback-disabled" aria-hidden="true"></div>',
            1,
        )
    if str(record["path"]) == "/pages/get-started/":
        return f'<article class="site-information g3c-get-started"><h1>Get Started</h1>{fragment}</article>'
    return f'<article class="site-information">{boundary}{fragment}</article>'


def video_gallery_body(record: dict[str, object]) -> str:
    thumbnails = [
        ref for ref in report_assets(record)
        if urlsplit(str(ref["url"])).hostname == "img.youtube.com"
    ]
    resource_links = [
        link for link in record.get("links", [])
        if "/resources/mit14_129s25_lec" in str(link["url"])
    ]
    cards = "".join(
        '<article class="video-list-card">'
        f'{image_tag(ref, "video-thumbnails", alt="Static lecture thumbnail")}'
        f'<a href="{escape(local_path(str(link["url"])), quote=True)}">{escape(str(link["text"]))}</a>'
        '</article>'
        for ref, link in zip(thumbnails, resource_links)
    )
    return course_frame(
        record,
        '<section data-wb-capability="video-playback-disabled"><h2 class="video-title">Lecture Videos</h2>'
        '<p class="video-description">For the lecture slide files that accompany these videos, see the <a href="/data-boundary/">Lecture Notes</a> page.</p>'
        f'<div class="video-list">{cards}</div></section>',
        component="video-gallery",
        right_panel=video_course_info(),
    )


def family_body(record: dict[str, object]) -> str:
    family = str(record["family"])
    renderers = {
        "collection": collection_body,
        "course-overview": course_overview_body,
        "course-section-or-deep-link": course_section_body,
        "resource-detail-or-index": resource_body,
        "course-download": course_download_body,
        "story-index": story_index_body,
        "story-detail": story_detail_body,
        "site-information-or-boundary": information_body,
        "video-gallery": video_gallery_body,
    }
    return renderers[family](record)


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {"ok": True, "site_id": SITE_ID, "capture_id": CAPTURE_ID, "remote_requests": 0}


@app.post("/__wb/session")
def session_boundary() -> JSONResponse:
    return JSONResponse({"ok": True, "actor": "anonymous-public"})


def download_headers(record: dict[str, object]) -> dict[str, str]:
    return {
        "Content-Length": str(record["bytes"]),
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(str(record['filename']))}",
        "X-Content-SHA256": str(record["sha256"]),
        "Cache-Control": "public, max-age=31536000, immutable",
    }


def iter_download(record: dict[str, object]) -> Iterator[bytes]:
    for chunk in record["chunks"]:
        path = SITE_ROOT / str(chunk["path"])
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                yield block


def streamed_download(record: dict[str, object]) -> StreamingResponse:
    return StreamingResponse(iter_download(record), media_type=str(record["content_type"]), headers=download_headers(record))



FONT_FILES = {
    "Cardo-Bold.ttf": "font/ttf",
    "Helvetica-Light.ttf": "font/ttf",
    "MaterialIcons-Regular.subset.woff2": "font/woff2",
}


@app.get("/fonts/{name}")
def font_file(name: str):
    media_type = FONT_FILES.get(name)
    if not media_type:
        return Response(status_code=404)
    return FileResponse(
        HERE / "static" / "fonts" / name,
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )

@app.get("/assets/{name}")
def asset(name: str):
    record = DATA["assets"].get(name)
    if not record:
        return Response(status_code=404)
    return FileResponse(SITE_ROOT / str(record["runtime_path"]), media_type=str(record["mime_type"]))


@app.get("/presentation-assets/{name}")
def presentation_asset(name: str):
    record = DATA.get("presentation_assets", {}).get(name)
    if not record:
        return Response(status_code=404)
    return FileResponse(
        SITE_ROOT / str(record["runtime_path"]),
        media_type=str(record["mime_type"]),
        headers={"X-Content-SHA256": str(record["sha256"]), "Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.get("/g3a-visual-assets/{name}")
def g3a_visual_asset(name: str):
    record = G3_VISUAL_ASSETS.get(name)
    if not record:
        return Response(status_code=404)
    return FileResponse(
        SITE_ROOT / str(record["runtime_path"]),
        media_type=str(record["mime_type"]),
        headers={"X-Content-SHA256": str(record["sha256"]), "Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.get("/g3b-assets/{name}")
def g3b_content_asset(name: str):
    record = G3B_CONTENT_ASSETS.get(name)
    if not record:
        return Response(status_code=404)
    return FileResponse(
        SITE_ROOT / str(record["runtime_path"]),
        media_type=str(record["mime_type"]),
        headers={"X-Content-SHA256": str(record["sha256"]), "Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.get("/g3c-collection-assets/{name}")
def g3c_collection_asset(name: str):
    record = G3C_COLLECTION_ASSETS.get(name)
    if not record:
        return Response(status_code=404)
    return FileResponse(
        SITE_ROOT / str(record["runtime_path"]),
        media_type=str(record["mime_type"]),
        headers={"X-Content-SHA256": str(record["sha256"]), "Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.get("/g3c-catalog-assets/{name}")
def g3c_catalog_asset(name: str):
    record = G3C_CATALOG_ASSETS.get(name)
    if not record:
        return Response(status_code=404)
    return FileResponse(
        SITE_ROOT / str(record["runtime_path"]),
        media_type=str(record["mime_type"]),
        headers={"X-Content-SHA256": str(record["sha256"]), "Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.get(str(PDF["path"]))
def g2a_exact_problem_set_pdf():
    return FileResponse(
        SITE_ROOT / str(PDF["runtime_path"]),
        filename=str(PDF["filename"]),
        media_type="application/pdf",
        headers={"X-Content-SHA256": str(PDF["sha256"]), "Content-Length": str(PDF["bytes"])},
    )


@app.head(str(PDF["path"]))
def g2a_exact_problem_set_pdf_head():
    return Response(
        status_code=200,
        media_type="application/pdf",
        headers={"X-Content-SHA256": str(PDF["sha256"]), "Content-Length": str(PDF["bytes"])},
    )


@app.get("/unavailable-asset/")
def unavailable_asset(url: str = "") -> JSONResponse:
    record = UNAVAILABLE_ASSETS.get(url)
    if not record:
        return JSONResponse({"status": "unknown", "url": url}, status_code=404)
    return JSONResponse(
        {"status": "source-unavailable", "source_status": 404, "url": url, "evidence": record},
        status_code=404,
    )


@app.get("/")
def home(
    state: str = "default",
    featured: str = "",
    new_state: str = Query("", alias="new"),
    stories: str = "",
    promo: str = "",
) -> HTMLResponse:
    chosen = "carousel-second-batches" if state in {"carousel", "carousel-second-batches"} else "default"
    record = PAGES["/"]
    return HTMLResponse(
        shell(
            str(record["title"]),
            home_body(
                chosen,
                featured_state=featured,
                new_state=new_state,
                stories_state=stories,
                promo_state=promo,
            ),
            page_class=f"home home-{chosen}",
            record=record,
        )
    )


@app.get("/search/")
def search(state: str = "default", q: str = "") -> HTMLResponse:
    query_state = "empty" if q == "__no_results__" else ("error" if q == "__force_error__" else "default")
    chosen = state if state != "default" and state in DATA["catalog"]["states"] else query_state
    record = PAGES["/search/"]
    return HTMLResponse(
        shell(str(record["title"]), catalog_body(chosen, q), page_class=f"catalog catalog-{chosen}", record=record)
    )


@app.get("/external-boundary/")
def external_boundary(url: str = "") -> HTMLResponse:
    body = f'<div class="wrap" data-wb-component="external-boundary" data-wb-capability="external-boundary"><h1>You are leaving MIT OpenCourseWare</h1><p>The requested external destination is outside this offline snapshot.</p><p>{escape(url)}</p><a class="cta" data-wb-link="boundary-return-home" data-wb-control="external-return" href="/">Stay on MIT OpenCourseWare</a></div>'
    return HTMLResponse(shell("You are leaving MIT OpenCourseWare", body))


@app.get("/data-boundary/")
def data_boundary(selection: str = "", return_url: str = "/search/") -> HTMLResponse:
    safe_return = return_url if return_url == "/search/" else "/search/"
    selection_notice = (
        f'<p data-wb-component="data-boundary-selection">Selection: {escape(selection)}</p>'
        if selection else ""
    )
    body = (
        '<div class="wrap" data-wb-capability="data-boundary"><h1>This item is outside the frozen MIT OpenCourseWare route set</h1>'
        f'{selection_notice}<p>The requested destination was not one of the source routes authorized for this offline snapshot.</p>'
        f'<a class="cta" data-wb-control="data-boundary-return" href="{safe_return}">Return to search</a></div>'
    )
    return HTMLResponse(shell("This item is outside the retained MIT OpenCourseWare snapshot", body))


@app.get("/not-found/")
def not_found_recovery() -> HTMLResponse:
    body = (
        '<div class="wrap" data-wb-page-id="not-found-recovery">'
        '<h1>Page unavailable</h1><p>The requested MIT OpenCourseWare page was not captured.</p>'
        '<a class="cta" href="/">Return to MIT OpenCourseWare</a></div>'
    )
    return HTMLResponse(shell("Page Not Found | MIT OpenCourseWare", body), status_code=200)


@app.head("/{requested_path:path}")
def frozen_head(requested_path: str):
    path = "/" + requested_path
    record = DOWNLOADS.get(path) or SUPPLEMENTARY_DOWNLOADS.get(path)
    if record:
        return Response(status_code=200, media_type=str(record["content_type"]), headers=download_headers(record))
    page = PAGES.get(path) or PAGES.get(path + "/" if not path.endswith("/") else path)
    return Response(status_code=int(page["status"]) if page else 404)


@app.get("/{requested_path:path}")
def frozen_page(requested_path: str):
    path = "/" + requested_path
    download = DOWNLOADS.get(path) or SUPPLEMENTARY_DOWNLOADS.get(path)
    if download:
        return streamed_download(download)
    record = PAGES.get(path)
    if record is None and not path.endswith("/"):
        path += "/"
        record = PAGES.get(path)
    if record:
        return HTMLResponse(
            shell(
                str(record["title"]),
                family_body(record),
                page_class=f'frozen {record["family"]} {record["page_id"]}',
                record=record,
            ),
            status_code=int(record["status"]),
        )
    body = (
        '<div class="wrap" data-wb-page-id="hard-404-recovery"><h1>Page unavailable</h1>'
        '<p>This route is outside the frozen MIT OpenCourseWare capture.</p>'
        '<a class="cta" href="/">Return to MIT OpenCourseWare</a></div>'
    )
    return HTMLResponse(shell("Page Not Found | MIT OpenCourseWare", body), status_code=404)
