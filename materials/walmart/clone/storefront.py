"""Walmart homepage, captured navigation, and compact catalog browsing."""
from __future__ import annotations

import html
import json
import math
import os
import re
from pathlib import Path
from urllib.parse import quote, urlencode

DATA = Path(__file__).parent / 'data'
NAV = json.loads((DATA / 'navigation.json').read_text(encoding='utf-8'))
HOME = json.loads((DATA / 'homepage.json').read_text(encoding='utf-8'))
CATALOG = json.loads((DATA / 'catalog.json').read_text(encoding='utf-8'))
MEMBERS = json.loads((DATA / 'memberships.json').read_text(encoding='utf-8'))
CATEGORY_DETAILS = json.loads((DATA / 'product-details.json').read_text(encoding='utf-8'))
FOOTER = json.loads((DATA / 'footer.json').read_text(encoding='utf-8'))
BY_ID = {p['id']: p for p in CATALOG}
DEPARTMENTS = {d['id']: d for d in NAV['departments']}
ROUTES = {}
COLLECTIONS = {f'/collection/rollback-{i}': g for i, g in enumerate(HOME['rollbacks'])}

def esc(value):
    return html.escape(str(value), quote=True)

def money(value):
    return f'${value / 100:,.2f}'

def icon(name, size=24):
    paths = {
        'share': '<path d="M12 16V2m-4 4 4-4 4 4M5 10H3v12h18V10h-2"/>',
        'search': '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
        'heart': '<path d="M20.5 4.6a5.5 5.5 0 0 0-8.5 1 5.5 5.5 0 0 0-8.5-1C-2 10 7 17 12 21c5-4 14-11 8.5-16.4Z"/>',
        'user': '<circle cx="12" cy="7" r="4"/><path d="M4 22v-3a8 8 0 0 1 16 0v3"/>',
        'cart': '<path d="M2 3h3l3 13h11l3-9H6"/><circle cx="9" cy="21" r="1"/><circle cx="19" cy="21" r="1"/>',
        'grid': '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
        'down': '<path d="m5 9 7 7 7-7"/>',
        'right': '<path d="m9 5 7 7-7 7"/>',
        'left': '<path d="m15 5-7 7 7 7"/>',
        'close': '<path d="m5 5 14 14M19 5 5 19"/>',
        'plus': '<path d="M12 4v16M4 12h16"/>',
        'pin': '<path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/>',
        'truck': '<path d="M2 5h12v12H2ZM14 9h5l3 5v3h-8"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="19" r="2"/>',
        'bag': '<path d="M4 8h16l1 14H3ZM8 9V6a4 4 0 0 1 8 0v3"/>',
        'play': '<path d="m8 4 13 8-13 8Z"/>',
        'clock': '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
    }
    return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{paths.get(name, paths["grid"])}</svg>'

def image_file(key):
    return next((v['image'] for k, v in HOME['images'].items() if key in k), '')

def img(image, alt='', cls='', eager=False):
    return f'<img src="/static/assets/{esc(image)}" alt="{esc(alt)}" class="{cls}" loading="{"eager" if eager else "lazy"}" decoding="async">' if image else ''

def link_for(kind, department, group_index, item):
    prefix = 'category' if kind == 'departments' else 'service'
    first = department['groups'][0]['items'][0]
    if kind == 'departments' and item['source'] == first['source']:
        path = f'/{prefix}/{department["id"]}'
    else:
        path = f'/{prefix}/{department["id"]}/{group_index}-{item["id"]}'
    ROUTES[path] = {'kind': kind, 'department': department, 'item': item}
    return path

for kind, departments in NAV.items():
    for d in departments:
        for gi, group in enumerate(d['groups']):
            for item in group['items']:
                item['href'] = link_for(kind, d, gi, item)

def menu(kind):
    title = 'Departments' if kind == 'departments' else 'Services'
    left = []
    right = []
    for i, d in enumerate(NAV[kind]):
        left.append(f'<button type="button" data-menu-tab="{kind}-{i}" aria-controls="{kind}-{i}" aria-expanded="{str(i == 0).lower()}" class="menu-tab{" active" if i == 0 else ""}">{esc(d["name"])}{icon("right",16)}</button>')
        groups = ''.join('<section><h3>'+esc(g['title'])+'</h3>'+''.join(f'<a href="{item["href"]}">{esc(item["label"])}</a>' for item in g['items'])+'</section>' for g in d['groups'])
        right.append(f'<div id="{kind}-{i}" class="menu-content" {"hidden" if i else ""}><button class="mobile-menu-back link-button" type="button" data-menu-back>{icon("left",18)} All {title.lower()}</button><div class="menu-columns">{groups}</div></div>')
    return f'<section class="mega-panel overlay-panel" id="panel-{kind}" data-panel="{kind}" role="dialog" aria-label="{title}" hidden><div class="panel-heading"><b>{title}</b><button class="icon-button" data-close aria-label="Close {title}">{icon("close")}</button></div><div class="mega-body"><nav class="menu-tabs" aria-label="{title} categories">{"".join(left)}</nav><div class="menu-detail">{"".join(right)}</div></div></section>'

def shell(content, title, count, subtotal, search='', account=None):
    logo = image_file('spark-icon')
    logo_html = img(logo, 'Walmart', eager=True) if logo else '<span class="spark-mark">✳</span>'
    pills = [('Rollbacks & More','/category/rollbacks-more'),('Halloween','/category/halloween'),('Get it Fast','/search?fulfillment=Pickup'),('Pharmacy','/info/pharmacy-delivery'),('New Arrivals','/info/new-arrivals'),('The Baby Event','/category/baby-kids'),('Game Day','/category/sports-outdoors'),('Meals Made Easy','/category/grocery'),('My Items','/account-entry?view=items'),('Only at Walmart','/info/only-at-walmart'),('Credit Card','/info/credit-card'),('Walmart+','/info/walmart-plus')]
    pill_html = ''.join(f'<a href="{href}">{text}</a>' for text, href in pills)
    footer_local = {'All Departments':'/all-departments','Help':'/help','Delete Account':'/account-entry','Your Privacy Choices':'/privacy'}
    footlinks = ''.join(f'<a href="{esc(footer_local.get(i["text"],i["href"]))}" {"" if i["text"] in footer_local else "target=_blank rel=noopener"}>{esc(i["text"])}</a>' for i in FOOTER)
    account_name = account['display_name'] if account else 'Account'
    account_small = 'Hi' if account else 'Sign In'
    if account:
        account_panel = f'''<p class="account-greeting">Hi, {esc(account_name)}</p><a href="/account-entry?view=purchases">Purchase History</a><a href="/info/walmart-plus">Walmart+</a><a href="/info/subscriptions">Subscriptions</a><form method="post" action="/account/logout"><button class="button outline wide" type="submit">Sign out</button></form>'''
        sparky_account = f'''<p>Hi, {esc(account_name)}! I can help you browse this local catalog.</p><a class="button primary" href="/search">Start shopping</a><p>AI chat is not included in this preview.</p>'''
    else:
        account_panel = '''<a class="button primary" href="/account-entry">Sign in or create account</a><a href="/account-entry?view=purchases">Purchase History</a><a href="/info/walmart-plus">Walmart+</a><a href="/info/subscriptions">Subscriptions</a>'''
        sparky_account = '''<p>Sign in to keep local orders in your purchase history.</p><a class="button primary" href="/account-entry">Sign in</a><p>AI chat is not included in this preview.</p>'''
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title><link rel="stylesheet" href="/frontend/styles.css"><script src="/frontend/app.js" defer></script></head>
<body><a class="skip-link" href="#main">Skip to Main Content</a><header class="site-header"><div class="topbar">
<a class="logo" href="/" aria-label="Walmart home">{logo_html}</a>
<button class="fulfillment-button" data-open="fulfillment" aria-controls="panel-fulfillment" aria-expanded="false">{img(image_file('0a671c38'),'','fulfillment-art',True)}<span><b>Pickup or delivery?</b><small data-location>Sacramento, 95829</small></span>{icon('down',16)}</button>
<form action="/search" method="get" class="search-form" role="search"><label class="sr-only" for="global-search">Search Walmart</label><input id="global-search" name="q" value="{esc(search)}" placeholder="Search everything at Walmart online and in store" autocomplete="off" role="combobox" aria-autocomplete="list" aria-controls="search-suggestions" aria-expanded="false"><button aria-label="Search" type="submit">{icon('search')}</button><div id="search-suggestions" role="listbox" hidden></div></form>
<button class="header-action reorder" data-open="reorder" aria-controls="panel-reorder" aria-expanded="false">{icon('heart')}<span><small>Reorder</small><b>My Items</b></span></button>
<button class="header-action account" data-open="account" aria-controls="panel-account" aria-expanded="false">{icon('user')}<span><small>{esc(account_small)}</small><b>{esc(account_name)}</b></span></button>
<a class="cart-link" href="/cart" aria-label="Cart with {count} items">{icon('cart',28)}<b data-cart-count>{count}</b><small data-cart-total>{money(subtotal)}</small></a></div>
<nav class="secondary-nav" aria-label="Primary"><button data-open="departments" aria-controls="panel-departments" aria-expanded="false">{icon('grid',16)} Departments {icon('down',14)}</button><button data-open="services" aria-controls="panel-services" aria-expanded="false">{icon('grid',16)} Services {icon('down',14)}</button><span class="nav-divider"></span><div class="nav-pills">{pill_html}</div><button class="more-button" data-open="more" aria-controls="panel-more" aria-expanded="false">More {icon('down',14)}</button></nav>
</header><div class="scrim" data-scrim hidden></div>{menu('departments')}{menu('services')}
<section class="overlay-panel small-panel fulfillment-panel" id="panel-fulfillment" data-panel="fulfillment" role="dialog" aria-label="Pickup or delivery" hidden><div class="panel-heading"><b>How do you want your items?</b><button class="icon-button" data-close aria-label="Close fulfillment">{icon('close')}</button></div><div class="method-options">{''.join(f'<button data-method="{m}" aria-pressed="false">{img(image_file(i),"","method-art")}<b>{m}</b></button>' for m,i in [('Shipping','4be6f532'),('Pickup','333618e2'),('Delivery','c8d39665')])}</div><div class="location-card"><b>{icon('pin',18)} <span data-store>Sacramento Supercenter</span></b><p data-store-address>8915 Gerber Road, Sacramento, CA 95829</p><form id="location-form"><label for="test-zip">ZIP code</label><input id="test-zip" name="zip" inputmode="numeric" pattern="[0-9]{{5}}" maxlength="5" value="95829" required><small>Preview locations: 95829, 10001 or 90210. No personal address is collected.</small><button class="button primary" type="submit">Save location</button><p id="location-status" role="status"></p></form></div></section>
<section class="overlay-panel small-panel account-panel" id="panel-account" data-panel="account" role="dialog" aria-label="Account" hidden><div class="panel-heading"><b>Account</b><button class="icon-button" data-close aria-label="Close Account">{icon('close')}</button></div>{account_panel}<details class="language-choice"><summary>Language | English</summary><h3>Select language</h3><p>English is the definitive version, and any translations serve only as a guide.</p><label><input type="radio" name="language" checked value="en"> English</label><label><input type="radio" name="language" value="es" disabled> Español</label><p>Spanish translation is not included in this preview.</p><button type="button" class="button primary" data-close>Save</button></details></section>
<section class="overlay-panel small-panel reorder-panel" id="panel-reorder" data-panel="reorder" role="dialog" aria-label="My Items" hidden><div class="panel-heading"><b>My Items</b><button class="icon-button" data-close aria-label="Close My Items">{icon('close')}</button></div><a href="/account-entry?view=reorder">Reorder</a><a href="/account-entry?view=lists">Lists</a><a href="/info/registries">Registries</a></section>
<section class="overlay-panel small-panel more-panel" id="panel-more" data-panel="more" role="dialog" aria-label="More navigation" hidden><div class="panel-heading"><b>More</b><button class="icon-button" data-close aria-label="Close More">{icon('close')}</button></div>{pill_html}</section>
<main id="main">{content}</main><section class="feedback-band"><p>We’d love to hear what you think!</p><button class="button outline" data-open="feedback" aria-controls="panel-feedback" aria-expanded="false">Give feedback</button></section><footer class="site-footer"><nav aria-label="Footer">{footlinks}</nav><p>© 2026 Walmart. The trademarks Walmart and the Walmart Spark design are registered with the US Patent and Trademark Office. All Rights Reserved.</p></footer>
<button class="sparky" data-open="sparky" aria-controls="panel-sparky" aria-expanded="false" aria-label="Open Sparky, your AI shopping assistant">{logo_html}</button><section class="overlay-panel feedback-panel sparky-panel" data-panel="sparky" id="panel-sparky" role="dialog" aria-label="Sparky" hidden><div class="panel-heading"><h2>Ask me anything</h2><button data-close class="icon-button" aria-label="Close Sparky">{icon('close')}</button></div><div class="sparky-message"><small>AI</small>{sparky_account}</div></section><section class="overlay-panel feedback-panel" data-panel="feedback" id="panel-feedback" role="dialog" aria-label="Feedback" hidden><div class="panel-heading"><h2>How was your experience?</h2><button data-close class="icon-button" aria-label="Close feedback">{icon('close')}</button></div><form id="feedback-form"><p>Your feedback matters! Help us improve the Walmart website.</p><fieldset class="feedback-rating"><legend>Rate your experience (1 = Very poor, 5 = Excellent!)</legend><label><input type="radio" name="feedback-rating" value="1" required aria-label="Very poor"><span>1</span><small>Very poor</small></label><label><input type="radio" name="feedback-rating" value="2" required aria-label="Poor"><span>2</span><small>Poor</small></label><label><input type="radio" name="feedback-rating" value="3" required aria-label="Fair"><span>3</span><small>Fair</small></label><label><input type="radio" name="feedback-rating" value="4" required aria-label="Good"><span>4</span><small>Good</small></label><label><input type="radio" name="feedback-rating" value="5" required aria-label="Excellent!"><span>5</span><small>Excellent!</small></label></fieldset><label for="feedback-text">Comments (optional)</label><textarea id="feedback-text" maxlength="1000"></textarea><p>Feedback stays on this device. Nothing is sent.</p><button class="button primary">Save feedback locally</button><p role="status" id="feedback-status"></p></form></section><div class="toast" role="status" hidden></div></body></html>'''

def product_card(p, compact=False):
    options = p.get('options', [])
    option_id = options[0][0] if options and isinstance(options[0], (list,tuple)) else (options[0]['option_id'] if options else 'captured')
    badge = f'<span class="badge">{esc(p["badges"])}</span>' if p.get('badges') else ''
    was = f'<s>{money(p["was_cents"])}</s>' if p.get('was_cents') else ''
    rating = f'<div class="rating">★ {p["rating"]} <span>({p.get("reviews",p.get("review_count",0)):,})</span></div>' if p.get('rating') else ''
    needs_option = len(options)>1 or BY_ID.get(p['id'],{}).get('requires_options',False)
    action = f'<a class="button outline compact" href="/product/{esc(p["slug"])}">Options</a>' if needs_option else f'<form method="post" action="/cart/add" class="quick-add"><input type="hidden" name="product_id" value="{esc(p["id"])}"><input type="hidden" name="option_id" value="{esc(option_id)}"><button class="button outline compact" type="submit">{icon("plus",18)} Add</button></form>'
    return f'<article class="product-card{" mini-product" if compact else ""}" data-product-id="{esc(p["id"])}"><div class="product-visual"><a href="/product/{esc(p["slug"])}" class="product-image">{img(p["image"],p["name"])}</a><button class="favorite icon-button" data-favorite aria-label="Save {esc(p["name"])} to favorites">{icon("heart",20)}</button>{badge}</div><div class="product-action">{action}</div><div class="price-row"><strong class="{"sale-price" if was else ""}">{money(p["price_cents"])}</strong>{was}</div><a class="product-name" href="/product/{esc(p["slug"])}">{esc(p["name"])}</a>{rating}<p class="fulfillment" data-availability="{esc(p["fulfillment"])}">{esc(p["fulfillment"].split("|")[0].split()[0])} · preview availability</p></article>'

def scroller(items, label, cls=''):
    return f'<div class="scroller {cls}" data-carousel><div class="scroll-track" tabindex="0" aria-label="{esc(label)}">{items}</div><button class="carousel-arrow prev icon-button" data-direction="-1" aria-label="Previous {esc(label)}">{icon("left")}</button><button class="carousel-arrow next icon-button" data-direction="1" aria-label="Next {esc(label)}">{icon("right")}</button></div>'


def homepage():
    hero_slides = [
        ('16f645b5','Save up to $109/yr. with Peacock or Paramount+','Members get movies & more','/info/walmart-plus','Try Walmart+ for $1'),
        ('32be59a6','New premium beauty','StriVectin, PÜR Minerals & more','/category/beauty','Shop now'),
        ('f2589321','The active edit','Athletic Works, Avia & Reebok','/category/clothing-shoes-accessories','Shop now'),
        ('15897733','Labor Day savings you can’t miss','Rollbacks & more','/category/rollbacks-more','Shop now'),
        ('1d2b3ff1','The fall home edit','Bring the season home','/category/home-garden-tools','Shop now'),
    ]
    hero = '<section class="membership-carousel" aria-label="Featured offers">'+''.join(f'<article class="promo membership-hero hero-slide" data-hero-slide="{i}" {"hidden" if i else ""}>{img(image_file(key),"",eager=True)}<div class="promo-copy"><p>{esc(sub)}</p><h2>{esc(title)}</h2><a href="{href}">{cta}</a></div></article>' for i,(key,title,sub,href,cta) in enumerate(hero_slides))+'<div class="hero-controls" aria-label="Select featured offer"><button data-hero-step="-1" aria-label="Previous featured offer">'+icon('left',14)+'</button><button data-hero-play aria-label="Play carousel">'+icon('play',14)+'</button><button data-hero-step="1" aria-label="Next featured offer">'+icon('right',14)+'</button>'+''.join(f'<button data-hero-select="{i}" aria-label="Offer {i+1}: {esc(slide[1])}" aria-pressed="{str(i==0).lower()}"></button>' for i,slide in enumerate(hero_slides))+'</div></section>'
    top = f'''<section class="mosaic top-mosaic" aria-label="Seasonal favorites">
    <article class="promo mosaic-left baby-nursery">{img(image_file('e74d9323'),'Baby Event nursery with crib and plaid armchair',eager=True)}<div class="promo-copy"><p>Save up to $250 on 3 select items</p><h2>Free furniture shipping & assembly*</h2><a href="/category/baby-kids">Shop now</a></div></article>
    <div class="mosaic-middle"><article class="promo mosaic-wide cleaning-promo">{img(image_file('41e332ba'),'Blue toy octopus beside a vacuum',eager=True)}<div class="promo-copy"><p>With $300 registry spend</p><h2>Get a free home cleaning*</h2><a href="/info/baby-registry">Learn more</a></div></article>
    <div class="mosaic-pair"><article class="promo gaming-gift">{img(image_file('aa9c279b'),'PlayStation gift card',eager=True)}<div class="promo-copy"><h2>Can’t lose: gaming gift cards</h2><a href="/category/gaming-movies">Shop now</a></div></article><article class="promo birthday-gift">{img(image_file('58344b16'),'Birthday gift bag and party plates',eager=True)}<div class="promo-copy"><h2>Get birthday party faves, fast!</h2><a href="/category/party-supplies">Shop now</a></div></article></div></div>
    <article class="promo mosaic-right pharmacy-promo">{img(image_file('8f42436d'),'Mother and daughter, and a Walmart pharmacy delivery bag',eager=True)}<div class="promo-copy"><p>Relief at your door in 1 hour</p><h2>Kids’ cold & flu Rx delivery*</h2><a href="/info/pharmacy-delivery">Learn more</a></div></article></section>'''
    rollback_items = ''.join('<section class="rollback-group"><div class="section-heading"><h3>'+esc(g['title'])+'</h3><a href="'+path+'">View all</a></div><div class="mini-grid">'+''.join(product_card(BY_ID[i],True) for i in g['ids'][:4])+'</div></section>' for path,g in COLLECTIONS.items())
    rollbacks = '<section class="home-section"><h2>Rollbacks & more</h2>'+scroller(rollback_items,'rollback groups','rollback-scroller')+'</section>'
    personal = [BY_ID[i] for i in MEMBERS.get('Personal Care',[])][:6]
    personal_section = '<section class="split-section personal-section"><div class="split-products"><div class="section-heading"><h2>Can’t-miss personal care</h2><a href="/category/personal-care">View all</a></div><p class="section-subtitle">Stock up on your everyday essentials.</p>'+scroller(''.join(product_card(p) for p in personal),'personal care','three-cards')+'</div>'+f'<article class="semester-banner"><div><p>Full-sized to travel-sized picks</p><h2>Stay stocked this semester</h2><a href="/category/personal-care">Shop now</a></div>{img(image_file("04ee9c5b"),"Personal care and beauty products on a blue bathroom shelf")}</article></section>'
    circle_ids = ['rollbacks-more','grocery','home-garden-tools','home-garden-tools','clothing-shoes-accessories','electronics','toys-outdoor-play','pharmacy-health-wellness','personal-care','beauty','auto-tires','home-garden-tools']
    circles = ''.join(f'<a href="/category/{circle_ids[i % len(circle_ids)]}">{img(c["image"],"")}<span>{esc(c["title"])}</span></a>' for i,c in enumerate(HOME['circles']))
    circles = '<section class="home-section category-section"><div class="section-heading"><h2>Get it all right here</h2><a href="/all-departments">View all</a></div>'+scroller(circles,'departments','circle-scroller')+'</section>'
    baby_ids = HOME['carousels'].get('The latest you’ll love',[]) or MEMBERS.get('Baby & Kids',[])
    baby = f'<section class="split-section baby-section"><article class="promo split-promo baby-event">{img(image_file("cbb34c28"),"The Baby Event: an expectant parent holding a baby onesie")}<div class="promo-copy"><p>Prep for baby’s arrival</p><h2>Big savings & new brands!</h2><a href="/category/baby-kids">Shop now</a></div></article><div class="split-products"><div class="section-heading"><h2>The latest you’ll love</h2><a href="/category/baby-kids">View all</a></div>'+scroller(''.join(product_card(BY_ID[i]) for i in baby_ids if i in BY_ID),'baby products','three-cards')+'</div></section>'
    flash_ids = HOME['carousels'].get('Flash Deals',[])
    deadline = esc(os.environ.get('WALMART_FLASH_ENDS_AT',''))
    flash = '<section class="home-section"><div class="section-heading"><h2>Flash Deals</h2><a href="/category/rollbacks-more/0-flash-deals">View all</a></div><p class="section-subtitle">Up to 65% off <span class="deal-clock" data-deal-deadline="'+deadline+'">Captured offers · countdown unavailable</span></p>'+scroller(''.join(product_card(BY_ID[i]) for i in flash_ids if i in BY_ID),'flash deals','six-cards')+'</section>'
    videos = ''.join(f'<article class="video-card"><div class="video-frame"><video controls playsinline muted preload="metadata" poster="/static/assets/{esc(v["poster"])}" src="/static/assets/{esc(v["video"])}" aria-label="Video from {esc(v["creator"])}"></video><span class="creator">{esc(v["creator"])}</span></div><a class="video-product" href="/product/{esc(BY_ID[v["id"]]["slug"])}">{img(v["product_image"],"")}<span><strong>{money(BY_ID[v["id"]]["price_cents"])}</strong><br>{esc(v["name"])}</span></a></article>' for v in HOME['videos'] if v['video'] and v['id'] in BY_ID)
    video_section = '<section class="home-section"><h2>Featured in videos</h2>'+scroller(videos,'featured videos','video-scroller')+'</section>'
    social = ''
    for i, post in enumerate(HOME['social']):
        tags = ''.join(f'<a href="{esc(tag["source"])}" target="_blank" rel="noopener noreferrer"><span>{esc(tag["name"])}</span><b>{esc(tag["price"])}</b>{icon("right",16)}</a>' for tag in post['tags'])
        social += f'<article class="social-card">{img(post["image"],"Photo from "+post["creator"])}<span class="creator">{esc(post["creator"])}</span><button class="social-hotspot" data-social="{i}" aria-expanded="true" aria-controls="social-tags-{i}" aria-label="View products featured by {esc(post["creator"])}">{icon("plus",22)}</button><div class="social-tags" id="social-tags-{i}">{tags}</div></article>'
    social_section = '<section class="home-section"><h2>Trending on social</h2>'+scroller(social,'social posts','social-scroller')+'</section>'
    bottom = f'''<section class="mosaic bottom-mosaic" aria-label="More for everyday life"><article class="promo mosaic-left telehealth-promo"><div class="promo-copy"><p>Telehealth, your way</p><h2>Licensed professionals available 24/7</h2><a href="/info/telehealth">Learn more</a></div>{img(image_file('32d001f4'),'Family consulting a health professional by video')}</article><div class="mosaic-middle"><article class="promo mosaic-wide wearable-promo">{img(image_file('07ebc34d'),'Apple Watch with tortoiseshell-style band')}<div class="promo-copy"><h2>Wearable tech for college</h2><a href="/category/electronics/0-wearables-smart-tech">Shop now</a></div></article><div class="mosaic-pair"><article class="promo lunch-promo">{img(image_file('dca2539c'),'Lunch gear')}<div class="promo-copy"><h2>Lunch gear from $2.97</h2><a href="/category/school-office-art-supplies">Shop now</a></div></article><article class="promo boo-promo">{img(image_file('04a8d357'),'Candy and toys in a ghost-shaped basket')}<div class="promo-copy"><h2>Build a boo basket</h2><a href="/category/halloween">Shop now</a></div></article></div></div><article class="promo mosaic-right pool-promo"><div class="promo-copy"><h2>Get your pool winter-ready</h2><a href="/category/sports-outdoors">Shop now</a></div>{img(image_file('cdc94e14'),'Above-ground swimming pool')}</article></section>'''
    return '<div class="home-layout"><h1 class="sr-only">Walmart — Save money. Live better.</h1>'+hero+top+rollbacks+personal_section+circles+baby+flash+video_section+social_section+bottom+'</div>'

def suggestions(query, products):
    term = query.strip().lower()
    if not term:
        return []
    results = [{'label':d['name'], 'url':'/category/'+d['id'], 'kind':'Department'} for d in NAV['departments'] if term in d['name'].lower()]
    brands = sorted({p['brand'] for p in products if term in p['brand'].lower()})
    results += [{'label':b,'url':'/search?'+urlencode({'q':b,'brand':b}),'kind':'Brand'} for b in brands[:3]]
    results += [{'label':p['name'],'url':'/product/'+p['slug'],'kind':'Product'} for p in products if all(t in (p['name']+' '+p['brand']+' '+p['category']).lower() for t in term.split())][:8]
    return results[:10]

def all_departments():
    return '<section class="page-section"><p class="breadcrumbs"><a href="/">Home</a> / All Departments</p><h1>All Departments</h1><div class="department-grid">'+''.join(f'<a href="/category/{d["id"]}"><h2>{esc(d["name"])}</h2><p>{len(MEMBERS.get(d["name"],[]))} items in this preview</p></a>' for d in NAV['departments'])+'</div></section>'

def subcategory_matches(label, product):
    # Compound menu entries describe alternatives, not words every item must contain.
    aliases = {'fresh produce':'fruit|vegetable|tomato|potato|lettuce|berry|banana|apple',
               'beverages':'drink|juice|soda|tea|coffee|water',
               'meat':'meat|beef|chicken|pork|turkey', 'seafood':'seafood|fish|shrimp|salmon',
               'shoes':'shoe|sneaker|boot|sandal', 'bedding':'sheet|pillow|blanket|comforter',
               'haircare':'shampoo|conditioner|hair', 'oral care':'toothpaste|toothbrush|mouthwash',
               'stuffed animals':'plush|stuffed', 'tv':'tv|television',
               'laptops':'laptop|notebook', 'pcs':'computer|desktop',
               'fashion':'clothing|shirt|dress|jacket|jeans', 'jewelry':'jewelry|necklace|earring|ring',
               'baking':'flour|cake|baking|cupcake', 'pantry':'pasta|rice|soup|sauce|canned',
               'floral shop':'flower|bouquet|rose', 'alcohol':'wine|beer|vodka|whiskey'}
    def words(text):
        return {w[:-1] if len(w)>3 and w.endswith('s') and not w.endswith('ss') else w for w in re.findall(r'[a-z0-9]+',text.lower())}
    meta=CATEGORY_DETAILS.get(product['id'],{})
    text=product['name']+' '+meta.get('type','')+' '+' '.join(meta.get('category',[])[1:])
    actual=words(text)
    for part in re.split(r'\s*(?:&|\band\b|,)\s*',label.lower()):
        part=re.sub(r'^(all|shop)\s+','',part).strip()
        if part=='alcohol' and re.search(r'non[ -]?alcohol',text,re.I):continue
        if part in aliases:
            if any(words(term)<=actual for term in aliases[part].split('|')):return True
        else:
            wanted=words(part)-{'all','shop','the','for','more','s','in'}
            if wanted and wanted<=actual:return True
    return False

def category_products(path, products):
    d=DEPARTMENTS[path.split('/')[2]]
    ids=set(MEMBERS.get(d['name'],[]))
    parent=[p for p in products if p['id'] in ids or p['category'].lower()==d['name'].lower()]
    entry=ROUTES.get(path)
    if path.count('/')<=2 or not entry:return parent,False
    label=entry['item']['label'].lower()
    if 'flash-deals' in path:
        matches=[p for p in products if p['id'] in HOME['carousels'].get('Flash Deals',[])]
    elif label in {'shop all','rollbacks'}:matches=parent
    elif label=='clearance':matches=[p for p in parent if 'clearance' in p['badges'].lower()]
    else:matches=[p for p in parent if subcategory_matches(label,p)]
    # Keep parent recommendations explicit, and apply user filters afterwards.
    return (matches,False) if matches else (parent,True)

def listing(path, query, products):
    d = DEPARTMENTS.get(path.split('/')[2]) if path.startswith('/category/') else None
    entry = ROUTES.get(path)
    deep = d and path.count('/') > 2
    label = entry['item']['label'] if deep and entry else (d['name'] if d else 'Search')
    q = query.get('q','').strip()
    base = list(products)
    recommendations = False
    collection = COLLECTIONS.get(path)
    if collection:
        base = [p for p in base if p['id'] in collection['ids']]
        label = collection['title']
    if d:
        base,recommendations = category_products(path,products)
    if q:
        base = [p for p in base if all(t in (p['name']+' '+p['brand']+' '+p['category']).lower() for t in q.lower().split())]
    brands = sorted({p['brand'] for p in base})
    found = list(base)
    if query.get('brand'):
        found = [p for p in found if p['brand'].lower()==query['brand'].lower()]
    if query.get('fulfillment'):
        found = [p for p in found if query['fulfillment'].lower() in p['fulfillment'].lower()]
    for key, compare in [('min_price',lambda a,b:a>=b),('max_price',lambda a,b:a<=b)]:
        try:
            value = float(query.get(key,''))
            if math.isfinite(value) and value >= 0:
                found = [p for p in found if compare(p['price_cents'],round(value*100))]
        except ValueError:
            pass
    sort = query.get('sort','best')
    if sort in {'price-low','price-high'}:
        found.sort(key=lambda p:(p['price_cents'],p['name']),reverse=sort=='price-high')
    elif sort=='rating':
        found.sort(key=lambda p:(p['rating'],p.get('review_count',0)),reverse=True)
    pages = max(1,math.ceil(len(found)/12))
    try:
        page = min(pages,max(1,int(query.get('page','1'))))
    except ValueError:
        page = 1
    def select(name, options):
        return f'<select name="{name}">'+''.join(f'<option value="{esc(value)}" {"selected" if query.get(name, "best" if name=="sort" else "")==value else ""}>{esc(text)}</option>' for value,text in options)+'</select>'
    filters = f'<form method="get" action="{esc(path)}" class="filters" data-filter-form><h2>Filters & sort</h2><input type="hidden" name="q" value="{esc(q)}"><label>Brand{select("brand",[("","All brands")]+[(b,b) for b in brands])}</label><fieldset><legend>Price</legend><div class="price-inputs"><label>Min<input name="min_price" type="number" min="0" step=".01" value="{esc(query.get("min_price",""))}" placeholder="$0"></label><label>Max<input name="max_price" type="number" min="0" step=".01" value="{esc(query.get("max_price",""))}" placeholder="Any"></label></div></fieldset><label>Availability{select("fulfillment",[("","Any"),("Shipping","Shipping"),("Pickup","Pickup"),("Delivery","Delivery")])}</label><label>Sort by{select("sort",[("best","Best Match"),("price-low","Price: low to high"),("price-high","Price: high to low"),("rating","Top rated")])}</label><button class="button primary">Apply filters</button><a class="clear-filters" href="{path}?{urlencode({"q":q})}">Clear all</a></form>'
    title = label if d or collection else f'Results for “{q or "all products"}”'
    active = ' · '.join(esc(query[k]) for k in ('brand','min_price','max_price','fulfillment') if query.get(k))
    children = ''
    if d and not deep:
        children = '<nav class="category-chips" aria-label="Subcategories">'+''.join(f'<a href="{i["href"]}">{esc(i["label"])}</a>' for g in d['groups'] for i in g['items'] if i['href']!=path)+'</nav>'
    cards = ''.join(product_card(p) for p in found[(page-1)*12:page*12])
    recommendation_note = f'<aside class="category-recommendation"><h2>Explore more from {esc(d["name"])}</h2><p>Items in {esc(label)} are not in this catalog yet. Browse these {esc(d["name"])} products instead.</p></aside>' if recommendations else ''
    if not found:
        cards = '<div class="no-results"><h2>No matching items</h2><p>'+'Try a different keyword or clear your filters.'+f'</p><a href="{("/category/"+d["id"]) if d else "/all-departments"}">{"Back to "+esc(d["name"]) if d else "Browse departments"}</a></div>'
    pagination = '<nav class="pagination" aria-label="Pages">'+''.join(f'<a href="{path}?{urlencode({**query,"page":n})}" {"aria-current=page" if n==page else ""}>{n}</a>' for n in range(1,pages+1))+'</nav>' if pages>1 else '<p class="end-results">You’ve reached the end of this selection.</p>'
    parent = f'<a href="/category/{d["id"]}">{esc(d["name"])}</a> / ' if deep else ''
    return f'<section class="page-section search-page"><p class="breadcrumbs"><a href="/">Home</a> / {parent}{esc(label)}</p><div class="search-title"><div><h1>{esc(title)}</h1><p>{len(found)} {"recommended items" if recommendations else "results"}{(" · "+active) if active else ""}</p></div><button class="button outline mobile-filter" data-filter-toggle aria-expanded="false">Filters & sort</button></div>{children}<div class="search-layout">{filters}<div class="results">{recommendation_note}<div class="product-grid search-grid">{cards}</div>{pagination}</div></div></section>'

def information(path, query):
    entry = ROUTES.get(path)
    if path in {'/info/telehealth', '/info/pharmacy-delivery', '/info/baby-registry'}:
        entry = next((e for e in ROUTES.values() if e['kind']=='services' and e['item']['id']==path.split('/')[-1]), None)
    if entry and entry['kind']=='services':
        title = entry['item']['label']
        import service_pages
        content=service_pages.render(entry['item']['source'],title)
        if content:return content,title
        body = f'<p>{esc(entry["department"]["name"])}</p><p>This service requires Walmart’s live service. Appointments, subscriptions and personal information are not submitted in this preview.</p><a class="button outline" target="_blank" rel="noopener noreferrer" href="{esc(entry["item"]["source"])}">Read about {esc(title)} on Walmart.com</a>'
    elif path.startswith('/info/social-'):
        title = 'Shop the look'
        body = '<p>Product tags for this creator’s post are not available in the captured catalog.</p><a href="/category/clothing-shoes-accessories">Browse fashion</a> · <a href="/category/home-garden-tools">Browse home</a>'
    else:
        title = path.split('/')[-1].replace('-',' ').title()
        body = '<p>This feature is not available in the local shopping preview.</p><p>You can browse the catalog, change your preview location, and manage your cart.</p><a href="/all-departments" class="button primary">Browse departments</a>'
        if 'walmart-plus' in path:
            title='Walmart+'
            body='<h2>Members get movies & more</h2><p>The reference offer includes Peacock or Paramount+ with a Walmart+ membership. Membership enrollment and billing are not available in this preview.</p><a href="https://www.walmart.com/plus" target="_blank" rel="noopener noreferrer">View current Walmart+ terms</a>'
    return f'<section class="page-section narrow boundary-page"><p class="breadcrumbs"><a href="/">Home</a> / {esc(title)}</p><h1>{esc(title)}</h1>{body}</section>', title

