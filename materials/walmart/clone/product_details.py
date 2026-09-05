"""Product detail layouts driven by captured product content, not merchandising shelves."""
import json,re
from pathlib import Path
from urllib.parse import quote
import storefront as s
DETAILS=json.loads((Path(__file__).parent/'data/product-details.json').read_text(encoding='utf-8'))
PROMOTIONS=json.loads((Path(__file__).parent/'data/detail-promotions.json').read_text(encoding='utf-8'))

def kind(p):
    meta=DETAILS.get(p['id'],{});root=(meta.get('category') or [''])[0]
    departments={'Food':'food','Clothing':'apparel','Electronics':'electronics','Baby':'baby','Beauty':'care','Personal Care':'care','Household Essentials':'care','Home':'home','Toys':'standard','Pets':'standard','Auto & Tires':'standard'}
    if root in departments:return departments[root]
    text=(meta.get('type','')+' '+p['name']).lower()
    if re.search(r'\btoy\b|\bplush\b|\bdoll\b|sandwich bags|food storage bags',text):return 'standard'
    for name,pattern in [
        ('apparel',r'jacket|dress\b|jeans|shirt|leggings|pants|sneaker|shoe|hoodie|swimsuit|bra\b|sock'),
        ('electronics',r'laptop|computer|tablet|headphone|earbud|speaker|sound ?bar|television|smartwatch|usb|monitor|camera'),
        ('care',r'body wash|shampoo|moisturizer|cream|serum|soap|detergent|cleaner|lotion|vitamin|tooth|deodorant|medicine'),
        ('food',r'popcorn|chips\b|cereal|coffee|candy|snack|chocolate|oatmeal|protein shake|cookie|juice|milk\b|flour|fruit'),
        ('baby',r'baby|stroller|car seat|diaper|bassinet|crib|toddler'),
        ('home',r'chair|table|sofa|cabinet|bed\b|sheet|blanket|furniture|rug|lamp|pillow|candle|curtain')]:
        if re.search(pattern,text):return name
    return 'standard'

def accordion(title,content,open=False):
    return f'<details class="pdp-accordion" {"open" if open else ""}><summary>{s.esc(title)}</summary><div>{content}</div></details>'

def table(rows):
    return '<dl class="pdp-specs">'+''.join(f'<div><dt>{s.esc(r["name"])}</dt><dd>{s.esc(r["value"])}</dd></div>' for r in rows)+'</dl>'

def related(p,products):
    k=kind(p);tokens=set(re.findall(r'[a-z]{4,}',p['name'].lower()))
    candidates=[x for x in products if x['id']!=p['id'] and kind(x)==k]
    if k=='apparel':
        child=re.search(r'\btoddler|\bbaby|\bkids|\bgirls|\bboys',p['name'].lower())
        candidates=[x for x in candidates if bool(re.search(r'\btoddler|\bbaby|\bkids|\bgirls|\bboys',x['name'].lower()))==bool(child)]
    if k=='standard':candidates=[x for x in candidates if x['category']==p['category']]
    candidates.sort(key=lambda x:(len(tokens&set(re.findall(r'[a-z]{4,}',x['name'].lower()))),x.get('review_count',x.get('reviews',0))),reverse=True)
    return candidates[:18]

def recommendation(title,items):
    if not items:return ''
    return '<section class="pdp-recommend"><h2>'+title+'</h2><p class="pdp-caption">From this preview’s catalog</p>'+s.scroller(''.join(s.product_card(x) for x in items),title,'pdp-related')+'</section>'

def render(p,query,products):
    meta=DETAILS.get(p['id'],{});k=kind(p);enriched=bool(meta)
    counts=meta.get('rating_counts',[])
    if sum(counts):
        p=dict(p, rating=round(sum((5-i)*n for i,n in enumerate(counts))/sum(counts),1), review_count=sum(counts))
    variants=meta.get('variants',{});vid=query.get('option',meta.get('default_variant',''))
    if vid not in variants:vid=meta.get('default_variant','')
    variant=variants.get(vid,{})
    selected=next((o for o in p['options'] if o['option_id']==query.get('option')),p['options'][0])
    price=variant.get('price',p['price_cents']+selected['price_delta_cents'])
    images=variant.get('images') or meta.get('images') or [p['image']]
    category=meta.get('category') or [next((d['name'] for d in s.NAV['departments'] if p['id'] in s.MEMBERS.get(d['name'],[]) and d['id']!='rollbacks-more'),p['category'])]
    department=next((d for d in s.NAV['departments'] if p['id'] in s.MEMBERS.get(d['name'],[]) and d['id']!='rollbacks-more'),s.DEPARTMENTS.get('rollbacks-more'))
    source_department={'Food':'grocery','Clothing':'clothing-shoes-accessories','Electronics':'electronics','Home':'home-garden-tools','Baby':'baby-kids','Beauty':'beauty','Personal Care':'personal-care','Health':'pharmacy-health-wellness','Pets':'pets','Toys':'toys-outdoor-play'}.get(category[0])
    if source_department:department=s.DEPARTMENTS[source_department]
    bread='<a href="/">Home</a> / <a href="/category/'+department['id']+'">'+s.esc(department['name'])+'</a>'
    if meta.get('category'):bread+=' / '+' / '.join(s.esc(x) for x in category[1:])
    thumbs=''.join(f'<button class="pdp-thumb" data-gallery-index="{i}" aria-label="View image {i+1}" aria-pressed="{str(i==0).lower()}">{s.img(im,p["name"]+f", view {i+1}",eager=i<3)}</button>' for i,im in enumerate(images))
    gallery=f'<section class="pdp-gallery" aria-label="Product images"><div class="pdp-thumbnails">{thumbs}</div><div class="pdp-media"><button class="pdp-enlarge" data-zoom aria-label="Enlarge product image">{s.img(images[0],p["name"],eager=True)}</button><div class="pdp-media-tools"><button class="icon-button" data-pdp-share aria-label="Share this item">{s.icon("share",20)}</button><button class="icon-button" data-favorite aria-label="Save item to favorites">{s.icon("heart",20)}</button><button class="icon-button" data-zoom aria-label="Zoom product image">{s.icon("search",20)}</button></div><button class="icon-button pdp-next" data-gallery-next aria-label="Next product image" {"hidden" if len(images)<2 else ""}>{s.icon("right")}</button></div></section>'
    stars=f'<span class="pdp-stars" aria-label="{p["rating"]} out of 5 stars">★★★★★</span><span> ({p["rating"]})</span> <a href="#reviews">{p["review_count"]:,} ratings</a>' if p['rating'] else '<span>No captured ratings</span>'
    title=f'<header class="pdp-title"><a href="/search?brand={quote(meta.get("brand") or p["brand"])}">Visit the {s.esc(meta.get("brand") or p["brand"])} Store</a><h1>{s.esc(p["name"])}</h1><div class="pdp-ratings">{stars}</div></header>'
    options=''
    if variants and meta.get('criteria'):
        for c in meta['criteria']:
            chosen=next((x['name'] for x in c['values'] if x['id'] in variant.get('keys',[])),'Select')
            values=''.join(f'<label class="pdp-swatch {"has-image" if x["image"] else ""}"><input type="radio" data-criterion="{s.esc(c["id"])}" name="criterion-{s.esc(c["id"])}" value="{s.esc(x["id"])}" {"checked" if x["id"] in variant.get("keys",[]) else ""}>{s.img(x["image"],"") if x["image"] else ""}<span>{s.esc(x["name"])}</span></label>' for x in c['values'])
            options+=f'<fieldset class="pdp-criterion"><legend>{s.esc(c["name"])}: <strong data-criterion-label="{s.esc(c["id"])}">{s.esc(chosen)}</strong></legend><div>{values}</div></fieldset>'
        options+=f'<input form="pdp-buy-form" type="hidden" name="option_id" value="{s.esc(vid)}" data-variant-id><p data-variant-status role="status" class="pdp-caption"></p>'
    else:
        required=not enriched and s.BY_ID.get(p['id'],{}).get('requires_options',False) and not query.get('option')
        if len(p['options'])>1 or required:
            options='<fieldset><legend>Choose an option: <strong data-option-label>'+s.esc(selected['label'] if selected['label']!='As shown' else 'Captured configuration')+'</strong></legend><div class="option-grid">'+''.join(f'<label class="option-card"><input form="pdp-buy-form" type="radio" name="option_id" value="{s.esc(o["option_id"])}" data-option-price="{p["price_cents"]+o["price_delta_cents"]}" {"checked" if not required and o["option_id"]==selected["option_id"] else ""} required><span>{s.esc(o["label"] if o["label"]!="As shown" else "Captured configuration")}</span></label>' for o in p['options'])+'</div></fieldset>'
        else:options=f'<input form="pdp-buy-form" type="hidden" name="option_id" value="{s.esc(selected["option_id"])}">'
    options='<section class="pdp-options">'+options+'</section>'
    features=meta.get('features') or [p['name']]
    features_html='<ul>'+''.join('<li>'+s.esc(x)+'</li>' for x in features[:10])+'</ul><a href="#about-item">View all item details</a>'
    sections=meta.get('sections',{})
    highlights=''
    if k=='food' and sections.get('Ingredients'):highlights+=accordion('Ingredients',table(sections['Ingredients']))
    highlights+=accordion('Key item features',features_html,True)
    if meta.get('review_summary'):
        highlights+=accordion('Reviews summary','<ul>'+''.join('<li><b>'+s.esc(a)+'</b> '+s.esc(b)+'</li>' for a,b in meta['review_summary'])+'</ul><p class="pdp-caption">From the captured Walmart review summary.</p>')
    if k=='electronics' and sections.get('Specifications'):highlights+=accordion('Technical specifications',table(sections['Specifications'][:6]),True)
    intro=gallery+'<div class="pdp-summary">'+title+options+'<section class="pdp-highlights">'+highlights+'</section></div>'
    p=dict(p)
    if variant:p['was_cents']=variant.get('was') or None
    was=f'<s data-pdp-was>{s.money(p["was_cents"])}</s>' if p.get('was_cents') and p['was_cents']>price else ''
    save=f'<p class="pdp-saving" data-pdp-saving>You save {s.money(p["was_cents"]-price)}</p>' if was else ''
    methods=''.join(f'<button type="button" data-open="fulfillment" aria-controls="panel-fulfillment" aria-expanded="false">{s.img(s.image_file(key),"")}<b>{name}</b><small>Check availability</small></button>' for name,key in [('Shipping','4be6f532'),('Pickup','333618e2'),('Delivery','c8d39665')])
    source=meta.get('source') or s.BY_ID.get(p['id'],{}).get('source','')
    source_link=f'<a target="_blank" rel="noopener noreferrer" href="{s.esc(source)}">View current offers on Walmart.com</a>' if source.startswith('https://') else ''
    buy=f'''<aside class="pdp-buy"><div class="pdp-buy-sticky"><div class="pdp-buy-card"><div class="pdp-price-line"><strong data-price class="{"sale-price" if was else ""}">{s.money(price)}</strong>{was}</div>{save}<p class="pdp-caption">Price when purchased online</p><form method="post" action="/cart/add" class="buy-form" id="pdp-buy-form"><input type="hidden" name="product_id" value="{s.esc(p['id'])}"><label class="pdp-quantity">Quantity<select name="quantity">{''.join(f'<option>{n}</option>' for n in range(1,5))}</select></label><button class="button primary wide" type="submit" data-pdp-add>Add to cart</button></form><h2>How you’ll get this item:</h2><div class="pdp-methods">{methods}</div><button class="link-button" type="button" data-open="fulfillment" aria-controls="panel-fulfillment" aria-expanded="false">Change delivery method</button><p class="fulfillment" data-availability="{s.esc(p['fulfillment'])}">Select a preview location</p><p class="pdp-caption">Availability shown here is a local preview.</p><hr><div class="pdp-save-links"><button class="link-button" data-favorite>{s.icon('heart',16)} Add to list</button><a href="/info/registries">Add to registry</a></div></div><div class="pdp-offers">{source_link}<p class="pdp-caption">Seller, delivery dates and return terms may change.</p></div><a class="pdp-plus" href="/info/walmart-plus"><b>Walmart+</b> Explore membership benefits</a></div></aside>'''
    description=meta.get('description') or p['description'].split(' The displayed item')[0]
    about='<section id="about-item" class="pdp-about"><h2>About this item</h2>'+accordion('Product details','<p>'+s.esc(description)+'</p>'+('<ul>'+''.join('<li>'+s.esc(x)+'</li>' for x in features)+'</ul>' if enriched else ''))
    specs=sections.get('Specifications') or [{'name':'Brand','value':p['brand']},{'name':'Item','value':p['name']},{'name':'Category','value':category[-1]}]
    about+=accordion('Specifications',table(specs))
    for label,rows in sections.items():
        if label!='Specifications':about+=accordion(label,table(rows))
    if not enriched:about+='<p class="pdp-caption">Additional manufacturer specifications and media were not captured for this item.</p>'
    about+='</section>'
    reviews=render_reviews(p,meta,source)
    recs=related(p,products);a=recommendation('Similar items you might like',recs[:6]);b=recommendation('More in this category',recs[6:12]);c=recommendation('More items to consider',recs[12:18])
    promotions='<section class="pdp-promotions" aria-label="Payment information">'+''.join(f'<a href="{s.esc(x["href"])}" {"target=_blank rel=noopener" if x["href"].startswith("https:") else ""}>{s.img(x["image"],x["title"])}<span><b>{s.esc(x["title"])}</b> {s.esc(x["text"])}</span><u>Learn more</u></a>' for x in PROMOTIONS)+'</section>'
    body=(a+about+b if k=='apparel' else about+a+b)+reviews+promotions+c+'<nav class="pdp-bottom-bread" aria-label="Product category">'+bread+'</nav>'
    payload=json.dumps({'images':images,'variants':variants,'selected':vid,'source':source,'product':p['id']},ensure_ascii=False).replace('<','\\u003c')
    return f'''<link rel="stylesheet" href="/frontend/product-details.css"><script src="/frontend/product-details.js" defer></script><section class="pdp-page pdp-{k}" data-pdp><div class="pdp-layout"><div class="pdp-primary"><div class="pdp-intro">{intro}</div><div class="pdp-body">{body}</div></div>{buy}</div><dialog class="pdp-lightbox" aria-label="Product image viewer"><button class="icon-button" data-zoom-close aria-label="Close image viewer">{s.icon('close')}</button><img alt="{s.esc(p['name'])}"><div><button class="button outline" data-light-step="-1">Previous image</button><span data-light-counter></span><button class="button outline" data-light-step="1">Next image</button></div></dialog><script type="application/json" id="pdp-data">{payload}</script><p class="sr-only" role="status" data-pdp-status></p></section>'''

def render_reviews(p,meta,source):
    rows=meta.get('reviews',[]);rating=p['rating'];counts=meta.get('rating_counts',[]);total=sum(counts)
    summary=f'<div><strong>{rating} out of 5</strong><p class="pdp-stars">★★★★★</p><p>{p["review_count"]:,} ratings</p></div>' if rating else '<p>No captured ratings.</p>'
    if total:summary+='<div class="pdp-rating-bars">'+''.join(f'<button data-review-stars="{5-i}" {"disabled" if not rows else ""}><span>{5-i} stars</span><meter min="0" max="{total}" value="{count}">{count}</meter><span>{round(count/total*100)}% ({count:,})</span></button>' for i,count in enumerate(counts))+'</div>'
    photos=list(dict.fromkeys(im for r in rows for im in r['images']))
    media='<h3>Customer photos</h3><div class="pdp-customer-photos">'+''.join(f'<button data-review-image="{s.esc(im)}" aria-label="Enlarge customer photo {i+1}">{s.img(im,"Customer photo "+str(i+1))}</button>' for i,im in enumerate(photos))+'</div>' if photos else ''
    filters='<div class="pdp-review-filters"><label>Star rating<select data-review-filter><option value="">All ratings</option>'+''.join(f'<option value="{n}">{n} stars</option>' for n in range(5,0,-1))+'</select></label><label>Sort by<select data-review-sort><option value="relevant">Most relevant</option><option value="newest">Newest first</option><option value="high">Highest rating</option><option value="low">Lowest rating</option></select></label></div><p data-review-count role="status"></p>' if rows else ''
    cards=''.join(f'<article class="pdp-review" data-review-rating="{r["rating"]}" data-review-date="{s.esc(r["date"])}"><div><time>{s.esc(r["date"])}</time><p>{s.esc(r["author"] or "Walmart customer")}</p></div><div><span class="pdp-stars" aria-label="{r["rating"]} out of 5 stars">{"★"*r["rating"]}</span><h3>{s.esc(r["title"])}</h3><p>{s.esc(r["text"])}</p><div class="pdp-review-photos">'+''.join(f'<button data-review-image="{im}" aria-label="Enlarge review photo">{s.img(im,"Customer review photo")}</button>' for im in r['images'])+f'</div><a target="_blank" rel="noopener noreferrer" href="{s.esc(source)}">Read full review on Walmart.com</a></div></article>' for r in rows)
    note=f'{len(rows)} review excerpts captured; the source has {meta.get("review_total",len(rows))} written reviews.' if rows else 'Individual reviews and customer photos have not been captured for this item.'
    return '<section id="reviews" class="pdp-reviews"><h2>Customer ratings & reviews</h2><div class="pdp-review-summary">'+summary+'</div>'+media+filters+'<div data-review-list>'+cards+'</div>'+('<button class="button outline" data-reviews-more>View all captured reviews</button>' if len(rows)>3 else '')+'<p class="pdp-caption">'+note+'</p></section>'


