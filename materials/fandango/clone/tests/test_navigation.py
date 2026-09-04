"""Stateful navigation additions must preserve actor isolation and server pricing."""
from fastapi.testclient import TestClient
from app import app
from backend import store


def available_product():
    return next((p,v) for p in store.NAV_PRODUCTS.values() for v in p['variants'] if v['available'])


def test_navigation_destinations_return_success_on_direct_load():
    with TestClient(app) as client:
        for route in ['/fanstore','/fanstore/collections/all','/fanstore/cart','/streaming','/streaming/library','/movie-news','/theaters?zip=90001']:
            response=client.get(route)
            assert response.status_code==200
            assert 'navigation.js' in response.text


def test_cart_is_persisted_and_actor_isolated():
    product,variant=available_product()
    with TestClient(app) as first, TestClient(app) as second:
        first.get('/api/navigation/state')
        response=first.post('/api/navigation/state',json={'kind':'cart','product':product['id'],'variant':variant['id'],'quantity':2,'price':0.01})
        assert response.status_code==200
        assert response.json()['subtotal']==round(variant['price']*2,2)
        assert first.get('/api/navigation/state').json()['cart'][0]['quantity']==2
        assert second.get('/api/navigation/state').json()['cart']==[]
        response=first.post('/api/navigation/state',json={'kind':'cart','product':product['id'],'variant':variant['id'],'quantity':0})
        assert response.json()['cart']==[]


def test_cart_rejects_invalid_quantity_and_foreign_variant():
    product,variant=available_product()
    with TestClient(app) as client:
        for quantity in [-1,100,1.5,True,'2']:
            assert client.post('/api/navigation/state',json={'kind':'cart','product':product['id'],'variant':variant['id'],'quantity':quantity}).status_code==422
        assert client.post('/api/navigation/state',json={'kind':'cart','product':product['id'],'variant':'foreign','quantity':1}).status_code==422


def test_sold_out_variant_cannot_be_added():
    product,variant=next((p,v) for p in store.NAV_PRODUCTS.values() for v in p['variants'] if not v['available'])
    with TestClient(app) as client:
        assert client.post('/api/navigation/state',json={'kind':'cart','product':product['id'],'variant':variant['id'],'quantity':1}).status_code==422


def test_different_product_options_remain_distinct_in_cart():
    product=next(p for p in store.NAV_PRODUCTS.values() if sum(v['available'] for v in p['variants'])>1)
    variants=[v for v in product['variants'] if v['available']][:2]
    with TestClient(app) as client:
        client.get('/api/navigation/state')
        for variant in variants:
            response=client.post('/api/navigation/state',json={'kind':'cart','product':product['id'],'variant':variant['id'],'quantity':1})
            assert response.status_code==200
        cart=response.json()
        assert {line['variant'] for line in cart['cart']}=={v['id'] for v in variants}
        assert cart['subtotal']==round(sum(v['price'] for v in variants),2)


def test_saved_lists_toggle_and_reject_unknown_records():
    with TestClient(app) as client:
        client.get('/api/navigation/state')
        for kind,key in [('theaters','theaters'),('library','streaming')]:
            item=store.NAV_CATALOG[key][0]
            assert item in client.post('/api/navigation/state',json={'kind':kind,'id':item}).json()[kind]
            assert item not in client.post('/api/navigation/state',json={'kind':kind,'id':item}).json()[kind]
            assert client.post('/api/navigation/state',json={'kind':kind,'id':'unknown'}).status_code==422
