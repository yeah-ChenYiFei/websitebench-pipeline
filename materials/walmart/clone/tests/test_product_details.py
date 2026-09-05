import json,sqlite3,unittest
import product_details as pd
from backend.walmart_backend import PRODUCTS,migrate_details_v4

class ProductDetailTests(unittest.TestCase):
 def product(self,pid):
  p=dict(next(p for p in PRODUCTS if p['id']==pid));p['review_count']=p['reviews'];p['options']=[{'option_id':id,'label':label,'price_delta_cents':delta} for id,label,delta in p['options']];return p
 def test_every_product_has_one_purchase_region_and_correct_identity(self):
  for product in PRODUCTS:
   with self.subTest(id=product['id']):
    p=self.product(product['id']);html=pd.render(p,{},PRODUCTS)
    self.assertEqual(html.count('class="pdp-buy"'),1)
    self.assertIn(pd.s.esc(p['name']),html)
    self.assertIn('id="pdp-buy-form"',html)
    self.assertNotIn('Everyday low price</li>',html)
 def test_food_and_apparel_have_distinct_sections(self):
  food=self.product('wm-14709803648');apparel=self.product('wm-18202305889')
  a=pd.render(food,{},PRODUCTS);b=pd.render(apparel,{},PRODUCTS)
  self.assertIn('Ingredients',a);self.assertNotIn('data-criterion=',a);self.assertNotIn('As shown',a)
  self.assertIn('Actual Color',b);self.assertIn('Clothing Size',b);self.assertIn('Fabric Care Instructions',b);self.assertNotIn('<summary>Ingredients</summary>',b)
  self.assertLess(b.index('Similar items you might like'),b.index('id="about-item"'))
  self.assertLess(a.index('id="about-item"'),a.index('Similar items you might like'))
 def test_captured_variants_seed_correct_prices_and_exclude_unavailable(self):
  db=sqlite3.connect(':memory:');migrate_details_v4(db)
  for pid,meta in pd.DETAILS.items():
   for vid,v in meta['variants'].items():
    row=db.execute('SELECT p.price_cents+o.price_delta_cents FROM wb_walmart_product_options o JOIN wb_walmart_products p ON p.id=o.product_id WHERE o.product_id=? AND o.option_id=?',(pid,vid)).fetchone()
    if v['available']:self.assertEqual(row[0],v['price'])
    else:self.assertIsNone(row)
  self.assertIsNotNone(db.execute("SELECT 1 FROM wb_walmart_product_options WHERE product_id='wm-18202305889' AND option_id='captured'").fetchone())
  db.close()
 def test_official_food_category_and_toy_description_do_not_use_clothing_layout(self):
  self.assertEqual(pd.kind(self.product('wm-10291616')),'food')
  self.assertEqual(pd.kind({'id':'uncaptured-toy','name':'Disney soft toy in an embroidered red T-shirt'}),'standard')
  jacket=self.product('wm-18202305889')
  self.assertTrue(all(pd.kind(p)=='apparel' for p in pd.related(jacket,PRODUCTS)))
