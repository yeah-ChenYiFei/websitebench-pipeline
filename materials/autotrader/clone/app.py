"""Offline AutoTrader clone, grounded in the supplied SingleFile snapshots."""
from __future__ import annotations

import html, json, re, time
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
try:
    from .backend.site_backend_integration import open_site_services
except ImportError:
    from backend.site_backend_integration import open_site_services

ROOT=Path(__file__).resolve().parent; PAGES=ROOT/"pages"; app=FastAPI(title="AutoTrader Offline Clone")
SITE_BACKEND, AUTH_STORE = open_site_services()
SESSION_COOKIE = SITE_BACKEND.session_cookie
SESSION_COOKIE_NAME = str(SESSION_COOKIE["name"])
AUTH_STORE.seed_account(
    subject_id="demo-driver",
    email="demo@example.test",
    display_name="Demo Driver",
    password="demo-password",
)

def _auth_session(request: Request) -> tuple[str, dict]:
    return AUTH_STORE.ensure_session(request.cookies.get(SESSION_COOKIE_NAME))

def _set_auth_cookie(response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        secure=bool(SESSION_COOKIE["secure"]),
        httponly=bool(SESSION_COOKIE["httponly"]),
        samesite=str(SESSION_COOKIE["samesite"]).lower(),
        path=str(SESSION_COOKIE["path"]),
    )
def _session_state(request: Request) -> dict | None:
    return AUTH_STORE.resolve_session(request.cookies.get(SESSION_COOKIE_NAME))

def _account(request: Request) -> dict | None:
    state=_session_state(request)
    return state.get("account") if state and state.get("authenticated") else None

def _owner_subject(request: Request) -> str | None:
    account=_account(request)
    return str(account["subject_id"]) if account else None

def _listing_dict(row) -> dict:
    return {
        "id":row["listing_id"],"make":row["make"],"year":row["year"],
        "mileage":row["mileage"],"price":row["price"],
        "description":row["description"],"photo_count":row["photo_count"],
        "status":row["status"],"version":row["version"],
    }

def _owned_listing(owner: str, listing_id: str):
    with SITE_BACKEND.lifecycle.connection() as connection:
        return connection.execute(
            "SELECT * FROM autotrader_listings WHERE listing_id=? AND owner_subject_id=?",
            (listing_id,owner),
        ).fetchone()

def _owned_listings(owner: str) -> list:
    with SITE_BACKEND.lifecycle.connection() as connection:
        return connection.execute(
            "SELECT * FROM autotrader_listings WHERE owner_subject_id=? ORDER BY updated_at DESC,listing_id DESC",
            (owner,),
        ).fetchall()

def _state_owner(request: Request) -> tuple[str,str]:
    token,state=_auth_session(request)
    account=state.get("account") if state else None
    if account:return token,"account:"+str(account["subject_id"])
    return token,"session:"+AUTH_STORE.session_owner_digest(token)

def _listing_state_owner(request: Request) -> tuple[str,str]:
    token,state=_auth_session(request)
    account=state.get("account") if state else None
    if account:return token,str(account["subject_id"])
    return token,"session:"+AUTH_STORE.session_owner_digest(token)

def _saved_rows(request:Request,kind:str|None=None) -> tuple[str,list]:
    token,owner=_state_owner(request)
    sql="SELECT item_kind,item_id,created_at FROM autotrader_saved_items WHERE owner_key=?"
    values=[owner]
    if kind:sql+=" AND item_kind=?";values.append(kind)
    sql+=" ORDER BY created_at,item_id"
    with SITE_BACKEND.lifecycle.connection() as connection:
        rows=connection.execute(sql,values).fetchall()
    return token,rows
def _slug(v:str)->str:return re.sub(r"[^a-z0-9]+","-",v.lower()).strip("-")
SNAPSHOTS=sorted(PAGES.glob("*.html"), key=lambda p: ("2026_8_22" not in p.name, p.name)); AUTO_SNAPSHOTS=[p for p in SNAPSHOTS if "atlassian" not in p.name.lower()]
SNAPSHOT_ROUTES={f"/snapshot/{_slug(p.stem)}":p for p in AUTO_SNAPSHOTS}
def _captured_url(page):
    source=page.read_text(encoding="utf-8",errors="ignore")
    match=re.search(r"(?:^|\n)\s*url:\s*((?:https?://|about:blank#offline-)[^\s<]+)",source,re.I)
    if not match:return None
    captured=match.group(1).rstrip("\"'")
    if captured.startswith("about:blank#offline-"):
        captured="https://"+captured.removeprefix("about:blank#offline-")
    parsed=urlparse(captured)
    return parsed.path or "/"
CAPTURED_ROUTES={}
for _page_file in AUTO_SNAPSHOTS:
    _captured_path=_captured_url(_page_file)
    if _captured_path and _captured_path not in CAPTURED_ROUTES:
        CAPTURED_ROUTES[_captured_path]=_page_file
EXACT_ROUTES=CAPTURED_ROUTES
def _score(path,p):
    return sum(t in _slug(p.stem) for t in re.split(r"[/_?=&-]+",path.lower()) if len(t)>2)
def _route_map():
    out={}
    for page in AUTO_SNAPSHOTS:
        source=page.read_text(encoding="utf-8",errors="ignore")
        for groups in re.findall(r'''(?:href|action)\s*=\s*(?:"([^"]+)"|'([^']+)'|([^\s>]+))''',source,re.I):
            raw=html.unescape(next((v for v in groups if v),"")); parsed=urlparse(raw)
            if parsed.netloc and "autotrader.co.uk" not in parsed.netloc:continue
            path=parsed.path or "/"
            if not path.startswith(("/cars","/secure","/selling","/bikes","/vans","/motorhomes","/caravans","/trucks","/farm","/plant")):continue
            best=max(AUTO_SNAPSHOTS,key=lambda p:_score(path,p),default=None)
            if best and (path not in out or _score(path,best)>_score(path,out[path])):out[path]=best
    return out
INTERNAL_ROUTE_MAP=_route_map()
def _page(*parts):
    for part in parts:
        matches=[p for p in AUTO_SNAPSHOTS if part.lower() in p.name.lower()]
        if matches:
            return matches[0]
    return None
def _snapshot(path):
    if path in EXACT_ROUTES:return EXACT_ROUTES[path]
    if path in SNAPSHOT_ROUTES:return SNAPSHOT_ROUTES[path]
    if path in INTERNAL_ROUTE_MAP:return INTERNAL_ROUTE_MAP[path]
    score,p=max(((_score(path,p),p) for p in AUTO_SNAPSHOTS),default=(0,None));return p if score else None
def _is_frozen(path):
    return (path.startswith('/checkout/') or path.startswith('/payment/'))
def frozen_page(path):
    return HTMLResponse(shell('This feature is frozen in the offline clone',"<div class='notice warn'><p>This route is outside the frozen AutoTrader implementation scope.</p><a class='button' href='/cars/used'>Return to used cars</a></div>",path),status_code=404)
ROUTES={"/":("Autotrader UK - New and Used Cars For Sale",),"/cars":("Autotrader UK",),"/cars/used":("Used Cars For Sale",),"/cars/new":("New Car Deals",),"/buy-a-car-online":("Buy a Car Online",),"/sell-my-car":("Sell My Car",),"/sign-in":("Sign In",),"/electric-cars":("Electric Cars",),"/used-vans":("Find used vans",),"/used-motorbikes":("Find used motorbikes",),"/car-leasing":("Car Leasing Deals",),"/car-reviews":("Car reviews",),"/bike-reviews":("Bike reviews",),"/sell-my-van":("Sell My Van",),"/sell-my-motorbike":("Sell My Motorbike",),"/value-my-car":("Free Car Valuation",)}
CARS=[
 {"id":"ford-fiesta","title":"2022 Ford Fiesta 1.0 EcoBoost","make":"Ford","model":"Fiesta","price":14995,"year":2022,"mileage":24100,"body":"Hatchback","rating":"4.8","spec":"Manual · Petrol","location":"London","availability":"Available"},
 {"id":"bmw-320d","title":"2021 BMW 3 Series 320d","make":"BMW","model":"3 Series","price":22490,"year":2021,"mileage":31400,"body":"Saloon","rating":"4.7","spec":"Automatic · Diesel","location":"Manchester","availability":"Available"},
 {"id":"vw-tiguan","title":"2020 Volkswagen Tiguan 2.0 TDI","make":"Volkswagen","model":"Tiguan","price":18950,"year":2020,"mileage":43800,"body":"SUV","rating":"4.6","spec":"Automatic · Diesel","location":"Bristol","availability":"Reserved"}]
_CATALOG=[("Ford","Focus","Hatchback"),("Ford","Kuga","SUV"),("BMW","1 Series","Hatchback"),("BMW","X3","SUV"),("Volkswagen","Golf","Hatchback"),("Volkswagen","Passat","Estate"),("Audi","A3","Hatchback"),("Audi","A4","Saloon"),("Toyota","Corolla","Hatchback"),("Toyota","RAV4","SUV"),("Nissan","Qashqai","SUV"),("Vauxhall","Corsa","Hatchback")]
_LOCATIONS=["London","Manchester","Bristol","Birmingham","Leeds","Glasgow","Cardiff","Nottingham"]
CARS += [{"id":f"local-{i:03d}","title":f"{2017+i%9} {make} {model} Local Edition","make":make,"model":model,"price":6995+(i*379)%28000,"year":2017+i%9,"mileage":4500+(i*1739)%92000,"body":body,"rating":f"{4+(i%10)/10:.1f}","spec":("Automatic" if i%3==0 else "Manual")+" · "+("Diesel" if i%4==0 else "Petrol"),"location":_LOCATIONS[i%len(_LOCATIONS)],"availability":"Reserved" if i%11==0 else "Available"} for i in range(1,198) for make,model,body in [_CATALOG[(i-1)%len(_CATALOG)]]]
assert len(CARS)==200
CATEGORY_PRODUCTS={
 "vans":{"title":"2024 Ford Transit Custom Limited","make":"Ford","model":"Transit Custom","price":28995,"year":2024,"mileage":8200,"body":"Panel Van","spec":"Automatic · Diesel","location":"Birmingham","image":"van"},
 "bikes":{"title":"2023 Yamaha MT-07","make":"Yamaha","model":"MT-07","price":6499,"year":2023,"mileage":1800,"body":"Naked Bike","spec":"Manual · Petrol","location":"Leeds","image":"bike"},
 "motorhomes":{"title":"2022 Auto-Trail Frontier Scout","make":"Auto-Trail","model":"Frontier Scout","price":74995,"year":2022,"mileage":12600,"body":"Motorhome","spec":"Automatic · Diesel","location":"Bristol","image":"motorhome"},
 "caravans":{"title":"2024 Swift Challenger 560","make":"Swift","model":"Challenger 560","price":23995,"year":2024,"mileage":0,"body":"Touring Caravan","spec":"Twin axle · 4 berth","location":"Nottingham","image":"caravan"},
 "trucks":{"title":"2021 DAF XF 480 Space Cab","make":"DAF","model":"XF 480","price":52900,"year":2021,"mileage":214000,"body":"Artic Truck","spec":"Automatic · Diesel","location":"Manchester","image":"truck"},
 "farm":{"title":"2020 John Deere 6155R","make":"John Deere","model":"6155R","price":89500,"year":2020,"mileage":3200,"body":"Tractor","spec":"AutoPowr · 155 hp","location":"York","image":"farm"},
 "plant":{"title":"2022 JCB 3CX Compact","make":"JCB","model":"3CX Compact","price":46995,"year":2022,"mileage":1450,"body":"Plant Machinery","spec":"4WD · Diesel","location":"Coventry","image":"plant"},
 "cars":{"title":"2024 Volkswagen Polo R-Line","make":"Volkswagen","model":"Polo R-Line","price":24995,"year":2024,"mileage":1200,"body":"Hatchback","spec":"Automatic · Petrol","location":"London","image":"car"}
}
# Build an index from the supplied leasing/listing snapshots so every card ID
# gets its own title and price instead of falling back to one generic vehicle.
PRODUCT_INDEX={}
for _snapshot_file in AUTO_SNAPSHOTS:
 _snapshot_source=_snapshot_file.read_text(encoding="utf-8",errors="ignore")
 for _match in re.finditer(r"/(cars|vans)/leasing/product/(\d+)[^\"'<>]*.*?<h3[^>]*>(.*?)</h3>(.*?)(?=<a href=|</article>)",_snapshot_source,re.I|re.S):
  _category,_product_id,_title,_tail=_match.groups(); _category=_category.lower();_title=re.sub(r"<[^>]+>"," ",html.unescape(_title)); _title=re.sub(r"\s+"," ",_title).strip()
  _tail_text=re.sub(r"<[^>]+>"," ",html.unescape(_tail));_tail_text=re.sub(r"\s+"," ",_tail_text).strip()
  _subtitle_match=re.search(r"<p[^>]*subtitle[^>]*>(.*?)</p>",_tail,re.I|re.S)
  _subtitle=re.sub(r"<[^>]+>"," ",html.unescape(_subtitle_match.group(1))) if _subtitle_match else "";_subtitle=re.sub(r"\s+"," ",_subtitle).strip()
  if _subtitle and _subtitle not in _title:_title=f"{_title} {_subtitle}"
  _money=re.search(r"£\s*([\d,]+)",_tail_text)
  _initial=re.search(r"£\s*([\d,]+)\s*initial payment",_tail_text,re.I)
  _contract=re.search(r"([\d,]+)\s*month contract",_tail_text,re.I)
  _miles=re.search(r"([\d,]+)\s*miles p/a",_tail_text,re.I)
  _delivery=re.search(r"([A-Z][a-z]+\s+\d{4}\s+delivery)",_tail_text)
  _vat=re.search(r"Per month\s*\(([^)]+VAT)\)",_tail_text,re.I)
  _image=re.search(r'(<picture\b[^>]*class="[^"]*atds-image__container[^"]*"[^>]*>.*?</picture>)',_tail,re.I|re.S)
  _product_key=(_category,_product_id)
  if _title and _product_key not in PRODUCT_INDEX:
   PRODUCT_INDEX[_product_key]={"title":_title,"price":int(_money.group(1).replace(",","")) if _money else None,"initial_payment":_initial.group(1) if _initial else None,"contract_months":_contract.group(1) if _contract else None,"annual_miles":_miles.group(1) if _miles else None,"delivery":_delivery.group(1) if _delivery else None,"vat_label":_vat.group(1) if _vat else None,"image_html":_image.group(1) if _image else None}
def e(v):return html.escape(str(v),quote=True)
def _snapshot_vehicle_images():
 source=EXACT_ROUTES.get("/cars/used")
 if not source:return []
 images=[]
 for tag in re.findall(r"<img\b[^>]*>",source.read_text(encoding="utf-8",errors="ignore"),re.I):
  width=re.search(r'''\bwidth\s*=\s*["']?(\d+)(?:px)?''',tag,re.I)
  height=re.search(r'''\bheight\s*=\s*["']?(\d+)(?:px)?''',tag,re.I)
  if not width or not height or (width.group(1),height.group(1)) not in {("339","132"),("240","94")}:continue
  match=re.search(r'''\bsrc\s*=\s*(?:"([^"]+)"|'([^']+)'|([^\s>]+))''',tag,re.I)
  if not match:continue
  src=html.unescape(next(value for value in match.groups() if value))
  if src.startswith("data:image/") and src not in images:images.append(src)
 return images
CARD_IMAGES=_snapshot_vehicle_images()
def _vehicle_image(car):
 if not CARD_IMAGES:return "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 640 300'%3E%3Crect width='640' height='300' fill='%23f2f3f5'/%3E%3C/svg%3E"
 return CARD_IMAGES[sum(ord(char) for char in car["id"])%len(CARD_IMAGES)]
def shell(title,body,path):
 return f"""<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>{e(title)} | Autotrader UK</title><link rel=canonical href='{e(path)}'><style>
*{{box-sizing:border-box}}:root{{--ink:#24242f;--muted:#626270;--line:#dedee4;--blue:#0019ff;--blue-dark:#0015d6;--red:#ec153d;--page:#f7f7f8}}body{{margin:0;background:var(--page);color:var(--ink);font:15px/1.5 Arial,Helvetica,sans-serif}}a{{color:inherit}}.utility,.primary-nav{{background:#fff;border-bottom:1px solid #ededf0}}.utility-inner,.nav-inner{{max-width:1180px;margin:auto;display:flex;align-items:center}}.utility-inner{{min-height:30px;gap:18px;font-size:11px;color:#4f4f59}}.utility a,.primary-nav a{{text-decoration:none}}.nav-inner{{height:66px;gap:25px}}.brand{{font-size:25px;font-weight:800;letter-spacing:-1.5px;margin-right:10px;display:flex;align-items:center}}.brand-mark{{width:20px;height:14px;margin-right:5px;position:relative}}.brand-mark:before,.brand-mark:after{{content:'';position:absolute;left:0;width:20px;height:6px;transform:skew(-25deg);border-radius:1px}}.brand-mark:before{{top:0;background:var(--red)}}.brand-mark:after{{bottom:0;background:var(--blue)}}.nav-link{{font-weight:650;font-size:13px;white-space:nowrap}}.nav-spacer{{flex:1}}.nav-icon{{font-size:12px;text-align:center;min-width:50px}}main{{max-width:1180px;margin:0 auto;padding:26px 24px 72px}}h1{{font-size:34px;line-height:1.15;letter-spacing:-.7px;margin:10px 0 24px}}h2{{line-height:1.2}}.path{{font-size:12px;color:var(--muted);margin-top:4px}}.muted,.eyebrow{{color:var(--muted)}}.eyebrow{{font-size:12px;text-transform:uppercase;letter-spacing:.08em;font-weight:700}}.panel,.card,.gallery,.notice,.listing-row,.empty-state,.vehicle-summary{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:22px;margin:18px 0;box-shadow:0 2px 9px rgba(24,24,32,.05)}}.grid,.cards,.action-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(225px,1fr));gap:16px}}.cards{{align-items:stretch}}.card{{margin:0;padding:0;overflow:hidden}}.card-body{{padding:18px}}.vehicle-thumb{{height:145px;background:linear-gradient(145deg,#dbe9f4 0 56%,#b9c3ca 57% 60%,#e8ebee 61%);position:relative;overflow:hidden}}.vehicle-thumb:before{{content:'';position:absolute;width:150px;height:48px;border-radius:40px 50px 15px 14px;background:#ffe000;left:50%;top:52%;transform:translate(-50%,-50%);box-shadow:inset 0 -8px #d7bd00}}.vehicle-thumb:after{{content:'';position:absolute;width:112px;height:23px;border-radius:30px 35px 0 0;background:#263746;left:50%;top:43%;transform:translate(-50%,-50%)}}.card h2{{font-size:17px;margin:0 0 9px}}.price{{font-size:24px;font-weight:800}}label{{display:flex;flex-direction:column;gap:7px;font-weight:700}}input,select,textarea{{width:100%;font:inherit;padding:12px;border:1px solid #9999a4;border-radius:5px;background:#fff;color:var(--ink)}}input:focus,select:focus,textarea:focus{{outline:3px solid rgba(0,25,255,.18);border-color:var(--blue)}}button,.button{{background:var(--blue);color:#fff;border:0;border-radius:999px;padding:11px 18px;font-weight:750;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;justify-content:center;margin:3px;min-height:43px}}button:hover,.button:hover{{background:var(--blue-dark)}}.secondary{{background:#fff;color:var(--ink);border:1px solid #696974}}.secondary:hover{{background:#f0f0f3}}.danger{{background:#ad1634}}.ok{{border-left:5px solid #16834b;background:#eef9f3}}.warn{{border-left:5px solid #d77a00;background:#fff7e8}}.gallery,.vehicle-summary,.auth-layout{{display:grid;grid-template-columns:1.2fr 1fr;gap:26px}}.photo{{min-height:310px;border-radius:10px;background:linear-gradient(145deg,#d9e9f5,#edf0f1);display:grid;place-items:center;color:#555;font-weight:700}}.listing-row{{display:flex;align-items:center;justify-content:space-between;gap:20px}}.row-actions{{display:flex;flex-wrap:wrap;justify-content:flex-end}}.action-card{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:22px;text-decoration:none;display:flex;flex-direction:column;gap:8px}}.action-card:hover{{border-color:var(--blue);box-shadow:0 3px 12px rgba(0,25,255,.09)}}.table-wrap{{overflow:auto;background:#fff;border-radius:12px;border:1px solid var(--line)}}table{{width:100%;border-collapse:collapse}}th,td{{padding:14px;border-bottom:1px solid var(--line);text-align:left}}.error{{color:#b42318}}[role=status]:not(:empty){{padding:10px;font-weight:700}}@media(max-width:760px){{.utility{{display:none}}.nav-inner{{height:55px;padding:0 16px;gap:12px}}.nav-link{{display:none}}main{{padding:18px 16px 60px}}.gallery,.vehicle-summary,.auth-layout{{grid-template-columns:1fr}}.listing-row{{display:block}}.cards{{grid-template-columns:1fr}}}}</style></head><body><header><div class=utility><div class=utility-inner><a href=/cars>Cars</a><a href=/vans>Vans</a><a href=/bikes>Bikes</a><a href=/motorhomes>Motorhomes</a><a href=/caravans>Caravans</a><a href=/trucks>Trucks</a></div></div><nav class=primary-nav aria-label='Primary navigation'><div class=nav-inner><a class=brand href=/><span class=brand-mark></span>Autotrader</a><a class=nav-link href=/cars/used>Used cars</a><a class=nav-link href=/cars/new>New cars</a><a class=nav-link href=/selling/find-car>Sell your car</a><a class=nav-link href=/value-my-car>Value your car</a><a class=nav-link href=/car-reviews>Car reviews</a><span class=nav-spacer></span><a class=nav-icon href=/cars/used>♡<br>Saved</a><a class=nav-icon data-offline-global-account href=/secure/signin>♙<br>Account</a></div></nav></header><main><div class=path>Canonical path: {e(path)}</div><h1>{e(title)}</h1>{body}</main><script>async function keep(kind,id,button){{let r=await fetch('/api/saved',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{kind:kind,item_id:id}})}});if(r.ok){{await r.json();button.textContent=kind==='car'?'Saved':kind==='compare'?'Added to compare':'Alert created';}}}}
 document.querySelectorAll('[data-save]').forEach(b=>b.onclick=()=>keep('car',b.dataset.save,b));document.querySelectorAll('[data-compare]').forEach(b=>b.onclick=()=>keep('compare',b.dataset.compare,b));document.querySelectorAll('[data-alert]').forEach(b=>b.onclick=()=>keep('alert',b.dataset.alert,b));</script>{ACCOUNT_SYNC_SCRIPT}</body></html>""".replace("class=nav-icon href=/cars/used>♡<br>Saved","class=nav-icon href=/cars/saved>♡<br>Saved")
def cards(cars):
 if not cars:return "<div class='notice warn'><h2>No cars found</h2><p>We couldn't find any cars matching those filters.</p><a class=button href=/cars/used>Clear filters</a></div>"
 return "<div class='cards result-list'>"+"".join(f"<article class=card><img class=vehicle-thumb src='{e(_vehicle_image(c))}' alt='{e(c['title'])}' loading=lazy><div class=card-body><h2><a href='/cars/used/listing/{c['id']}'>{e(c['title'])}</a></h2><p class=price>£{c['price']:,}</p><p>{c['mileage']:,} miles · {e(c['spec'])} · {e(c['body'])}</p><p>Rating {c['rating']} · {c['availability']}</p><button data-save='{c['id']}'>Save</button><button class=secondary data-compare='{c['id']}'>Compare</button></div></article>" for c in cars)+"</div>"
def category_product(path,request):
 match=re.match(r"^/(cars|vans|bikes|motorhomes|caravans|trucks|farm|plant)(?:/leasing)?/(?:product|listing)/([^/?]+)$",path)
 if not match:return None
 category,product_id=match.groups(); product_key=(category,product_id);product=dict(CATEGORY_PRODUCTS.get(category,CATEGORY_PRODUCTS["cars"])); product.update({k:v for k,v in PRODUCT_INDEX.get(product_key,{}).items() if v}); product["id"]=product_id
 if "/leasing/product/" in path and product_key in PRODUCT_INDEX:
  initial=product.get("initial_payment","Unavailable");contract=product.get("contract_months","Unavailable");miles=product.get("annual_miles","Unavailable");delivery=product.get("delivery","Delivery date unavailable");vat=product.get("vat_label","VAT status unavailable");image_html=product.get("image_html") or "Vehicle image unavailable in the supplied product-card evidence"
  body=f"""<div class='gallery'><div class=photo aria-label='{e(product['title'])} product-card image'>{image_html}</div><div><p class=eyebrow>Lease a brand new {e('van' if category=='vans' else 'car')}</p><h2>{e(product['title'])}</h2><p class=price>£{product['price']:,} per month <span class=muted>({e(vat)})</span></p><div class=panel><h3>Selected lease option</h3><p><b>£{e(initial)}</b> initial payment</p><p><b>{e(contract)}</b> month contract</p><p><b>{e(miles)}</b> miles p/a</p><p>{e(delivery)}</p></div><button id=lease-save>Save lease option locally</button><button class=secondary id=lease-review>Review this lease option</button><p id=lease-status role=status></p><p class=muted>The supplied evidence contains this leasing card and selected terms, but not a standalone captured product-detail page.</p></div></div><script>(function(){{var status=document.getElementById('lease-status');document.getElementById('lease-save').onclick=function(){{localStorage.setItem('saved-lease-{e(category)}-{e(product_id)}','1');this.textContent='Lease option saved';status.textContent='This lease option was saved only in this browser.'}};document.getElementById('lease-review').onclick=function(){{status.textContent='Review ready. No application or external request was submitted.'}}}})();</script>"""
  return HTMLResponse(source_shell(product["title"],body,path,f"/{category}/leasing"))
 body=f"""<div class='gallery'><div class=photo role=img aria-label='{e(product['title'])} image gallery'>{e(product['image'].title())} image gallery · 12 photos</div><div><p class=muted>{e(category.title())} · verified offline product</p><h2>£{product['price']:,}</h2><p>{product['mileage']:,} miles · {e(product['spec'])} · {e(product['body'])}</p><p><b>Seller:</b> verified dealer, {e(product['location'])}</p><div class=panel><h3>Customize your purchase</h3><div class=grid><label>Colour<select><option>Black</option><option>White</option><option>Blue</option></select></label><label>Annual mileage<select><option>5,000 miles</option><option>8,000 miles</option><option>10,000 miles</option></select></label><label>Contract length<select><option>24 months</option><option>36 months</option><option>48 months</option></select></label></div></div><button id=product-save>Save vehicle</button><button class=secondary id=product-compare>Compare</button><button class=button id=product-apply>Start application</button><p id=product-status role=status></p></div></div><section class=panel><h2>Specifications and history</h2><p>{e(product['title'])} · {e(product['spec'])} · dealer verified · history available offline.</p></section><script>(function(){{var s=document.getElementById('product-status'),save=document.getElementById('product-save'),compare=document.getElementById('product-compare'),apply=document.getElementById('product-apply');save.onclick=function(){{localStorage.setItem('saved-product-{e(product_id)}','1');s.textContent='Vehicle saved locally.';this.textContent='Saved';}};compare.onclick=function(){{s.textContent='Added to comparison locally.';this.textContent='Added to compare';}};apply.onclick=function(){{s.textContent='Application preview ready. No external application was submitted.';}};}})();</script>"""
 return HTMLResponse(shell(product["title"],body,path))
def synthetic(path,request):
 if path.startswith("/cars/used/listing/"):
  c=next((c for c in CARS if c["id"]==path.rsplit('/',1)[-1]),CARS[0])
  body=f"<div class=gallery><div class=photo>Photo gallery · 12 vehicle photos</div><div><h2>£{c['price']:,}</h2><p>{c['mileage']:,} miles · {e(c['spec'])} · {c['body']}</p><p><b>Seller:</b> verified dealer, {c['location']} · rating {c['rating']}</p><label>Configuration<select><option>Standard model</option><option>Premium trim</option></select></label><label>Colour<select><option>Blue</option><option>Black</option></select></label><button data-save={c['id']}>Save</button><button class=secondary data-compare={c['id']}>Compare</button><a class=button href='/contact-seller?car={c['id']}'>Contact / test drive</a></div></div><section class=panel><h2>Specifications and history</h2><p>Full service history · HPI clear · One previous owner · MOT valid.</p></section>"
  return HTMLResponse(source_shell(c["title"],body,path))
 generated=category_product(path,request)
 if generated is not None:return generated
 q=request.query_params
 if path=="/cars/used" and not q:
  return render(path)
 if path=="/secure/signin" and not q:
  return render(path)
 if path in {"/secure/signin","/secure/signin/preview"}:
  body="""<div class=auth-layout><form class=panel id=signin><label>Email address<input name=email type=email required autocomplete=username></label><label>Password<input name=password type=password required autocomplete=current-password></label><button>Sign in</button><button type=button class=secondary>Continue with Google</button><button type=button class=secondary>Continue with Apple</button><p id=signin-status role=status></p></form><aside class=panel><h2>New to Autotrader?</h2><p>Create a local account to save cars and manage adverts.</p><a class=button href=/secure/register>Create account</a></aside></div><p><a href=/password-recovery>Forgotten password?</a></p><script>
const signInForm=document.getElementById('signin'),signInStatus=document.getElementById('signin-status');
signInForm.addEventListener('submit',async event=>{event.preventDefault();let response=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(signInForm)))}),result=await response.json();signInStatus.textContent=response.ok?'Signed in locally.':result.error;if(response.ok)location.href='/secure/my-auto-trader'});
</script>"""
  return HTMLResponse(shell("Sign in",body,path))
 if path=="/secure/register":
  body="""<div class=auth-layout><form class='panel grid' id=reg><label>Name<input name=name required></label><label>Email<input name=email type=email required></label><label>Password<input name=password type=password minlength=8 required></label><label><span><input type=checkbox required> I agree to the <a href='/terms-and-conditions/advertising'>Terms</a> and <a href='/privacy-notice'>Privacy Policy</a></span></label><button>Continue</button><p id=reg-status role=status></p></form><form class='panel grid' id=verify hidden><h2>Verify your local email</h2><p>The offline outbox keeps verification on this device. No real email is sent.</p><button type=button id=open-inbox class=secondary>Open local inbox</button><label>Verification code<input name=code inputmode=numeric required></label><button>Verify and create account</button><p id=verify-status role=status></p></form></div><p><a href=/secure/signin>Return to sign in</a></p><script>
const registrationForm=document.getElementById('reg'),verificationForm=document.getElementById('verify'),registrationStatus=document.getElementById('reg-status'),verificationStatus=document.getElementById('verify-status'),openInbox=document.getElementById('open-inbox');
registrationForm.addEventListener('submit',async event=>{event.preventDefault();let response=await fetch('/api/auth/register',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(registrationForm)))}),result=await response.json();registrationStatus.textContent=response.ok?'Verification required. Open the local inbox.':result.error;if(response.ok)verificationForm.hidden=false});
openInbox.addEventListener('click',async()=>{let response=await fetch('/api/auth/local-mail?purpose=registration'),result=await response.json();if(response.ok){verificationForm.elements.code.value=result.verification_code;verificationStatus.textContent='Local verification code loaded.'}else verificationStatus.textContent=result.error});
verificationForm.addEventListener('submit',async event=>{event.preventDefault();let response=await fetch('/api/auth/register/verify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:verificationForm.elements.code.value})}),result=await response.json();verificationStatus.textContent=response.ok?'Account created locally.':result.error;if(response.ok)location.href='/secure/my-auto-trader'});
</script>"""
  return HTMLResponse(shell("Create your account",body,path))
 if path in {"/terms-and-conditions/advertising","/privacy-notice"}:
  heading="Advertising terms" if path.startswith("/terms-") else "Privacy notice"
  body=f"<div class='notice'><h2>{heading}</h2><p>This offline clone stores only synthetic local test data and never publishes adverts, contacts a dealer, or sends data to AutoTrader.</p><p>This page is local test guidance, not a copy of the live legal text.</p><a class=button href=/secure/register>Return to registration</a></div>"
  return HTMLResponse(shell(heading,body,path))
 if path=="/selling/review":
  try:photo_count=max(0,min(int(q.get("photo_count","0")),20))
  except ValueError:photo_count=0
  category=q.get("category","cars")
  payload={"category":category,"make":q.get("make","Ford"),"year":q.get("year","2022"),"mileage":q.get("mileage","24100"),"price":q.get("price","14995"),"description":q.get("description",""),"photo_count":photo_count}
  rows="".join(f"<tr><th>{a}</th><td>{e(b)}</td></tr>" for a,b in [("Category",category.replace("-"," ").title()),("Make",payload["make"]),("Year",payload["year"]),("Mileage",payload["mileage"]+" miles"),("Price","£"+payload["price"]),("Description",payload["description"] or "Not provided"),("Photos",f"{photo_count} selected for local preview")])
  fallback="/selling/confirmation?"+str(q)
  hidden="".join(f'<input type="hidden" name="{e(key)}" value="{e(value)}">' for key,value in payload.items())
  body=f'<table>{rows}</table><form method="post" action="/selling/submit" id="listing-submit-form">{hidden}<a class="button secondary" href=/cars/sell-my-car>Edit</a><a class="button" id="submit-listing" href="{e(fallback)}" onclick="event.preventDefault();this.closest(\'form\').requestSubmit()">Submit listing</a></form>'
  return HTMLResponse(shell("Review your advert",body,path))
 if path=="/cars/saved":
  token,rows=_saved_rows(request)
  vehicles=[];alerts=[]
  for row in rows:
   if row["item_kind"]=="car":
    vehicle=next((car for car in CARS if car["id"]==row["item_id"]),None)
    if vehicle:vehicles.append(vehicle)
   elif row["item_kind"]=="alert":alerts.append(row["item_id"].replace("-"," ").capitalize())
  if not vehicles and not alerts:
   body="<div class='empty-state'><h2>No saved cars or alerts yet</h2><p>Save a vehicle or search to find it here after refresh.</p><a class=button href=/cars/used>Browse used cars</a></div>"
  else:
   body=cards(vehicles) if vehicles else ""
   if alerts:body+="<section class=panel><h2>Saved alerts</h2><ul>"+"".join(f"<li>{e(alert)}</li>" for alert in alerts)+"</ul></section>"
  response=HTMLResponse(shell("Saved cars and alerts",body,path));_set_auth_cookie(response,token);return response
 if path=="/cars/used":
  found=CARS[:]
  for key,field in (("keyword","title"),("make","make"),("model","model"),("location","location"),("body","body")):
   if q.get(key):found=[c for c in found if q[key].lower() in c[field].lower()]
  for key,op in (("price",lambda c,v:c["price"]<=v),("year",lambda c,v:c["year"]>=v),("mileage",lambda c,v:c["mileage"]<=v)):
   if q.get(key,"").isdigit():found=[c for c in found if op(c,int(q[key]))]
  if q.get("sort")=="price-low":found.sort(key=lambda c:c["price"])
  if q.get("sort")=="price-high":found.sort(key=lambda c:c["price"],reverse=True)
  options=lambda values,key:"<option value=''>Any</option>"+"".join(f"<option {'selected' if q.get(key)==x else ''}>{x}</option>" for x in values)
  form=f"<form class='panel grid' method=get><label>Keyword<input name=keyword value='{e(q.get('keyword',''))}' placeholder='Ford Fiesta'></label><label>Make<select name=make>{options(['Ford','BMW','Volkswagen'],'make')}</select></label><label>Model<input name=model value='{e(q.get('model',''))}'></label><label>Location<input name=location value='{e(q.get('location',''))}'></label><label>Price up to<input type=number name=price value='{e(q.get('price',''))}'></label><label>Year from<input type=number name=year value='{e(q.get('year',''))}'></label><label>Mileage up to<input type=number name=mileage value='{e(q.get('mileage',''))}'></label><label>Body style<select name=body>{options(['Hatchback','SUV','Saloon'],'body')}</select></label><label>Sort<select name=sort><option>Recommended</option><option value=price-low>Price low to high</option><option value=price-high>Price high to low</option></select></label><button>Search cars</button></form>"
  return HTMLResponse(source_shell("Used cars for sale",form+f"<p><b>{len(found)} cars found</b> · <a href=/cars/compare>Compare selected</a></p>"+cards(found)+"<p><button data-alert=search>Create price/new-listing alert</button></p>",path))
 if path=="/cars/used/no-results":return RedirectResponse("/cars/used?keyword=no-such-vehicle-zzzz",302)
 if path=="/cars/compare":
  token,selected=_saved_rows(request,"compare");cars=[next((c for c in CARS if c["id"]==row["item_id"]),None) for row in selected];cars=[c for c in cars if c][:4]
  if len(cars)<2:
   response=HTMLResponse(shell("Compare cars","<div class='empty-state'><h2>Select at least two cars</h2><p>Add cars from the search results before comparing price, rating, specifications and availability.</p><a class=button href=/cars/used>Browse used cars</a></div>",path));_set_auth_cookie(response,token);return response
  headings="".join(f"<th>{e(c['title'])}</th>" for c in cars)
  rows="".join("<tr><th>"+label+"</th>"+"".join(f"<td>{value(c)}</td>" for c in cars)+"</tr>" for label,value in [("Price",lambda c:f"£{c['price']:,}"),("Rating",lambda c:c["rating"]),("Mileage",lambda c:f"{c['mileage']:,}"),("Specifications",lambda c:e(c["spec"])),("Availability",lambda c:e(c["availability"]))])
  response=HTMLResponse(shell("Compare cars",f"<div class=table-wrap><table><tr><th></th>{headings}</tr>{rows}</table></div><a class=button href=/cars/used>Back to results</a>",path));_set_auth_cookie(response,token);return response
 if path=="/contact-seller":
  car_id=q.get("car","");car=next((item for item in CARS if item["id"]==car_id),None)
  if not car:return HTMLResponse(shell("Vehicle unavailable","<div class='notice warn'><p>The selected vehicle is unavailable.</p><a class=button href=/cars/used>Back to used cars</a></div>",path),404)
  if not _account(request):
   next_path=quote(f"/contact-seller?car={car_id}")
   body=f'<div class="notice warn"><h2>Sign in is required</h2><p>Sign in before saving a local message or test-drive request.</p><a class=button href="/secure/signin?next={next_path}">Continue to sign in</a></div>'
   return HTMLResponse(shell("Contact the seller",body,path))
  body=f"""<p class='notice'>Contacting the seller about <b>{e(car['title'])}</b>. No message or test-drive request is sent externally.</p><form class='panel grid' id="contact-seller-form"><input type=hidden name=car_id value='{e(car_id)}'><label>Request<select name=request_type><option value=information>More information</option><option value=test-drive>Book a test drive</option></select></label><label>Message<textarea name=message required></textarea></label><button>Save request locally</button></form><p id=contact-status role=status></p><script>const contactForm=document.getElementById('contact-seller-form'),contactStatus=document.getElementById('contact-status');contactForm.addEventListener('submit',async event=>{{event.preventDefault();let response=await fetch('/api/contact-requests',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(Object.fromEntries(new FormData(contactForm)))}}),result=await response.json();contactStatus.textContent=response.ok?'Request saved locally. No message was sent.':result.error}})</script>"""
  return HTMLResponse(shell("Contact the seller",body,path))
 if path=="/selling/find-car" and q.get("edit"):
  owner=_owner_subject(request)
  if not owner:return RedirectResponse("/secure/signin?next="+quote("/selling/find-car?edit="+q["edit"]),status_code=303)
  row=_owned_listing(owner,q["edit"])
  if not row:return HTMLResponse(shell("Advert not found","<div class='notice warn'><p>This advert is unavailable or belongs to another account.</p><a class=button href=/account/history>Back to your adverts</a></div>",path),404)
  listing=_listing_dict(row)
  body=f"""<form class='panel grid' id="edit-listing-form" data-edit-listing="{e(listing['id'])}"><label>Make<input name=make required value="{e(listing['make'])}"><span class=error></span></label><label>Year<input name=year required type=number value="{listing['year']}"><span class=error></span></label><label>Mileage<input name=mileage required type=number value="{listing['mileage']}"><span class=error></span></label><label>Price (£)<input name=price required type=number value="{listing['price']}"><span class=error></span></label><label>Description<textarea name=description>{e(listing['description'])}</textarea></label><label>Photo count<input name=photo_count type=number min=0 max=20 value="{listing['photo_count']}"></label><input type=hidden name=expected_version value="{listing['version']}"><button>Save advert changes</button></form><p id=edit-status role=status></p><script>const editForm=document.getElementById('edit-listing-form'),editStatus=document.getElementById('edit-status');editForm.addEventListener('submit',async event=>{{event.preventDefault();let values=Object.fromEntries(new FormData(editForm));let response=await fetch('/api/listings/{e(listing['id'])}',{{method:'PATCH',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(values)}}),result=await response.json();editStatus.textContent=response.ok?'Advert changes saved locally.':result.error;if(response.ok)setTimeout(()=>location.assign('/account/listings/{e(listing['id'])}'),250)}})</script>"""
  return HTMLResponse(shell("Edit your advert",body,path))
 if path == "/selling/find-car":
  category=q.get("category","cars");labels={"cars":"car","vans":"van","bikes":"motorbike","motorhomes":"motorhome","caravans":"caravan","trucks":"truck","farm":"farm machinery","plant":"plant machinery"};label=labels.get(category,"vehicle")
  body=f"<p>Vehicle category: <b>{e(label.title())}</b>. Build a local advert preview without publishing anything externally.</p><input form=sell type=hidden name=category value='{e(category)}'>"+"""<form class='panel grid' id=sell novalidate><label>Make<input name=make required placeholder=Ford><span class=error></span></label><label>Year<input name=year required type=number placeholder=2022><span class=error></span></label><label>Mileage<input name=mileage required type=number placeholder=24100><span class=error></span></label><label>Price (£)<input name=price required type=number placeholder=14995><span class=error></span></label><label>Description<textarea name=description></textarea></label><label>Photos<input name=photos type=file accept='image/*' multiple><span class=muted>Files stay in this browser; only their count is used in the local preview.</span></label><button>Review listing</button></form><script>sell.onsubmit=x=>{x.preventDefault();let bad=false;sell.querySelectorAll('[required]').forEach(i=>{i.nextElementSibling.textContent=i.value?'':'This field is required';bad=bad||!i.value});if(!bad){let params=new URLSearchParams(new FormData(sell));params.delete('photos');params.set('photo_count',sell.elements.photos.files.length);location.href='/selling/review?'+params}}</script>""";return HTMLResponse(shell(f"Sell your {label}",body,path))
 if path=="/selling/confirmation" and q.get("id"):
  token,owner=_listing_state_owner(request);row=_owned_listing(owner,q["id"])
  if not row:
   response=HTMLResponse(shell("Listing unavailable","<div class='notice warn'><p>This listing does not belong to the current session.</p><a class=button href=/selling/find-car>Start a listing</a></div>",path),404);_set_auth_cookie(response,token);return response
  listing=_listing_dict(row)
  body=f"<div class='notice ok'><h2>Your local advert preview has been saved</h2><p>Offline reference {e(listing['id'])} · Pending local review</p></div><table><tr><th>Vehicle</th><td>{listing['year']} {e(listing['make'])}</td></tr><tr><th>Mileage</th><td>{listing['mileage']} miles</td></tr><tr><th>Price</th><td>£{listing['price']}</td></tr><tr><th>Vehicle photos</th><td>{listing['photo_count']}</td></tr><tr><th>Total</th><td>£0 offline preview</td></tr></table><a class=button href=/cars/used>Back to used cars</a>"
  response=HTMLResponse(shell("Listing confirmation",body,path));_set_auth_cookie(response,token);return response
 if path=="/selling/confirmation":return HTMLResponse(shell("Listing confirmation",f"<div class='notice ok'><h2>Your advert has been submitted</h2><p>Offline reference AT-754 · Pending review</p></div><table><tr><th>Vehicle</th><td>{e(q.get('year','2022'))} {e(q.get('make','Ford'))}</td></tr><tr><th>Mileage</th><td>{e(q.get('mileage','24100'))} miles</td></tr><tr><th>Price</th><td>£{e(q.get('price','14995'))}</td></tr><tr><th>Total</th><td>£0 offline preview</td></tr></table><a class=button href=/account/history>Manage listing</a>",path))
 if path=="/password-recovery":return HTMLResponse(shell("Reset your password","<form class=panel onsubmit='event.preventDefault();this.reportValidity()'><label>Reset email address<input type=email required><span class=error>Enter the address used for your account.</span></label><button>Continue</button></form><p>No reset message is sent offline.</p><a href=/secure/signin>Return to sign in</a>",path))
 if path=="/help":return HTMLResponse(shell("Help and support","<div class=cards><section class=card><h2>Used-car listings</h2><p>Search, filters, saved vehicles, alerts and dealers.</p><a href=/cars/used>Browse cars</a></section><section class=card><h2>Account access</h2><p>Sign-in, registration and recovery.</p><a href=/secure/signin>Account help</a></section><section class=card><h2>Failed actions</h2><p>Required fields and permission prompts explain corrections.</p><a href=/cars/sell-my-car>Listing help</a></section></div><p>No private account data is displayed.</p>",path))
 if path=="/external-link":
  label=q.get("label","External service")[:120]
  body=f"<div class='notice warn'><h2>{e(label)}</h2><p>This external destination is not opened by the offline clone. No request was sent.</p><a class=button href=/>Return to Autotrader</a></div>"
  return HTMLResponse(shell("External service unavailable offline",body,path))
 return None

def account_surface(path:str,request:Request):
 account=_account(request)
 if not account:
  return RedirectResponse("/secure/signin?next="+quote(path,safe=""),status_code=303)
 owner=str(account["subject_id"])
 if path in {"/account","/secure/my-auto-trader"}:
  body=f"""<div class='notice ok'><h2>Welcome back, {e(account['display_name'])}</h2><p>{e(account['email_normalized'])} · verified local account</p></div><div class=action-grid><a class=action-card href=/account/history><b>Your adverts</b><span>Review, edit, pause, renew or remove listings</span></a><a class=action-card href=/account/address><b>Delivery and pickup</b><span>Manage your local address and delivery preference</span></a><a class=action-card href=/cars/used><b>Saved cars and searches</b><span>Return to used-car records</span></a></div><form method=post action=/secure/logout><button id=account-signout class=secondary>Sign out</button></form>"""
  return HTMLResponse(shell("My Autotrader",body,path))
 if path=="/account/history":
  rows=_owned_listings(owner)
  cards_html="".join(f"""<article class=listing-row><div><p class=eyebrow>Advert {e(row['listing_id'])}</p><h2>{e(row['year'])} {e(row['make'])}</h2><p>Status: <b>{e(row['status'])}</b> · £{row['price']:,} · {row['mileage']:,} miles</p></div><div class=row-actions><a class=button href='/account/listings/{e(row['listing_id'])}'>Details</a><a class='button secondary' href='/selling/find-car?edit={e(row['listing_id'])}'>Edit</a><button class=secondary data-listing='{e(row['listing_id'])}' data-version='{row['version']}' data-action=pause>Pause</button><button class=secondary data-listing='{e(row['listing_id'])}' data-version='{row['version']}' data-action=renew>Renew</button><button class=danger data-listing='{e(row['listing_id'])}' data-version='{row['version']}' data-action=remove>Remove</button></div></article>""" for row in rows)
  body=(cards_html or "<div class='empty-state'><h2>No adverts yet</h2><a class=button href=/selling/find-car>Sell your car</a></div>")+"""<p id=history-status role=status></p><a href=/cars/used>Back to used cars</a><script>document.querySelectorAll('[data-action]').forEach(b=>b.onclick=async()=>{let r=await fetch('/api/listings/'+b.dataset.listing+'/actions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:b.dataset.action,expected_version:Number(b.dataset.version)})}),x=await r.json();history-status.textContent=r.ok?'Advert updated to '+x.listing.status+'.':x.error;if(r.ok)setTimeout(()=>location.reload(),250)})</script>"""
  return HTMLResponse(shell("Your adverts and saved cars",body,path))
 if path=="/account/address":
  with SITE_BACKEND.lifecycle.connection() as connection:
   row=connection.execute("SELECT * FROM autotrader_addresses WHERE owner_subject_id=?",(owner,)).fetchone()
  value=lambda key:e(row[key] if row else "")
  selected=lambda option:" selected" if row and row["delivery_option"]==option else ""
  body=f"""<form class='panel grid' id=address-form><label>Address<input name=address value='{value("address")}' required></label><label>City<input name=city value='{value("city")}' required></label><label>Postcode<input name=postcode value='{value("postcode")}' required></label><label>Delivery option<select name=delivery_option><option value=dealer-pickup{selected("dealer-pickup")}>Dealer pickup</option><option value=home-delivery{selected("home-delivery")}>Home delivery</option></select></label><button>Save address</button></form><p id=address-status role=status></p><script>const addressForm=document.getElementById('address-form'),addressStatus=document.getElementById('address-status');addressForm.addEventListener('submit',async event=>{{event.preventDefault();let response=await fetch('/api/account/address',{{method:'PUT',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(Object.fromEntries(new FormData(addressForm)))}}),result=await response.json();addressStatus.textContent=response.ok?'Address and delivery option saved locally.':result.error}})</script>"""
  return HTMLResponse(shell("Delivery and pickup",body,path))
 if path.startswith("/account/listings/"):
  listing_id=path.rsplit("/",1)[-1];row=_owned_listing(owner,listing_id)
  if not row:return HTMLResponse(shell("Advert not found","<div class='empty-state'><p>This advert is unavailable.</p><a class=button href=/account/history>Back to your adverts</a></div>",path),404)
  listing=_listing_dict(row)
  body=f"""<div class=vehicle-summary><div class=photo>Vehicle photos · {listing['photo_count']}</div><div><p class=eyebrow>Advert {e(listing_id)}</p><h2>{e(listing['year'])} {e(listing['make'])}</h2><p class=price>£{listing['price']:,}</p><p>{listing['mileage']:,} miles</p><p>Status: <b>{e(listing['status'])}</b></p><p>{e(listing['description'])}</p></div></div><a class=button href=/account/history>Back to your adverts</a>"""
  return HTMLResponse(shell("Advert "+listing_id,body,path))
 return HTMLResponse(shell("Account page unavailable","<a class=button href=/secure/my-auto-trader>Back to your account</a>",path),404)

ROUTING_SCRIPT="""<script data-offline-routing>(function(){function go(e){var target=e.target.closest&&e.target.closest('a[href],button');if(!target)return;var raw=target.getAttribute('href')||'';var label=(target.textContent||'').replace(/\\s+/g,' ').trim();if(/sign in another way/i.test(label)){e.preventDefault();e.stopImmediatePropagation();window.location.assign('/secure/signin?mode=local');return}if(!raw&&/\\bsign in\\b/i.test(label)){e.preventDefault();e.stopImmediatePropagation();window.location.assign('/secure/signin');return}if(!raw)return;var url;try{url=new URL(raw,location.origin)}catch(x){return}if(url.hostname.indexOf('autotrader.co.uk')>=0){e.preventDefault();e.stopImmediatePropagation();window.location.assign(url.pathname+url.search+url.hash);return}if(url.origin!==location.origin){e.preventDefault();e.stopImmediatePropagation();window.location.assign('/external-link?label='+encodeURIComponent(label||url.hostname));}}document.addEventListener('click',go,true);setTimeout(function(){document.querySelectorAll('button[data-testid="account-sign-in"],button[data-gui="account-sign-in"]').forEach(function(b){b.addEventListener('click',function(e){e.preventDefault();e.stopImmediatePropagation();window.location.assign(b.dataset.offlineAccountDestination||'/secure/signin')},true)})},0)})();</script>"""
ACCOUNT_SYNC_SCRIPT=r"""<script data-offline-account-sync>(function(){
function setAccountLabel(element,label){
 var direct=Array.from(element.childNodes).filter(function(node){return node.nodeType===3&&String(node.nodeValue||'').trim()});
 if(direct.length){direct[direct.length-1].nodeValue=label;return}
 var leaf=Array.from(element.querySelectorAll('span,p')).find(function(node){return !node.children.length&&/^(sign in|account)$/i.test((node.textContent||'').trim())});
 if(leaf)leaf.textContent=label;
}
async function syncAccount(){
 var signed=false,state={account:null};
 try{var response=await fetch('/api/auth/session');state=await response.json();signed=!!state.authenticated}catch(error){}
 var destination=signed?'/secure/my-auto-trader':'/secure/signin';
 var visibleLabel=signed?'Account':'Sign in';
 var accountName=signed&&state.account&&state.account.name?state.account.name:'your';
 var selector='button[data-testid="account-sign-in"],button[data-gui="account-sign-in"],header a[href*="/secure/signin"],header a[href*="/secure/my-auto-trader"],nav a[href*="/secure/signin"],nav a[href*="/secure/my-auto-trader"],[role="navigation"] a[href*="/secure/signin"],[role="navigation"] a[href*="/secure/my-auto-trader"],a[data-offline-global-account]';
 document.querySelectorAll(selector).forEach(function(element){
  if(element.closest('main form')||element.dataset.offlineAuthAction)return;
  element.dataset.offlineGlobalAccount='';
  element.dataset.offlineAccountDestination=destination;
  element.dataset.offlineAccountState=signed?'authenticated':'anonymous';
  if(element.tagName==='A')element.setAttribute('href',destination);
  setAccountLabel(element,visibleLabel);
  element.setAttribute('aria-label',signed?'Open your Autotrader Account — '+accountName:'Sign in to your Autotrader Account');
  if(!element.dataset.offlineAccountBound){
   element.dataset.offlineAccountBound='1';
   element.addEventListener('click',function(event){event.preventDefault();event.stopImmediatePropagation();location.assign(element.dataset.offlineAccountDestination||'/secure/signin')},true);
  }
 });
}
syncAccount();window.addEventListener('pageshow',syncAccount);window.addEventListener('offline-auth-changed',syncAccount);
})();</script>"""
VIEWPORT_GUARD_STYLE="""<style data-offline-viewport-guard>html,body{max-width:100%;overflow-x:hidden}</style>"""
OFFLINE_INTERACTION_SCRIPT=r'''<script data-offline-interactions>(function(){
function text(el){return (el&&el.textContent||'').replace(/\s+/g,' ').trim()}
function mark(el){var key=el.getAttribute('data-testid')||el.id||text(el).slice(0,80)||'button';try{localStorage.setItem('autotrader.interaction.'+key,'1')}catch(e){}el.setAttribute('data-offline-activated','true');}
function field(form,pattern){return Array.from(form.querySelectorAll('input,select')).find(function(el){var text=[el.name,el.id,el.getAttribute('aria-label'),el.getAttribute('placeholder'),el.closest('label')&&el.closest('label').textContent].filter(Boolean).join(' ');return pattern.test(text)})}
function category(path){var match=path.match(/^\/(vans|bikes|motorhomes|caravans|trucks|farm|plant)(?:\/|$)/);return match?match[1]:'cars'}
function usedRoute(path){var routes={cars:'/cars/used',vans:'/vans/used-vans',bikes:'/bikes/used-bikes',motorhomes:'/motorhomes/used-motorhomes',caravans:'/caravans/used-caravans',trucks:'/trucks/used-trucks',farm:'/farm/used-farm-machinery',plant:'/plant/used-plant-machinery'};if(/\/(?:used-|new-)|^\/cars\/(?:used|new)$/.test(path))return path;return routes[category(path)]||'/cars/used'}
function tabRoute(path,label){var kind=category(path),homes={cars:'/cars',vans:'/vans',bikes:'/bikes',motorhomes:'/motorhomes',caravans:'/caravans',trucks:'/trucks',farm:'/farm',plant:'/plant'},sell={cars:'/cars/sell-my-car',vans:'/vans/sell',bikes:'/bikes/sell',motorhomes:'/motorhomes/sell',caravans:'/caravans/sell',trucks:'/trucks/sell',farm:'/farm/sell',plant:'/plant/sell'},lease={cars:'/cars/leasing',vans:'/vans/leasing'};if(/^buy$/i.test(label))return homes[kind];if(/^sell$/i.test(label))return sell[kind];if(/^lease$/i.test(label))return lease[kind];return null}
function goSearch(form,path){form.dataset.offlineInteractionBound='1';var postcode=field(form,/postcode/i),make=field(form,/make/i),model=field(form,/model/i),params=new URLSearchParams();[[postcode,'postcode'],[make,'make'],[model,'model']].forEach(function(pair){if(pair[0]&&String(pair[0].value||'').trim()&&!/^any$/i.test(pair[0].value))params.set(pair[1],pair[0].value)});location.assign(usedRoute(path)+'?'+params.toString())}
function goSell(form,path){form.dataset.offlineInteractionBound='1';var registration=field(form,/registration|vrm/i),mileage=field(form,/mileage/i),params=new URLSearchParams({category:category(path)});if(registration&&registration.value)params.set('registration',registration.value);if(mileage&&mileage.value)params.set('mileage',mileage.value);location.assign('/selling/find-car?'+params.toString())}
function statusNear(element,message){var host=element.closest('form,section,article,footer,main')||element.parentElement||document.body;var status=host.querySelector('[data-offline-status]');if(!status){status=document.createElement('p');status.dataset.offlineStatus='';status.setAttribute('role','status');status.setAttribute('aria-live','polite');status.style.cssText='margin:12px 0;padding:10px;border:1px solid #b6b6c2;border-radius:6px;background:#fff;color:#24242f;font:14px/1.4 Arial,sans-serif';host.appendChild(status)}status.textContent=message;return status}
function openLocalPanel(kind,title,message){var old=document.querySelector('[data-offline-panel]');if(old)old.remove();var wrap=document.createElement('div');wrap.dataset.offlinePanel=kind;wrap.setAttribute('role','dialog');wrap.setAttribute('aria-modal','true');wrap.setAttribute('aria-labelledby','offline-panel-title');wrap.style.cssText='position:fixed;inset:0;z-index:2147483647;background:rgba(7,11,52,.55);display:grid;place-items:center;padding:20px';var box=document.createElement('section');box.style.cssText='width:min(520px,100%);max-height:85vh;overflow:auto;background:#fff;color:#24242f;border-radius:10px;padding:24px;box-shadow:0 12px 50px rgba(0,0,0,.3);font:16px/1.45 Arial,sans-serif';box.innerHTML='<h2 id="offline-panel-title" style="margin-top:0"></h2><p data-offline-panel-message></p><button type="button" data-offline-panel-confirm style="background:#0019ff;color:#fff;border:0;border-radius:999px;padding:11px 18px;font-weight:700;cursor:pointer">Done</button>';box.querySelector('h2').textContent=title;box.querySelector('[data-offline-panel-message]').textContent=message;wrap.appendChild(box);document.body.appendChild(wrap);var done=box.querySelector('[data-offline-panel-confirm]');done.addEventListener('click',function(){if(kind==='cookies'){try{localStorage.setItem('autotrader.cookie-preferences','local-only')}catch(e){}}wrap.remove()});wrap.addEventListener('click',function(ev){if(ev.target===wrap)wrap.remove()});done.focus();return wrap}
function openSearchOptions(trigger,form,path){
 var old=document.querySelector('[data-offline-panel]');if(old)old.remove();
 var kind=category(path),bodyOptions={cars:['Hatchback','SUV','Saloon','Estate','Coupe'],vans:['Panel Van','Combi Van','Camper Van','Electric Van'],bikes:['Adventure','Naked','Scooter','Sports'],motorhomes:['Coachbuilt','Campervan','A-Class'],caravans:['Touring','Static'],trucks:['Rigid','Tractor unit'],farm:['Tractor','Harvester'],plant:['Excavator','Loader']}[kind]||[];
 var wrap=document.createElement('div');wrap.dataset.offlinePanel='search-options';wrap.setAttribute('role','dialog');wrap.setAttribute('aria-modal','true');wrap.setAttribute('aria-labelledby','offline-search-options-title');wrap.style.cssText='position:fixed;inset:0;z-index:2147483647;background:rgba(7,11,52,.58);display:grid;place-items:center;padding:16px';
 var box=document.createElement('section');box.setAttribute('data-offline-search-options','');box.style.cssText='box-sizing:border-box;width:min(680px,100%);max-height:calc(100vh - 32px);overflow:auto;background:#fff;color:#24242f;border-radius:12px;padding:24px;box-shadow:0 16px 56px rgba(0,0,0,.32);font:16px/1.45 Arial,sans-serif';
 box.innerHTML='<style>[data-offline-search-options] *{box-sizing:border-box}[data-offline-search-options] .offline-options-head{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:20px}[data-offline-search-options] h2{margin:0;font-size:26px;line-height:1.2}[data-offline-search-options] .offline-options-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}[data-offline-search-options] label{display:flex;flex-direction:column;gap:7px;font-weight:700}[data-offline-search-options] select{width:100%;min-height:48px;padding:11px 40px 11px 12px;border:1px solid #7d7d87;border-radius:4px;background:#fff;color:#24242f;font:inherit}[data-offline-search-options] .offline-options-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:24px}[data-offline-search-options] button{min-height:44px;padding:10px 20px;border-radius:999px;border:1px solid #0019ff;font:inherit;font-weight:700;cursor:pointer}[data-offline-search-options] button:focus-visible,[data-offline-search-options] select:focus{outline:3px solid rgba(0,25,255,.25);outline-offset:2px}[data-offline-search-options] [data-options-apply]{background:#0019ff;color:#fff}[data-offline-search-options] [data-options-close]{background:#fff;color:#0019ff}@media(max-width:560px){[data-offline-search-options]{padding:20px!important;border-radius:10px!important}[data-offline-search-options] .offline-options-grid{grid-template-columns:1fr}[data-offline-search-options] .offline-options-actions{flex-direction:column-reverse}[data-offline-search-options] .offline-options-actions button{width:100%}}</style><div class="offline-options-head"><h2 id="offline-search-options-title">More search options</h2><button type="button" data-options-close aria-label="Close more search options">Close</button></div><div class="offline-options-grid"><label>Price up to<select name="price"><option value="">Any price</option><option value="5000">£5,000</option><option value="10000">£10,000</option><option value="15000">£15,000</option><option value="25000">£25,000</option><option value="40000">£40,000</option></select></label><label>Year from<select name="year"><option value="">Any year</option><option>2024</option><option>2022</option><option>2020</option><option>2018</option></select></label><label>Mileage up to<select name="mileage"><option value="">Any mileage</option><option value="10000">10,000 miles</option><option value="30000">30,000 miles</option><option value="60000">60,000 miles</option><option value="100000">100,000 miles</option></select></label><label>Body style<select name="body"><option value="">Any body style</option></select></label></div><div class="offline-options-actions"><button type="button" data-options-cancel>Cancel</button><button type="button" data-options-apply>Apply filters</button></div>';
 var bodySelect=box.querySelector('select[name="body"]');bodyOptions.forEach(function(option){bodySelect.add(new Option(option,option))});wrap.appendChild(box);document.body.appendChild(wrap);var previousOverflow=document.body.style.overflow;document.body.style.overflow='hidden';trigger.setAttribute('aria-expanded','true');trigger.setAttribute('aria-controls','offline-search-options-title');
 function close(){document.body.style.overflow=previousOverflow;wrap.remove();trigger.setAttribute('aria-expanded','false');trigger.focus()}
 box.querySelector('[data-options-close]').onclick=close;box.querySelector('[data-options-cancel]').onclick=close;wrap.addEventListener('click',function(event){if(event.target===wrap)close()});wrap.addEventListener('keydown',function(event){if(event.key==='Escape')close()});
 box.querySelector('[data-options-apply]').onclick=function(){var params=new URLSearchParams(),postcode=field(form,/postcode/i),make=field(form,/make/i),model=field(form,/model/i);[[postcode,'postcode'],[make,'make'],[model,'model']].forEach(function(pair){if(pair[0]&&pair[0].value&&!pair[0].disabled&&!/^any$/i.test(pair[0].value))params.set(pair[1],pair[0].value)});box.querySelectorAll('select').forEach(function(select){if(select.value)params.set(select.name,select.value)});location.assign(usedRoute(path)+'?'+params.toString())};box.querySelector('select').focus();
}
function bindDependentSelects(){var models={Ford:['Fiesta','Focus','Kuga','E-Transit','E-Transit Custom','Transit Courier'],BMW:['1 Series','3 Series','X3'],Volkswagen:['Golf','Passat','Tiguan','ID. Buzz Cargo','e-Transporter'],'Mercedes-Benz':['eSprinter','eVito'],Vauxhall:['Corsa','Vivaro Electric','Combo Electric'],Peugeot:['e-Partner','e-Expert'],Kia:['PV5'],MAXUS:['eDeliver 5','eTERRON 9']};document.querySelectorAll('form').forEach(function(form){var make=field(form,/\bmake\b/i),model=field(form,/\bmodel\b/i);if(!make||!model||make.dataset.offlineDependentBound)return;make.dataset.offlineDependentBound='1';make.addEventListener('change',function(){var values=models[make.value]||[];model.innerHTML='<option value="">Any</option>';values.forEach(function(value){model.add(new Option(value,value))});model.disabled=!make.value;var root=model.closest('[data-disabled]');if(root)root.setAttribute('data-disabled',String(!make.value));model.dispatchEvent(new Event('offline-options-changed',{bubbles:true}))})})}
function accordionTarget(el){var id=el.getAttribute('aria-controls');if(id){var controlled=document.getElementById(id);if(controlled)return controlled}var row=el.closest('.atds-accordion-row,[data-accordion-row],li,section');return row&&row.querySelector('.atds-accordion-row__content,[data-accordion-content]')||null}
function toggleAccordion(el){var target=accordionTarget(el),expanded=el.getAttribute('aria-expanded')==='true';if(!target){openLocalPanel('unavailable','Content unavailable offline','This saved page does not contain the expanded source content.');el.setAttribute('aria-expanded','false');return}expanded=!expanded;el.setAttribute('aria-expanded',String(expanded));target.setAttribute('aria-hidden',String(!expanded));target.hidden=!expanded;target.style.display=expanded?'block':'none';mark(el)}
function carouselParts(el){var root=el.closest('[class*="carouselLiteWrapper"],[data-carousel],section,article')||document;var win=root.querySelector('[class*="carouselSlideWindow"],[data-carousel-window]');var slides=Array.from(root.querySelectorAll('[class*="carouselSlide"],[data-carousel-slide]')).filter(function(slide){return !String(slide.className).includes('carouselSlideWindow')});return {root:root,win:win,slides:slides}}
function activateCarousel(el){var parts=carouselParts(el),label=[el.getAttribute('aria-label'),el.id,text(el)].filter(Boolean).join(' '),match=label.match(/(?:slide|page)[^0-9]*(\d+)/i),controls=Array.from(parts.root.querySelectorAll('button,[role="button"]')).filter(function(button){return /(?:slide|page)[^0-9]*\d+/i.test([button.getAttribute('aria-label'),button.id,text(button)].filter(Boolean).join(' '))}),index=match?Math.max(0,Number(match[1])-1):Math.max(0,controls.indexOf(el));if(!parts.slides.length){statusNear(el,'Additional carousel content is unavailable in this saved page.');return}index=Math.min(index,parts.slides.length-1);if(parts.win){var offset=parts.slides[index].offsetLeft;parts.win.style.transition='transform 240ms ease';parts.win.style.transform='translateX(-'+offset+'px)'}parts.slides.forEach(function(slide,i){slide.setAttribute('aria-hidden',String(i!==index));slide.dataset.offlineActiveSlide=String(i===index)});controls.forEach(function(control){var controlLabel=[control.getAttribute('aria-label'),control.id,text(control)].filter(Boolean).join(' '),controlMatch=controlLabel.match(/(?:slide|page)[^0-9]*(\d+)/i),active=controlMatch?Number(controlMatch[1])-1===index:control===el;control.setAttribute('aria-current',active?'true':'false');control.setAttribute('aria-pressed',String(active))});parts.root.dataset.offlineCarouselIndex=String(index);mark(el)}
function revealCollection(el){var host=el.closest('section,article,div,ul')||el.parentElement,hidden=host?Array.from(host.querySelectorAll('[hidden],[aria-hidden="true"]')):[];hidden=hidden.filter(function(item){return !item.closest('[data-offline-panel]')&&!item.matches('.atds-accordion-row__content')});if(!hidden.length){statusNear(el,'All available offline items are already shown.');el.setAttribute('aria-expanded','true');mark(el);return}hidden.forEach(function(item){item.hidden=false;item.setAttribute('aria-hidden','false');item.style.removeProperty('display')});el.setAttribute('aria-expanded','true');el.dataset.offlineRevealCount=String(hidden.length);if(/^show /i.test(text(el)))el.dataset.offlineOriginalLabel=text(el);mark(el)}
function submitLocalOnlyForm(form,message){var missing=Array.from(form.querySelectorAll('[required]')).filter(function(input){return input.type==='checkbox'?!input.checked:!String(input.value||'').trim()});missing.forEach(function(input){input.setAttribute('aria-invalid','true')});if(missing.length){statusNear(form,'Please complete the required fields before continuing.');missing[0].focus();form.dataset.offlineSubmitted='validation';return false}form.dataset.offlineSubmitted='true';statusNear(form,message);return true}
function nameIconButton(button){if(text(button)||button.getAttribute('aria-label')||button.getAttribute('aria-labelledby'))return;var svgTitle=button.querySelector('svg title'),image=button.querySelector('img[alt]'),title=button.getAttribute('title'),fieldSet=button.closest('fieldset'),label=button.closest('label'),context=title||(svgTitle&&text(svgTitle))||(image&&image.alt)||(label&&text(label))||(fieldSet&&text(fieldSet.querySelector('legend')));if(!context&&button.closest('form'))context='Open form options';if(!context)context='Open menu';button.setAttribute('aria-label',context.replace(/\s+/g,' ').trim().slice(0,120));button.dataset.offlineAccessibleName='derived'}
function initialise(){document.querySelectorAll('button,[role="button"]').forEach(nameIconButton);document.querySelectorAll('.atds-accordion-row__button').forEach(function(button){if(!button.hasAttribute('aria-expanded'))button.setAttribute('aria-expanded','false')});bindDependentSelects()}
document.addEventListener('click',function(ev){var el=ev.target.closest&&ev.target.closest('button,[role="button"],a');if(!el)return;if(el.closest('[data-offline-panel]'))return;var label=text(el),form=el.closest('form'),tab=String(el.className||'').indexOf('__tabButton')>=0?tabRoute(location.pathname,label):null;if(el.matches('.atds-accordion-row__button,[data-accordion-button]')||el.hasAttribute('aria-controls')&&/accordion/i.test(String(el.className))){ev.preventDefault();ev.stopImmediatePropagation();toggleAccordion(el);return}if(/go to slide|^slide[- ]?\d+$|carousel/i.test([label,el.getAttribute('aria-label'),el.id,String(el.className)].filter(Boolean).join(' '))&&(el.closest('[class*="carouselLiteWrapper"],[data-carousel]')||String(el.className).indexOf('carouselPip')>=0)){ev.preventDefault();ev.stopImmediatePropagation();activateCarousel(el);return}if(/^(show all|show more|view all|load more)/i.test(label)){ev.preventDefault();ev.stopImmediatePropagation();revealCollection(el);return}if(/back to top/i.test(label)||el.getAttribute('href')==='#top'){ev.preventDefault();ev.stopImmediatePropagation();window.scrollTo({top:0,left:0,behavior:'auto'});mark(el);return}if(/manage cookies|cookie settings|cookie preferences/i.test(label)){ev.preventDefault();ev.stopImmediatePropagation();openLocalPanel('cookies','Cookie preferences','Preferences are stored only in this browser. No preference was sent to Autotrader.');mark(el);return}if(/send feedback|give feedback/i.test(label)){ev.preventDefault();ev.stopImmediatePropagation();openLocalPanel('feedback','Feedback','This offline review cannot send feedback. No feedback was sent.');mark(el);return}if(/continue with (google|apple|facebook)|identity provider/i.test(label)){ev.preventDefault();ev.stopImmediatePropagation();openLocalPanel('identity-provider','Identity provider unavailable offline','No credentials were requested or sent. Use Sign in another way for the local identity simulation.');mark(el);return}if(tab){ev.preventDefault();ev.stopImmediatePropagation();location.assign(tab);return}if(form&&/^search\b/i.test(label)){ev.preventDefault();ev.stopImmediatePropagation();goSearch(form,location.pathname);return}if(form&&/sell my|start an advert|get my instant valuation/i.test(label)){ev.preventDefault();ev.stopImmediatePropagation();goSell(form,location.pathname);return}if(/more options/i.test(label)){ev.preventDefault();ev.stopImmediatePropagation();el.dataset.offlineInteractionBound='1';mark(el);if(form)form.setAttribute('data-offline-more-options','expanded');openSearchOptions(el,form||document.querySelector('form'),location.pathname);return}if(el.type==='submit')return;if(el.tagName==='BUTTON'||el.getAttribute('role')==='button'){ev.preventDefault();mark(el);statusNear(el,'This control was activated locally.')}} ,true);
document.addEventListener('submit',function(ev){var form=ev.target;if(form.dataset.offlineInteractionBound)return;var action=form.getAttribute('action')||'',shape=text(form)+' '+action,path=location.pathname;if(/sell my|start an advert|get my instant valuation/i.test(shape)){ev.preventDefault();goSell(form,path);return}if(/search|postcode|make|model|vehicle/i.test(shape)){ev.preventDefault();goSearch(form,path);return}if(/newsletter|email.*updates|sign up|subscribe/i.test(shape)){ev.preventDefault();submitLocalOnlyForm(form,'Your preference was saved locally. No email was sent.');return}if(/^https?:/i.test(action)||!action){ev.preventDefault();submitLocalOnlyForm(form,'This form was completed locally. No information was sent.')}} ,true);
document.querySelectorAll('a[href^="https://www.autotrader.co.uk"],a[href^="http://www.autotrader.co.uk"],a[href^="//www.autotrader.co.uk"]').forEach(function(a){try{var u=new URL(a.href);a.href=u.pathname+u.search+u.hash}catch(e){}});
initialise();
})();</script>'''
LOCAL_SAVED_ACTION_SCRIPT=r'''<script data-offline-saved-actions>(function(){
document.addEventListener('click',async function(event){
 var button=event.target.closest&&event.target.closest('[data-save],[data-compare],[data-alert]');
 if(!button)return;
 event.preventDefault();
 var kind=button.hasAttribute('data-save')?'car':button.hasAttribute('data-compare')?'compare':'alert';
 var itemId=button.getAttribute(kind==='car'?'data-save':kind==='compare'?'data-compare':'data-alert');
 var response=await fetch('/api/saved',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:kind,item_id:itemId})});
 if(response.ok){await response.json();button.textContent=kind==='car'?'Saved':kind==='compare'?'Added to compare':'Alert created';}
},true);
})();</script>'''
def _localize_snapshot_links(source:str) -> str:
 # SingleFile rewrites same-origin href/action values to an about:blank hash.
 # Restore only navigational attributes; embedded SVG/image namespaces remain byte-for-byte intact.
 return re.sub(
  r'''(\b(?:href|action)\s*=\s*(?:"|'|))about:blank#offline-(?:www\.)?autotrader\.co\.uk(?=/|"|'|\s|>)''',
  lambda match:match.group(1),
  source,
  flags=re.I,
 )
def render(path):
 p=EXACT_ROUTES.get(path) or SNAPSHOT_ROUTES.get(path) or INTERNAL_ROUTE_MAP.get(path) or _page(*ROUTES.get(path,())) or _snapshot(path) or _page("Autotrader UK - New")
 if not p:return HTMLResponse(shell("Unavailable","<p>Snapshot unavailable.</p>",path),503)
 source=p.read_text(encoding="utf-8",errors="ignore")
 source=_localize_snapshot_links(source)
 source=re.sub(r"<html\b",lambda match:f'<html data-offline-source-route="{e(path)}"',source,count=1,flags=re.I)
 source=source.replace("default-src 'none';", "default-src 'none'; connect-src 'self';", 1)
 # Rewrite captured auth destinations before the browser executes embedded site code.
 source=re.sub(r"https?://(?:www\.)?autotrader\.co\.uk/secure/signin(?:\?[^\"'<> ]*)?", "/secure/signin", source, flags=re.I)
 source=source.replace("//www.autotrader.co.uk/secure/signin", "/secure/signin")
 extra=VIEWPORT_GUARD_STYLE+ACCOUNT_SYNC_SCRIPT+OFFLINE_INTERACTION_SCRIPT
 if re.search(r"</body>\s*$",source,re.I): source=re.sub(r"</body>",ROUTING_SCRIPT+extra+"</body>",source,count=1,flags=re.I)
 else: source+=ROUTING_SCRIPT+extra
 return HTMLResponse(source)

SOURCE_SHELL_STYLE=r'''<style data-offline-source-shell>
main[data-offline-dynamic]{max-width:1180px;margin:0 auto;padding:28px 24px 80px;color:#24242f;background:#f7f7f8;font:15px/1.5 Arial,Helvetica,sans-serif}
main[data-offline-dynamic] *{box-sizing:border-box}main[data-offline-dynamic] h1{font-size:38px;line-height:1.1;margin:8px 0 24px;color:#070b34}
main[data-offline-dynamic] .panel,main[data-offline-dynamic] .card,main[data-offline-dynamic] .gallery,main[data-offline-dynamic] .notice{background:#fff;border:1px solid #dedee4;border-radius:10px;padding:22px;margin:18px 0;box-shadow:0 2px 8px rgba(7,11,52,.06)}
main[data-offline-dynamic] .grid,main[data-offline-dynamic] .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}main[data-offline-dynamic] .cards{align-items:stretch}main[data-offline-dynamic] .result-list{grid-template-columns:repeat(3,minmax(0,1fr));gap:20px}
main[data-offline-dynamic] .card{margin:0;padding:0;overflow:hidden}main[data-offline-dynamic] .card-body{padding:18px}main[data-offline-dynamic] .card h2{font-size:18px;margin:0 0 10px}
main[data-offline-dynamic] .vehicle-thumb{display:block;width:100%;height:190px;padding:18px;background:#f4f4f5;object-fit:contain;position:relative;overflow:hidden}
main[data-offline-dynamic] label{display:flex;flex-direction:column;gap:6px;font-weight:700}main[data-offline-dynamic] input,main[data-offline-dynamic] select,main[data-offline-dynamic] textarea{width:100%;padding:12px;border:1px solid #858593;border-radius:5px;background:#fff;color:#24242f;font:inherit}
main[data-offline-dynamic] button,main[data-offline-dynamic] .button{display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:11px 18px;border:1px solid #0019ff;border-radius:999px;background:#0019ff;color:#fff;font-weight:750;text-decoration:none;cursor:pointer;margin:3px}main[data-offline-dynamic] .secondary{background:#fff;color:#0019ff}
main[data-offline-dynamic] .price{font-size:25px;font-weight:800}main[data-offline-dynamic] .gallery{display:grid;grid-template-columns:1.2fr 1fr;gap:26px}main[data-offline-dynamic] .photo{min-height:320px;border-radius:8px;background:linear-gradient(145deg,#d9e9f5,#edf0f1);display:grid;place-items:center;font-weight:700;overflow:hidden}main[data-offline-dynamic] .photo picture,main[data-offline-dynamic] .photo img{display:block;width:100%;height:100%;min-height:320px;object-fit:contain}
@media(max-width:980px){main[data-offline-dynamic] .result-list{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:760px){main[data-offline-dynamic]{padding:20px 16px 60px}main[data-offline-dynamic] h1{font-size:30px}main[data-offline-dynamic] .gallery{grid-template-columns:1fr}main[data-offline-dynamic] .cards,main[data-offline-dynamic] .result-list{grid-template-columns:1fr}}
</style>'''

def source_shell(title:str,body:str,path:str,base_route:str="/cars/used") -> str:
 base=EXACT_ROUTES.get(base_route) or EXACT_ROUTES.get("/cars/used") or _page("Used Cars For Sale")
 if not base:return shell(title,body,path)
 source=base.read_text(encoding="utf-8",errors="ignore")
 source=_localize_snapshot_links(source)
 source=re.sub(r"<html\b",lambda _:f'<html data-offline-source-route="{e(base_route)}" data-offline-derived-state="true"',source,count=1,flags=re.I)
 replacement=f"<main data-offline-dynamic><h1>{e(title)}</h1>{body}</main>"
 source,count=re.subn(r"<main\b[^>]*>.*?</main>",lambda _:replacement,source,count=1,flags=re.I|re.S)
 if not count:return shell(title,body,path)
 source=re.sub(r"<title>.*?</title>",lambda _:f"<title>{e(title)} | Autotrader UK</title>",source,count=1,flags=re.I|re.S)
 source=source.replace("default-src 'none';", "default-src 'none'; connect-src 'self';", 1)
 source=re.sub(r"</head>",lambda _:SOURCE_SHELL_STYLE+"</head>",source,count=1,flags=re.I)
 extra=ROUTING_SCRIPT+VIEWPORT_GUARD_STYLE+ACCOUNT_SYNC_SCRIPT+OFFLINE_INTERACTION_SCRIPT+LOCAL_SAVED_ACTION_SCRIPT
 source,count=re.subn(r"</body>",lambda _:extra+"</body>",source,count=1,flags=re.I)
 if not count:source+=extra
 return source
@app.get("/healthz")
async def healthz():return {"ok":True,"site_id":"autotrader"}
@app.get("/__websitebench/health")
async def websitebench_health():return {"status":"ok"}
@app.get("/snapshots",response_class=HTMLResponse)
async def snapshots():return HTMLResponse(shell("Captured AutoTrader pages",f"<p>{len(AUTO_SNAPSHOTS)} supplied pages</p><ul>{''.join(f'<li><a href=/snapshot/{_slug(p.stem)}>{e(p.stem)}</a></li>' for p in AUTO_SNAPSHOTS)}</ul>","/snapshots"))
@app.get("/api/search")
async def search(request:Request):return JSONResponse({"query":dict(request.query_params),"status":"offline","results":CARS})

@app.get("/api/saved")
async def get_saved(request:Request):
 token,rows=_saved_rows(request)
 response=JSONResponse({"items":[{"kind":row["item_kind"],"item_id":row["item_id"]} for row in rows],"offline":True})
 _set_auth_cookie(response,token)
 return response

@app.post("/api/saved")
async def save_item(request:Request):
 data=await request.json();kind=str(data.get("kind",""));item_id=str(data.get("item_id","")).strip()
 if kind not in {"car","compare","alert"} or not item_id or len(item_id)>120:return JSONResponse({"error":"Invalid saved item."},status_code=400)
 if kind in {"car","compare"} and not any(car["id"]==item_id for car in CARS):return JSONResponse({"error":"Vehicle not found."},status_code=404)
 token,owner=_state_owner(request)
 with SITE_BACKEND.lifecycle.connection(transaction=True) as connection:
  connection.execute("INSERT OR IGNORE INTO autotrader_saved_items(owner_key,item_kind,item_id,created_at) VALUES(?,?,?,?)",(owner,kind,item_id,int(time.time())))
 response=JSONResponse({"kind":kind,"item_id":item_id,"saved":True,"offline":True},status_code=201)
 _set_auth_cookie(response,token)
 return response

@app.get("/api/contact-requests")
async def get_contact_requests(request:Request):
 owner=_owner_subject(request)
 if not owner:return JSONResponse({"error":"Sign in is required."},status_code=401)
 with SITE_BACKEND.lifecycle.connection() as connection:
  rows=connection.execute("SELECT request_id,car_id,request_type,message,status FROM autotrader_contact_requests WHERE owner_subject_id=? ORDER BY created_at DESC,request_id DESC",(owner,)).fetchall()
 return JSONResponse({"requests":[dict(row) for row in rows],"offline":True})

@app.post("/api/contact-requests")
async def create_contact_request(request:Request):
 owner=_owner_subject(request)
 if not owner:return JSONResponse({"error":"Sign in is required."},status_code=401)
 data=await request.json();car_id=str(data.get("car_id","")).strip();request_type=str(data.get("request_type","")).strip();message=str(data.get("message","")).strip()
 if not any(car["id"]==car_id for car in CARS):return JSONResponse({"error":"Vehicle not found."},status_code=404)
 if request_type not in {"information","test-drive"} or not message:return JSONResponse({"error":"Choose a request and enter a message."},status_code=400)
 now=int(time.time())
 with SITE_BACKEND.lifecycle.connection(transaction=True) as connection:
  row=connection.execute("SELECT MAX(CAST(SUBSTR(request_id,4) AS INTEGER)) AS n FROM autotrader_contact_requests").fetchone();request_id=f"CR-{int(row['n'] or 0)+1}"
  connection.execute("INSERT INTO autotrader_contact_requests(request_id,owner_subject_id,car_id,request_type,message,status,created_at) VALUES(?,?,?,?,?,?,?)",(request_id,owner,car_id,request_type,message[:2000],"saved-locally",now))
 return JSONResponse({"request":{"id":request_id,"car_id":car_id,"request_type":request_type,"message":message[:2000],"status":"saved-locally"},"offline":True},status_code=201)

@app.post("/api/listings/preview")
async def preview(request:Request):
 data=await request.json();missing=[k for k in ("make","year","mileage","price") if not str(data.get(k,"")).strip()];return JSONResponse({"status":"validation" if missing else "preview","missing":missing,"submission_enabled":not missing,"offline":True})
@app.post("/api/auth/register")
async def register(request:Request):
 data=await request.json();email=str(data.get("email","")).strip().lower();password=str(data.get("password",""));name=str(data.get("name","Local driver")).strip() or "Local driver"
 if not email or "@" not in email or len(password)<8:return JSONResponse({"ok":False,"error":"Enter a valid email and a password of at least 8 characters."},status_code=400)
 try:
  session_token,_=_auth_session(request)
  result=AUTH_STORE.start_registration(session_token,email=email,display_name=name,password=password)
  response=JSONResponse({"ok":True,"state":"challenge","mail_status":result["mail_status"],"offline":True},status_code=202)
  _set_auth_cookie(response,session_token)
  return response
 except Exception as exc:
  status=409 if "already belongs" in str(exc) else 400
  return JSONResponse({"ok":False,"error":"An account already exists for this email." if status==409 else "Unable to start local registration."},status_code=status)

@app.get("/api/auth/local-mail")
async def local_mail(request:Request,purpose:str="registration"):
 token=request.cookies.get(SESSION_COOKIE_NAME)
 if not token:return JSONResponse({"error":"Registration session required."},status_code=401)
 message=AUTH_STORE.local_mail_for_session(token,purpose=purpose)
 if not message:return JSONResponse({"error":"No local message is available."},status_code=404)
 return JSONResponse({"purpose":message["purpose"],"status":message["status"],"verification_code":message["verification_code"],"offline":True})

@app.post("/api/auth/register/verify")
async def verify_registration(request:Request):
 token=request.cookies.get(SESSION_COOKIE_NAME)
 if not token:return JSONResponse({"error":"Registration session required."},status_code=401)
 data=await request.json()
 try:
  AUTH_STORE.verify_registration_code(token,str(data.get("code","")))
  result=AUTH_STORE.complete_registration(token)
 except Exception:
  return JSONResponse({"error":"Verification code is invalid or expired."},status_code=400)
 account=result["account"]
 response=JSONResponse({"authenticated":True,"email":account["email_normalized"],"name":account["display_name"],"offline":True})
 _set_auth_cookie(response,result["session_token"])
 return response

@app.get("/api/auth/session")
async def auth_session(request:Request):
 state=_session_state(request)
 if not state:return JSONResponse({"authenticated":False,"account":None})
 account=state.get("account")
 public=None if not account else {"email":account["email_normalized"],"name":account["display_name"]}
 return JSONResponse({"authenticated":bool(state.get("authenticated")),"account":public})

@app.post("/api/auth/login")
async def login(request:Request):
 data=await request.json();email=str(data.get("email","")).strip().lower()
 try:
  session_token,_=_auth_session(request)
  result=AUTH_STORE.sign_in(session_token,email=email,password=str(data.get("password","")))
  account=result["account"]
  response=JSONResponse({"ok":True,"email":account["email_normalized"],"name":account["display_name"],"offline":True,"backend":True})
  _set_auth_cookie(response,result["session_token"])
  return response
 except Exception:return JSONResponse({"ok":False,"error":"Email or password is incorrect."},status_code=401)
@app.post("/api/auth/logout")
async def logout(request:Request):
 try: AUTH_STORE.sign_out(request.cookies.get(SESSION_COOKIE_NAME))
 except Exception: pass
 response=JSONResponse({"ok":True,"offline":True}); response.delete_cookie(SESSION_COOKIE_NAME,path="/",secure=True,httponly=True,samesite="lax"); return response

@app.post("/secure/logout")
async def logout_page(request:Request):
 try: AUTH_STORE.sign_out(request.cookies.get(SESSION_COOKIE_NAME))
 except Exception: pass
 response=RedirectResponse("/secure/signin",status_code=303)
 response.delete_cookie(SESSION_COOKIE_NAME,path="/",secure=True,httponly=True,samesite="lax")
 return response

@app.post("/api/listings")
async def create_listing(request:Request):
 owner=_owner_subject(request)
 if not owner:return JSONResponse({"error":"Sign in is required."},status_code=401)
 data=await request.json()
 try:
  make=str(data.get("make","")).strip()
  year=int(data.get("year"));mileage=int(data.get("mileage"));price=int(data.get("price"))
  if not make or not 1900<=year<=2100 or mileage<0 or price<=0:raise ValueError
 except (TypeError,ValueError):
  return JSONResponse({"error":"Enter a valid make, year, mileage and price."},status_code=400)
 description=str(data.get("description","")).strip()[:2000]
 photo_count=max(0,min(int(data.get("photo_count",0) or 0),20))
 now=int(time.time())
 with SITE_BACKEND.lifecycle.connection(transaction=True) as connection:
  row=connection.execute("SELECT MAX(CAST(SUBSTR(listing_id,4) AS INTEGER)) AS n FROM autotrader_listings").fetchone()
  listing_id=f"AT-{max(754,int(row['n'] or 754))+1}"
  connection.execute(
   "INSERT INTO autotrader_listings(listing_id,owner_subject_id,make,year,mileage,price,description,photo_count,status,version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
   (listing_id,owner,make,year,mileage,price,description,photo_count,"pending-review",1,now,now),
  )
 listing=_owned_listing(owner,listing_id)
 return JSONResponse({"listing":_listing_dict(listing),"offline":True},status_code=201)

@app.post("/api/listings/session")
async def create_session_listing(request:Request):
 token,owner=_listing_state_owner(request)
 data=await request.json()
 try:
  make=str(data.get("make","")).strip()
  year=int(data.get("year"));mileage=int(data.get("mileage"));price=int(data.get("price"))
  if not make or not 1900<=year<=2100 or mileage<0 or price<=0:raise ValueError
 except (TypeError,ValueError):
  return JSONResponse({"error":"Enter a valid make, year, mileage and price."},status_code=400)
 description=str(data.get("description","")).strip()[:2000]
 photo_count=max(0,min(int(data.get("photo_count",0) or 0),20))
 now=int(time.time())
 with SITE_BACKEND.lifecycle.connection(transaction=True) as connection:
  row=connection.execute("SELECT MAX(CAST(SUBSTR(listing_id,4) AS INTEGER)) AS n FROM autotrader_listings").fetchone()
  listing_id=f"AT-{max(754,int(row['n'] or 754))+1}"
  connection.execute(
   "INSERT INTO autotrader_listings(listing_id,owner_subject_id,make,year,mileage,price,description,photo_count,status,version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
   (listing_id,owner,make,year,mileage,price,description,photo_count,"pending-review",1,now,now),
  )
 listing=_owned_listing(owner,listing_id)
 response=JSONResponse({"listing":_listing_dict(listing),"offline":True},status_code=201)
 _set_auth_cookie(response,token)
 return response

@app.post("/selling/submit")
async def submit_session_listing(request:Request):
 token,owner=_listing_state_owner(request)
 fields={key:values[-1] for key,values in parse_qs((await request.body()).decode("utf-8")).items()}
 try:
  make=str(fields.get("make","")).strip()
  year=int(fields.get("year"));mileage=int(fields.get("mileage"));price=int(fields.get("price"));photo_count=int(fields.get("photo_count","0"))
  if not make or not 1900<=year<=2100 or mileage<0 or price<=0 or not 0<=photo_count<=20:raise ValueError
 except (TypeError,ValueError):
  response=RedirectResponse("/selling/find-car?error=invalid",status_code=303);_set_auth_cookie(response,token);return response
 description=str(fields.get("description","")).strip()[:2000]
 now=int(time.time())
 with SITE_BACKEND.lifecycle.connection(transaction=True) as connection:
  row=connection.execute("SELECT MAX(CAST(SUBSTR(listing_id,4) AS INTEGER)) AS n FROM autotrader_listings").fetchone()
  listing_id=f"AT-{max(754,int(row['n'] or 754))+1}"
  connection.execute(
   "INSERT INTO autotrader_listings(listing_id,owner_subject_id,make,year,mileage,price,description,photo_count,status,version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
   (listing_id,owner,make,year,mileage,price,description,photo_count,"pending-review",1,now,now),
  )
 response=RedirectResponse("/selling/confirmation?id="+quote(listing_id),status_code=303)
 _set_auth_cookie(response,token)
 return response

@app.get("/api/listings/{listing_id}")
async def get_listing(listing_id:str,request:Request):
 owner=_owner_subject(request)
 if not owner:return JSONResponse({"error":"Sign in is required."},status_code=401)
 row=_owned_listing(owner,listing_id)
 if not row:return JSONResponse({"error":"Listing not found."},status_code=404)
 return JSONResponse({"listing":_listing_dict(row),"offline":True})

@app.patch("/api/listings/{listing_id}")
async def update_listing(listing_id:str,request:Request):
 owner=_owner_subject(request)
 if not owner:return JSONResponse({"error":"Sign in is required."},status_code=401)
 existing=_owned_listing(owner,listing_id)
 if not existing:return JSONResponse({"error":"Listing not found."},status_code=404)
 data=await request.json()
 try:
  expected=int(data.get("expected_version"));make=str(data.get("make","")).strip();year=int(data.get("year"));mileage=int(data.get("mileage"));price=int(data.get("price"));photo_count=int(data.get("photo_count",existing["photo_count"]) or 0)
  if not make or not 1900<=year<=2100 or mileage<0 or price<=0 or not 0<=photo_count<=20:raise ValueError
 except (TypeError,ValueError):return JSONResponse({"error":"Enter a valid make, year, mileage, price and photo count."},status_code=400)
 description=str(data.get("description",existing["description"])).strip()[:2000]
 with SITE_BACKEND.lifecycle.connection(transaction=True) as connection:
  current=connection.execute("SELECT version FROM autotrader_listings WHERE listing_id=? AND owner_subject_id=?",(listing_id,owner)).fetchone()
  if not current:return JSONResponse({"error":"Listing not found."},status_code=404)
  if int(current["version"])!=expected:return JSONResponse({"error":"Listing changed; refresh and retry."},status_code=409)
  connection.execute("UPDATE autotrader_listings SET make=?,year=?,mileage=?,price=?,description=?,photo_count=?,version=version+1,updated_at=? WHERE listing_id=? AND owner_subject_id=? AND version=?",(make,year,mileage,price,description,photo_count,int(time.time()),listing_id,owner,expected))
 return JSONResponse({"listing":_listing_dict(_owned_listing(owner,listing_id)),"offline":True})

@app.post("/api/listings/{listing_id}/actions")
async def listing_action(listing_id:str,request:Request):
 owner=_owner_subject(request)
 if not owner:return JSONResponse({"error":"Sign in is required."},status_code=401)
 data=await request.json();action=str(data.get("action","")).lower()
 statuses={"pause":"paused","renew":"active","remove":"removed"}
 if action not in statuses:return JSONResponse({"error":"Unsupported listing action."},status_code=400)
 try:expected=int(data.get("expected_version"))
 except (TypeError,ValueError):return JSONResponse({"error":"expected_version is required."},status_code=400)
 with SITE_BACKEND.lifecycle.connection(transaction=True) as connection:
  existing=connection.execute("SELECT version FROM autotrader_listings WHERE listing_id=? AND owner_subject_id=?",(listing_id,owner)).fetchone()
  if not existing:return JSONResponse({"error":"Listing not found."},status_code=404)
  if int(existing["version"])!=expected:return JSONResponse({"error":"Listing changed; refresh and retry."},status_code=409)
  connection.execute("UPDATE autotrader_listings SET status=?,version=version+1,updated_at=? WHERE listing_id=? AND owner_subject_id=? AND version=?",(statuses[action],int(time.time()),listing_id,owner,expected))
 row=_owned_listing(owner,listing_id)
 return JSONResponse({"listing":_listing_dict(row),"offline":True})

@app.get("/api/account/address")
async def get_address(request:Request):
 owner=_owner_subject(request)
 if not owner:return JSONResponse({"error":"Sign in is required."},status_code=401)
 with SITE_BACKEND.lifecycle.connection() as connection:
  row=connection.execute("SELECT address,city,postcode,delivery_option FROM autotrader_addresses WHERE owner_subject_id=?",(owner,)).fetchone()
 if not row:return JSONResponse({"error":"Address not found."},status_code=404)
 return JSONResponse(dict(row))

@app.put("/api/account/address")
async def put_address(request:Request):
 owner=_owner_subject(request)
 if not owner:return JSONResponse({"error":"Sign in is required."},status_code=401)
 data=await request.json()
 values=[str(data.get(k,"")).strip() for k in ("address","city","postcode","delivery_option")]
 if not all(values) or values[3] not in {"dealer-pickup","home-delivery"}:return JSONResponse({"error":"Complete the address and choose a delivery option."},status_code=400)
 with SITE_BACKEND.lifecycle.connection(transaction=True) as connection:
  connection.execute("INSERT INTO autotrader_addresses(owner_subject_id,address,city,postcode,delivery_option,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(owner_subject_id) DO UPDATE SET address=excluded.address,city=excluded.city,postcode=excluded.postcode,delivery_option=excluded.delivery_option,updated_at=excluded.updated_at",(owner,*values,int(time.time())))
 return JSONResponse({"address":values[0],"city":values[1],"postcode":values[2],"delivery_option":values[3],"offline":True})
@app.get("/{path:path}",response_class=HTMLResponse)
async def page(path:str,request:Request):
 route="/"+path.rstrip("/")
 if _is_frozen(route):return frozen_page(route)
 if route in {"/account","/secure/my-auto-trader","/account/history","/account/address"} or route.startswith("/account/listings/"):
  return account_surface(route,request)
 generated=synthetic(route,request)
 if generated is not None:return generated
 if route in EXACT_ROUTES or route in SNAPSHOT_ROUTES or route in INTERNAL_ROUTE_MAP or route in ROUTES:return render(route)
 if route=="/secure/register":return HTMLResponse(shell("Create your AutoTrader account",REGISTER_PAGE,route))
 if route=="/account":return HTMLResponse(shell("My AutoTrader",ACCOUNT_PAGE,route))
 return HTMLResponse(shell("Page not found","<div class='notice warn'><p>We couldn't find that page.</p><a class=button href=/cars/used>Return to used cars</a><a class='button secondary' href=/>AutoTrader home</a></div>",route),404)
