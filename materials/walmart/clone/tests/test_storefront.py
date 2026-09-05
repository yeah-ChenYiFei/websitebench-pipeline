import json
import sys
import unittest
from pathlib import Path
from html.parser import HTMLParser

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import storefront as shop

class Cards(HTMLParser):
    def __init__(self,markup):
        super().__init__(); self.ids=[]; self.feed(markup)
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='article' and attrs.get('data-product-id'):
            self.ids.append(attrs['data-product-id'])

class StorefrontTests(unittest.TestCase):
    def test_every_recorded_menu_entry_has_a_distinct_valid_destination(self):
        self.assertEqual(len(shop.NAV['departments']),20)
        self.assertEqual(len(shop.NAV['services']),12)
        counts={kind:sum(len(g['items']) for d in ds for g in d['groups']) for kind,ds in shop.NAV.items()}
        self.assertEqual(counts,{'departments':282,'services':127})
        for route,entry in shop.ROUTES.items():
            with self.subTest(route=route):
                self.assertFalse(route.endswith('#'))
                if entry['kind']=='departments':
                    page=shop.listing(route,{},shop.CATALOG)
                    self.assertIn('breadcrumbs',page)
                    self.assertTrue(Cards(page).ids)
                    self.assertNotIn('No matching items',page)
                else:
                    page,title=shop.information(route,{})
                    self.assertEqual(title,entry['item']['label'])
                    self.assertIn(shop.esc(entry['item']['source']),page)

    def test_category_isolation_pagination_and_filter_combinations(self):
        for d in shop.NAV['departments']:
            ids=set(shop.MEMBERS[d['name']])
            page=shop.listing('/category/'+d['id'],{},shop.CATALOG)
            shown=Cards(page).ids
            self.assertTrue(shown)
            self.assertTrue(set(shown)<=ids)
            self.assertLessEqual(len(shown),12)
        base='/category/grocery'
        a=Cards(shop.listing(base,{},shop.CATALOG)).ids
        b=Cards(shop.listing(base,{'page':'2'},shop.CATALOG)).ids
        self.assertFalse(set(a)&set(b))
        self.assertEqual(len(set(a+b)),len(shop.MEMBERS['Grocery']))
        product=shop.BY_ID[a[0]]
        query={'brand':product['brand'],'min_price':str(product['price_cents']/100),'max_price':str(product['price_cents']/100),'fulfillment':'Shipping'}
        found=Cards(shop.listing(base,query,shop.CATALOG)).ids
        self.assertIn(product['id'],found)
        self.assertTrue(all(shop.BY_ID[i]['price_cents']==product['price_cents'] for i in found))
        self.assertIn('No matching items',shop.listing(base,{'brand':'no-such-brand'},shop.CATALOG))
        for sort in ('price-low','price-high'):
            ids=Cards(shop.listing(base,{'sort':sort},shop.CATALOG)).ids
            prices=[shop.BY_ID[i]['price_cents'] for i in ids]
            self.assertEqual(prices,sorted(prices,reverse=sort=='price-high'))

    def test_capture_prices_assets_and_suggestions(self):
        # These four sale/regular pairs are independently checked against the
        # source's unified price aria-label, not the visually split dollar spans.
        expected=[(1795,4000),(13885,15885),(3299,5000),(2197,2499)]
        group=shop.HOME['rollbacks'][0]
        self.assertEqual([(shop.BY_ID[i]['price_cents'],shop.BY_ID[i]['was_cents']) for i in group['ids']],expected)
        for product in shop.CATALOG:
            self.assertTrue((ROOT/'static/assets'/product['image']).is_file())
            self.assertGreater(product['price_cents'],0)
            if product['was_cents']:
                self.assertGreaterEqual(product['was_cents'],product['price_cents'])
        self.assertTrue(any(s['kind']=='Department' for s in shop.suggestions('grocery',shop.CATALOG)))
        self.assertTrue(any(s['kind']=='Product' for s in shop.suggestions('body wash',shop.CATALOG)))
        self.assertEqual(shop.suggestions('zzzz-unmatchable',shop.CATALOG),[])
        self.assertEqual(len(shop.HOME['videos']),4)
        self.assertTrue(all(v['video'] for v in shop.HOME['videos']))

    def test_compound_categories_match_alternatives_and_preserve_audiences(self):
        product=lambda name:{'id':'matching-fixture','name':name}
        self.assertTrue(shop.subcategory_matches('Meat & Seafood',product('Fresh Angus Ground Beef')))
        self.assertTrue(shop.subcategory_matches('Meat & Seafood',product('Raw Jumbo Shrimp')))
        self.assertTrue(shop.subcategory_matches('Shoes',product('Toddler Sneakers')))
        self.assertFalse(shop.subcategory_matches('Men',product("Women's Cotton T-shirt")))
        self.assertFalse(shop.subcategory_matches('Alcohol',product('Non-Alcoholic Sparkling Wine')))

    def test_empty_categories_show_parent_recommendations_without_bypassing_filters(self):
        fallbacks=[]
        for path,entry in shop.ROUTES.items():
            if entry['kind']!='departments':continue
            items,recommended=shop.category_products(path,shop.CATALOG)
            self.assertTrue(items,path)
            if recommended:
                fallbacks.append(path)
                parent=set(shop.MEMBERS[entry['department']['name']])
                self.assertTrue({p['id'] for p in items}<=parent)
                self.assertIn('recommended items',shop.listing(path,{},shop.CATALOG))
                filtered=shop.listing(path,{'brand':'no-such-brand'},shop.CATALOG)
                self.assertEqual(Cards(filtered).ids,[])
                self.assertIn('No matching items',filtered)
        self.assertTrue(fallbacks)

if __name__=='__main__':unittest.main()
