"""Minimal WebsiteBench offline clone application."""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse


SITE_ID = "33"
DISPLAY_NAME = "Coursera"
app = FastAPI(title=DISPLAY_NAME)


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {"ok": True, "site_id": SITE_ID}


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>""" + DISPLAY_NAME + """</title><style>body{font:16px system-ui;margin:0;background:#f6f7f9;color:#18202a}main{max-width:54rem;margin:12vh auto;padding:3rem;background:white;border-radius:1rem;box-shadow:0 1rem 3rem #18202a18}h1{font-size:clamp(2rem,6vw,4rem);margin:0 0 1rem}p{line-height:1.6}</style></head>
<body><main><p>WebsiteBench offline contribution scaffold</p><h1>""" + DISPLAY_NAME + """</h1><p>This local page is ready for source-grounded implementation.</p></main></body></html>"""
