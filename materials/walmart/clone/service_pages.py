"""Service routes backed by separately captured, locally hosted documents."""
import json
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit

def page_for(source):
    p=urlsplit(source);key=urlunsplit((p.scheme,p.netloc,p.path.rstrip('/'),'',''))
    pages=json.loads((Path(__file__).parent/'data/service-pages.json').read_text(encoding='utf-8'))
    return pages.get(key)

def render(source,title):
    import storefront as s
    page=page_for(source)
    if not page:return None
    standalone=' data-standalone' if page['standalone'] else ''
    return f'''<link rel="stylesheet" href="/frontend/service-shell.css"><script src="/frontend/service-shell.js" defer></script><section class="service-shell"{standalone} data-service-page="{page['sourceIndex']}" data-source="{s.esc(source)}"><iframe title="{s.esc(title)}" src="/static/assets/services/{page['file']}" sandbox="allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox allow-top-navigation-by-user-activation" scrolling="no"></iframe></section>'''
