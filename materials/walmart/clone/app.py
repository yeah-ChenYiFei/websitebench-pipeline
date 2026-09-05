#!/usr/bin/env python3
"""Local-only Walmart shopping-flow clone."""

from __future__ import annotations

import argparse
import html
import json
import mimetypes
import os
import re
import secrets
import sys
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse

from backend.site_backend_integration import open_site_services
from websitebench.local_clone_auth import AuthConflict, AuthError, AuthRejected, AuthValidationError
import storefront
import product_details


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "static"
FRONTEND_ROOT = ROOT / "frontend"
if os.environ.get("DATA_DIR") and not os.environ.get("WEBSITEBENCH_SITE_BACKEND_DATABASE"):
    os.environ["WEBSITEBENCH_SITE_BACKEND_DATABASE"] = str(
        Path(os.environ["DATA_DIR"]).resolve() / "walmart.sqlite3"
    )
BACKEND, _AUTH = open_site_services()
CART_COOKIE = "wb_walmart_cart"
AUTH_COOKIE = "wb_walmart_auth"


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def item_count_label(count: int) -> str:
    return f"{count} {'item' if count == 1 else 'items'}"


def fetch_products(*, query: str = "", brand: str = "", fulfillment: str = "", category: str = "", sort: str = "best", min_cents: int | None = None, max_cents: int | None = None) -> list[dict]:
    sql = "SELECT * FROM wb_walmart_products WHERE 1=1"
    params: list[object] = []
    if query:
        sql += " AND (lower(name) LIKE ? OR lower(brand) LIKE ? OR lower(category) LIKE ?)"
        term = f"%{query.lower()}%"
        params.extend((term, term, term))
    if brand:
        sql += " AND lower(brand) = lower(?)"
        params.append(brand)
    if fulfillment:
        sql += " AND lower(fulfillment) LIKE ?"
        params.append(f"%{fulfillment.lower()}%")
    if category:
        sql += " AND lower(category) = lower(?)"
        params.append(category)
    if min_cents is not None:
        sql += " AND price_cents >= ?"
        params.append(min_cents)
    if max_cents is not None:
        sql += " AND price_cents <= ?"
        params.append(max_cents)
    order = {
        "price-low": "price_cents ASC, name ASC",
        "price-high": "price_cents DESC, name ASC",
        "rating": "rating DESC, review_count DESC",
        "best": "CASE WHEN badges <> '' THEN 0 ELSE 1 END, rating DESC, name ASC",
    }.get(sort, "rating DESC, name ASC")
    sql += f" ORDER BY {order}"
    with BACKEND.lifecycle.connection() as connection:
        return [dict(row) for row in connection.execute(sql, params).fetchall()]


def fetch_product(*, slug: str = "", product_id: str = "") -> dict | None:
    key, value = ("slug", slug) if slug else ("id", product_id)
    with BACKEND.lifecycle.connection() as connection:
        row = connection.execute(f"SELECT * FROM wb_walmart_products WHERE {key} = ?", (value,)).fetchone()
        if row is None:
            return None
        product = dict(row)
        product["options"] = [dict(item) for item in connection.execute(
            "SELECT * FROM wb_walmart_product_options WHERE product_id = ? ORDER BY rowid",
            (product["id"],),
        ).fetchall()]
        return product


def cart_lines(cart_id: str) -> list[dict]:
    with BACKEND.lifecycle.connection() as connection:
        lines = [dict(row) for row in connection.execute(
            """
            SELECT c.product_id, c.option_id, c.quantity, p.slug, p.name, p.image,
                   p.price_cents + o.price_delta_cents AS unit_cents, o.label AS option_label
              FROM wb_walmart_carts c
              JOIN wb_walmart_products p ON p.id = c.product_id
              JOIN wb_walmart_product_options o
                ON o.product_id = c.product_id AND o.option_id = c.option_id
             WHERE c.cart_id = ?
             ORDER BY c.updated_at DESC, p.name
            """,
            (cart_id,),
        ).fetchall()]
    for line in lines:
        variant = product_details.DETAILS.get(line['product_id'], {}).get('variants', {}).get(line['option_id'], {})
        if variant.get('images'):
            line['image'] = variant['images'][0]
    return lines


def cart_summary(cart_id: str) -> tuple[int, int]:
    lines = cart_lines(cart_id)
    return sum(line["quantity"] for line in lines), sum(line["quantity"] * line["unit_cents"] for line in lines)


def logo() -> str:
    rays = "".join(f'<i style="--r:{index}"></i>' for index in range(6))
    return f'<span class="wordmark">Walmart</span><span class="spark" aria-hidden="true">{rays}</span>'


def product_card(product: dict) -> str:
    detailed = fetch_product(product_id=product['id'])
    return storefront.product_card(detailed)


class WalmartHandler(BaseHTTPRequestHandler):
    server_version = "WebsiteBenchWalmart/1.0"

    def log_message(self, format: str, *args: object) -> None:
        sys.stderr.write(f"[walmart] {self.address_string()} {format % args}\n")

    def _cart_id(self) -> tuple[str, bool]:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        value = cookie.get(CART_COOKIE)
        if value and re.fullmatch(r"[a-f0-9]{32}", value.value):
            return value.value, False
        return secrets.token_hex(16), True

    def _start_auth_session(self) -> None:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        supplied = cookie.get(AUTH_COOKIE)
        token, session = _AUTH.ensure_session(supplied.value if supplied else None)
        self.auth_token = token
        self.auth_session = session
        self.auth_cookie_changed = supplied is None or supplied.value != token

    def _use_auth_token(self, token: str) -> None:
        self.auth_token = token
        self.auth_session = _AUTH.resolve_session(token) or {"authenticated": False, "account": None}
        self.auth_cookie_changed = True

    @property
    def account(self) -> dict | None:
        return self.auth_session.get("account") if self.auth_session.get("authenticated") else None

    def _security_headers(self) -> None:
        service_document=bool(re.fullmatch(r'/static/assets/services/page-\d+\.html',urlparse(self.path).path))
        ancestors="'self'" if service_document else "'none'"
        self.send_header("Content-Security-Policy", f"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; font-src 'self' data:; connect-src 'self'; frame-ancestors {ancestors}; form-action 'self'; base-uri 'self'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN" if service_document else "DENY")

    def _send(self, status: int, body: bytes, content_type: str, *, cart_id: str | None = None, new_cart: bool = False) -> None:
        self.send_response(status)
        self._security_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if cart_id and new_cart:
            self.send_header("Set-Cookie", f"{CART_COOKIE}={cart_id}; Path=/; HttpOnly; SameSite=Lax")
        if getattr(self, "auth_cookie_changed", False):
            self.send_header("Set-Cookie", f"{AUTH_COOKIE}={self.auth_token}; Path=/; HttpOnly; SameSite=Lax")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _html(self, content: str, *, title: str, status: int = 200, cart_id: str, new_cart: bool, search_value: str = "", document_title: str | None = None) -> None:
        count, subtotal = cart_summary(cart_id)
        page = storefront.shell(content, document_title or f'{title} - Walmart', count, subtotal, search_value, self.account)
        self._send(status, page.encode(), "text/html; charset=utf-8", cart_id=cart_id, new_cart=new_cart)

    def _redirect(self, location: str, *, cart_id: str, new_cart: bool) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self._security_headers()
        self.send_header("Location", location)
        if new_cart:
            self.send_header("Set-Cookie", f"{CART_COOKIE}={cart_id}; Path=/; HttpOnly; SameSite=Lax")
        if getattr(self, "auth_cookie_changed", False):
            self.send_header("Set-Cookie", f"{AUTH_COOKIE}={self.auth_token}; Path=/; HttpOnly; SameSite=Lax")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _serve_file(self, path: Path) -> None:
        resolved = path.resolve()
        if not resolved.is_file() or not (resolved.is_relative_to(STATIC_ROOT) or resolved.is_relative_to(FRONTEND_ROOT)):
            self.send_error(404)
            return
        mime = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
        byte_range = self.headers.get('Range', '')
        match = re.fullmatch(r'bytes=(\d+)-(\d*)', byte_range)
        if match and mime.startswith('video/'):
            size = resolved.stat().st_size
            start = int(match[1])
            end = min(int(match[2]) if match[2] else size - 1, size - 1)
            if start >= size or start > end:
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            self.send_response(206)
            self._security_headers()
            self.send_header('Content-Type', mime)
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
            self.send_header('Content-Length', str(end-start+1))
            self.end_headers()
            if self.command != 'HEAD':
                with resolved.open('rb') as stream:
                    stream.seek(start)
                    self.wfile.write(stream.read(end-start+1))
            return
        self._send(200, resolved.read_bytes(), mime)

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = {key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
        self._start_auth_session()
        cart_id, new_cart = self._cart_id()
        if path == "/__websitebench/health":
            body = b'{"status":"ok"}'
            self._send(200, body, "application/json; charset=utf-8", cart_id=cart_id, new_cart=new_cart)
            return
        if path == "/api/cart":
            lines = cart_lines(cart_id)
            count, subtotal = cart_summary(cart_id)
            body = json.dumps({"cart_count": count, "subtotal_cents": subtotal, "lines": [{"product_id": line["product_id"], "option_id": line["option_id"], "quantity": line["quantity"]} for line in lines]}).encode()
            self._send(200, body, "application/json; charset=utf-8", cart_id=cart_id, new_cart=new_cart)
            return
        if path == "/api/checkout/review":
            count, subtotal = cart_summary(cart_id)
            status = 200 if count else 422
            body = json.dumps({"state": "ready" if count and self.account else "sign-in-required" if count else "empty", "cart_count": count, "subtotal_cents": subtotal, "can_submit_order": bool(count and self.account), "payment_fields": []}).encode()
            self._send(status, body, "application/json; charset=utf-8", cart_id=cart_id, new_cart=new_cart)
            return
        if path.startswith("/static/"):
            self._serve_file(STATIC_ROOT / path.removeprefix("/static/"))
            return
        if path.startswith("/frontend/"):
            self._serve_file(FRONTEND_ROOT / path.removeprefix("/frontend/"))
            return
        if path == '/api/search-suggestions':
            results = storefront.suggestions(query.get('q', ''), fetch_products())
            self._send(200, json.dumps(results).encode(), 'application/json; charset=utf-8', cart_id=cart_id, new_cart=new_cart)
            return
        if path == '/':
            self._html(storefront.homepage(), title='Save Money. Live Better', document_title='Walmart | Save Money. Live better.', cart_id=cart_id, new_cart=new_cart)
            return
        if path == '/all-departments':
            self._html(storefront.all_departments(), title='All Departments', cart_id=cart_id, new_cart=new_cart)
            return
        if path == '/search' or path in storefront.COLLECTIONS or (path.startswith('/category/') and (path in storefront.ROUTES or path.split('/')[2] in storefront.DEPARTMENTS and path.count('/') == 2)):
            self._html(storefront.listing(path, query, fetch_products()), title='Browse products', search_value=query.get('q',''), cart_id=cart_id, new_cart=new_cart)
            return
        if path.startswith('/info/') or path in storefront.ROUTES and storefront.ROUTES[path]['kind'] == 'services':
            content, title = storefront.information(path, query)
            self._html(content, title=title, cart_id=cart_id, new_cart=new_cart)
            return
        if path.startswith("/product/"):
            product = fetch_product(slug=path.rsplit("/", 1)[-1])
            if product:
                content = product_details.render(product, query, fetch_products())
                self._html(content, title=product["name"], cart_id=cart_id, new_cart=new_cart)
                return
        if path == "/cart":
            lines = cart_lines(cart_id)
            if not lines:
                content = f"""<section class="page-section narrow empty-cart">{storefront.icon("cart",64)}<h1>Your cart is empty</h1><p>Time to fill it up with everyday essentials.</p><a class="button primary" href="/search?q=dish+soap">Start shopping</a></section>"""
            else:
                items = "".join(self._cart_line(line) for line in lines)
                count, subtotal = cart_summary(cart_id)
                content = f"""<section class="page-section"><p class="breadcrumbs"><a href="/">Home</a> / Cart</p><h1>Cart <span class="muted">({item_count_label(count)})</span></h1><div class="cart-layout"><div class="cart-items">{items}</div><aside class="summary"><div class="savings">Pickup and delivery options available</div><div><span>Subtotal ({item_count_label(count)})</span><strong>{money(subtotal)}</strong></div><div><span>Taxes</span><span>Calculated at review</span></div><hr><div class="total"><span>Estimated total</span><strong>{money(subtotal)}</strong></div><a class="button primary wide" href="/checkout/review">Continue to checkout</a><p class="safe-note">Sign in to place a local preview order. No real payment is charged.</p></aside></div></section>"""
            self._html(content, title="Cart", cart_id=cart_id, new_cart=new_cart)
            return
        if path == "/checkout/review":
            self._checkout(cart_id=cart_id, new_cart=new_cart, zip_value=query.get("zip", ""), reviewed=query.get("reviewed") == "1")
            return
        if path == "/account-entry":
            self._account_page(cart_id=cart_id, new_cart=new_cart, query=query)
            return
        if path == "/order-confirmation":
            self._order_confirmation(cart_id=cart_id, new_cart=new_cart, order_id=query.get("id", ""))
            return
        if path == "/help":
            content = """<section class="help-hero"><h1>Walmart Help Center</h1><form action="/help" role="search"><label class="sr-only" for="help-search">Search help</label><input id="help-search" name="q" placeholder="Search help articles"><button aria-label="Search help">⌕</button></form></section><section class="page-section narrow"><h2>How can we help?</h2><div class="help-grid"><article>{storefront.icon("cart",64)}<h3>Shopping & cart</h3><p>Find items, choose options, and update your cart.</p></article><article><span>📦</span><h3>Pickup & delivery</h3><p>Review the fulfillment labels shown on product pages.</p></article><article><span>↩</span><h3>Returns</h3><p>Orders and returns are unavailable in this shopping preview.</p></article></div><a href="/">Return to home</a></section>"""
            self._html(content, title="Help Center", cart_id=cart_id, new_cart=new_cart)
            return
        if path == "/privacy":
            content = """<section class="page-section narrow boundary-page"><h1>Privacy choices</h1><div class="notice"><strong>This feature is not available.</strong><p>Privacy submissions are not included in this shopping preview.</p></div><a class="button primary" href="/">Return to home</a></section>"""
            self._html(content, title="Privacy choices", cart_id=cart_id, new_cart=new_cart)
            return
        content = """<section class="page-section narrow not-found"><span>404</span><h1>We couldn't find that page</h1><p>The link may be broken, or the page may have moved.</p><a class="button primary" href="/">Go to Walmart home</a><a href="/all-departments">Browse all departments</a></section>"""
        self._html(content, title="Page not found", status=404, cart_id=cart_id, new_cart=new_cart)

    def _cart_line(self, line: dict) -> str:
        return f"""<article class="cart-item"><a href="/product/{esc(line['slug'])}"><img src="/static/assets/{esc(line['image'])}" alt="{esc(line['name'])}"></a><div><a class="product-name" href="/product/{esc(line['slug'])}">{esc(line['name'])}</a><p>{esc(line['option_label'])}</p><p class="fulfillment" data-availability="Shipping|Pickup|Delivery">Preview availability</p><div class="cart-actions"><form method="post" action="/cart/update"><input type="hidden" name="product_id" value="{esc(line['product_id'])}"><input type="hidden" name="option_id" value="{esc(line['option_id'])}"><label>Qty <select name="quantity">{''.join(f'<option {"selected" if n==line["quantity"] else ""}>{n}</option>' for n in range(1, 21))}</select></label><button type="submit" class="link-button">Update</button></form><form method="post" action="/cart/remove"><input type="hidden" name="product_id" value="{esc(line['product_id'])}"><input type="hidden" name="option_id" value="{esc(line['option_id'])}"><button type="submit" class="link-button">Remove</button></form></div></div><strong>{money(line['unit_cents'] * line['quantity'])}</strong></article>"""

    @staticmethod
    def _safe_next(value: str) -> str:
        return value if value.startswith('/') and not value.startswith('//') else '/'

    def _account_page(self, *, cart_id: str, new_cart: bool, query: dict[str, str], error: str = "", values: dict[str, str] | None = None) -> None:
        values = values or {}
        next_path = self._safe_next(query.get('next', '/'))
        error_html = f'<p class="field-error" role="alert">{esc(error)}</p>' if error else ''
        if self.account:
            if query.get('view') == 'purchases':
                with BACKEND.lifecycle.connection() as connection:
                    orders = connection.execute("SELECT * FROM wb_walmart_orders WHERE account_id=? ORDER BY created_at DESC", (self.account['account_id'],)).fetchall()
                cards = ''.join(f'''<a class="order-card" href="/order-confirmation?id={esc(row['order_id'])}"><span><b>Order {esc(row['order_id'])}</b><small>{esc(row['created_at'])} · {esc(row['status'])}</small></span><strong>{money(row['total_cents'])}</strong></a>''' for row in orders)
                content = f'''<section class="page-section narrow account-page"><a href="/account-entry">← Account</a><h1>Purchase history</h1>{cards or '<div class="notice"><p>You have no local orders yet.</p></div>'}</section>'''
            else:
                content = f'''<section class="page-section narrow account-page"><h1>Welcome, {esc(self.account['display_name'])}</h1><p>{esc(self.account['email_normalized'])}</p><div class="account-links"><a class="order-card" href="/account-entry?view=purchases"><span><b>Purchase history</b><small>View orders placed in this local preview</small></span>›</a><a class="order-card" href="/cart"><span><b>Cart</b><small>Continue shopping or checkout</small></span>›</a></div><form method="post" action="/account/logout"><button class="button outline" type="submit">Sign out</button></form></section>'''
            self._html(content, title="Account", cart_id=cart_id, new_cart=new_cart)
            return
        if query.get('verify') == '1':
            mail = _AUTH.local_mail_for_session(self.auth_token, purpose='registration')
            if mail is None:
                self._redirect('/account-entry?mode=register', cart_id=cart_id, new_cart=new_cart)
                return
            content = f'''<section class="page-section narrow auth-page"><div class="auth-card"><h1>Verify your email</h1><p>This preview does not send email. Use the local verification code below.</p><div class="local-code"><small>Local verification code</small><strong>{esc(mail['verification_code'])}</strong></div>{error_html}<form method="post" action="/account/verify"><input type="hidden" name="next" value="{esc(next_path)}"><label for="code">6-digit code</label><input id="code" name="code" inputmode="numeric" pattern="[0-9]{{6}}" maxlength="6" required autocomplete="one-time-code"><button class="button primary wide" type="submit">Verify and create account</button></form></div></section>'''
        elif query.get('mode') == 'register':
            content = f'''<section class="page-section narrow auth-page"><div class="auth-card"><h1>Create your account</h1><p>Use an email and password for this local Walmart preview.</p>{error_html}<form method="post" action="/account/register"><input type="hidden" name="next" value="{esc(next_path)}"><label for="display-name">First and last name</label><input id="display-name" name="display_name" value="{esc(values.get('display_name',''))}" required maxlength="120" autocomplete="name"><label for="register-email">Email address</label><input id="register-email" name="email" type="email" value="{esc(values.get('email',''))}" required autocomplete="email"><label for="register-password">Password</label><input id="register-password" name="password" type="password" required minlength="8" maxlength="128" autocomplete="new-password"><small>Use 8 to 128 characters.</small><button class="button primary wide" type="submit">Create account</button></form><p>Already have an account? <a href="/account-entry">Sign in</a></p></div></section>'''
        else:
            content = f'''<section class="page-section narrow auth-page"><div class="auth-card"><h1>Sign in to your account</h1><p>Use the local account created for this shopping preview.</p>{error_html}<form method="post" action="/account/login"><input type="hidden" name="next" value="{esc(next_path)}"><label for="login-email">Email address</label><input id="login-email" name="email" type="email" value="{esc(values.get('email',''))}" required autocomplete="email"><label for="login-password">Password</label><input id="login-password" name="password" type="password" required autocomplete="current-password"><button class="button primary wide" type="submit">Sign in</button></form><p>New to this preview? <a href="/account-entry?mode=register&amp;next={quote(next_path)}">Create an account</a></p></div></section>'''
        self._html(content, title="Account", cart_id=cart_id, new_cart=new_cart)

    def _order_confirmation(self, *, cart_id: str, new_cart: bool, order_id: str) -> None:
        if not self.account:
            self._redirect('/account-entry?next=/account-entry%3Fview%3Dpurchases', cart_id=cart_id, new_cart=new_cart)
            return
        with BACKEND.lifecycle.connection() as connection:
            order = connection.execute("SELECT * FROM wb_walmart_orders WHERE order_id=? AND account_id=?", (order_id, self.account['account_id'])).fetchone()
            items = connection.execute("SELECT * FROM wb_walmart_order_items WHERE order_id=?", (order_id,)).fetchall() if order else []
        if order is None:
            self._html('<section class="page-section narrow not-found"><h1>Order not found</h1><a href="/account-entry?view=purchases">View purchase history</a></section>', title="Order not found", status=404, cart_id=cart_id, new_cart=new_cart)
            return
        rows = ''.join(f'''<li><img src="/static/assets/{esc(row['image'])}" alt=""><span>{row['quantity']} × {esc(row['product_name'])}<small>{esc(row['option_label'])}</small></span><strong>{money(row['quantity'] * row['unit_cents'])}</strong></li>''' for row in items)
        content = f'''<section class="checkout-shell confirmation"><div class="confirmation-check">✓</div><h1>Thanks, {esc(self.account['display_name'])}!</h1><p>Your local order <strong>{esc(order_id)}</strong> has been placed.</p><div class="review-banner"><strong>Local preview order</strong><p>No charge was made and nothing was submitted to Walmart.</p></div><section class="review-section"><h2>Pickup</h2><p>Sacramento Supercenter · ZIP {esc(order['zip_code'])}</p></section><section class="review-section"><h2>Items</h2><ul class="review-items">{rows}</ul></section><aside class="summary order-total"><div><span>Subtotal</span><strong>{money(order['subtotal_cents'])}</strong></div><div><span>Tax</span><strong>{money(order['tax_cents'])}</strong></div><hr><div class="total"><span>Total</span><strong>{money(order['total_cents'])}</strong></div></aside><a class="button primary" href="/">Continue shopping</a> <a class="button outline" href="/account-entry?view=purchases">Purchase history</a></section>'''
        self._html(content, title="Order confirmation", cart_id=cart_id, new_cart=new_cart)

    def _checkout(self, *, cart_id: str, new_cart: bool, zip_value: str = "", reviewed: bool = False, error: str = "") -> None:
        lines = cart_lines(cart_id)
        if not lines:
            content = """<section class="page-section narrow empty-cart"><h1>Your cart is empty</h1><p>Add an item before continuing to checkout review.</p><a class="button primary" href="/search?q=dish+soap">Start shopping</a></section>"""
            self._html(content, title="Checkout review", cart_id=cart_id, new_cart=new_cart)
            return
        if not self.account:
            self._redirect('/account-entry?next=/checkout/review', cart_id=cart_id, new_cart=new_cart)
            return
        count, subtotal = cart_summary(cart_id)
        if not reviewed:
            error_html = f'<p class="field-error" id="zip-error">{esc(error)}</p>' if error else ""
            content = f"""<section class="checkout-shell"><header><a href="/" class="checkout-logo">{logo()}</a><span>Secure review</span></header><div class="checkout-layout"><div><p class="step">Step 1 of 2</p><h1>How would you like to get your order?</h1><div class="method-card selected"><b data-method-label>Pickup</b><span>Preview availability</span><p data-store>Sacramento Supercenter</p></div><h2>Confirm your ZIP code</h2><form method="post" action="/checkout/review" class="zip-form" novalidate><label for="zip">ZIP code</label><input id="zip" name="zip" inputmode="numeric" maxlength="5" value="{esc(zip_value)}" aria-describedby="zip-help {"zip-error" if error else ""}" aria-invalid="{str(bool(error)).lower()}"><small id="zip-help">Use a 5-digit US ZIP code to show this review.</small>{error_html}<button class="button primary" type="submit">Review order</button></form></div><aside class="summary"><h2>Order summary</h2><div><span>Subtotal ({item_count_label(count)})</span><strong>{money(subtotal)}</strong></div><div><span>Taxes</span><span>Calculated next</span></div><hr><div class="total"><span>Estimated total</span><strong>{money(subtotal)}</strong></div></aside></div></section>"""
        else:
            item_rows = "".join(f'<li><img src="/static/assets/{esc(line["image"])}" alt=""><span>{line["quantity"]} × {esc(line["name"])}<small>{esc(line["option_label"])}</small></span><strong>{money(line["quantity"] * line["unit_cents"])}</strong></li>' for line in lines)
            tax = round(subtotal * 0.0775)
            content = f"""<section class="checkout-shell"><header><a href="/" class="checkout-logo">{logo()}</a><span>Secure checkout</span></header><div class="checkout-layout"><div><p class="step">Step 2 of 2</p><h1>Review your order</h1><div class="review-banner"><strong>Local preview checkout</strong><p>Placing this order records it only on this device. No payment is charged or sent to Walmart.</p></div><section class="review-section"><h2 data-method-label>Pickup</h2><p><strong>Ready for local checkout</strong><br><span data-store>Sacramento Supercenter</span> · ZIP {esc(zip_value)}</p><a href="/checkout/review">Change</a></section><section class="review-section"><h2>{'Item' if count == 1 else 'Items'} ({count})</h2><ul class="review-items">{item_rows}</ul></section></div><aside class="summary"><h2>Order summary</h2><div><span>Subtotal</span><strong>{money(subtotal)}</strong></div><div><span>Tax (7.75%)</span><strong>{money(tax)}</strong></div><hr><div class="total"><span>Total</span><strong>{money(subtotal + tax)}</strong></div><form method="post" action="/checkout/place"><input type="hidden" name="zip" value="{esc(zip_value)}"><button type="submit" class="button primary wide">Place order</button></form><p class="safe-note">This creates a local test order and clears your cart. No payment details are collected.</p><a href="/cart">Return to cart</a></aside></div></section>"""
        self._html(content, title="Review your order", cart_id=cart_id, new_cart=new_cart)

    def _form(self) -> dict[str, str]:
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 65536)
        except ValueError:
            length = 0
        return {key: values[-1] for key, values in parse_qs(self.rfile.read(length).decode("utf-8", "replace"), keep_blank_values=True).items()}

    def _json_body(self) -> dict:
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 65536)
        except ValueError:
            length = 0
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8", "replace"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        self._start_auth_session()
        cart_id, new_cart = self._cart_id()
        if path == "/api/cart/items":
            payload = self._json_body()
            if "owner" in payload:
                body = json.dumps({"error": "owner is server-bound"}).encode()
                self._send(403, body, "application/json; charset=utf-8", cart_id=cart_id, new_cart=new_cart)
                return
            product = fetch_product(product_id=payload.get("product_id", "") if isinstance(payload.get("product_id", ""), str) else "")
            option_id = payload.get("option_id", "")
            quantity = payload.get("quantity", 1)
            option = next((item for item in product["options"] if item["option_id"] == option_id), None) if product else None
            if product is None or option is None or isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= 20:
                body = json.dumps({"error": "valid product, option, and quantity 1..20 are required"}).encode()
                self._send(422, body, "application/json; charset=utf-8", cart_id=cart_id, new_cart=new_cart)
                return
            with BACKEND.lifecycle.connection(transaction=True) as connection:
                connection.execute(
                    """INSERT INTO wb_walmart_carts(cart_id, product_id, option_id, quantity)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(cart_id, product_id, option_id) DO UPDATE SET
                         quantity = MIN(20, quantity + excluded.quantity), updated_at=CURRENT_TIMESTAMP""",
                    (cart_id, product["id"], option["option_id"], quantity),
                )
            count, subtotal = cart_summary(cart_id)
            body = json.dumps({"cart_count": count, "subtotal_cents": subtotal, "state": "populated"}).encode()
            self._send(201, body, "application/json; charset=utf-8", cart_id=cart_id, new_cart=new_cart)
            return
        form = self._form()
        if path == "/__websitebench/reset":
            def reset_local_state(connection):
                BACKEND.lifecycle.reset_embedded(connection, confirm_site_id="walmart")
                connection.execute("DELETE FROM wb_walmart_carts")
                connection.execute("DELETE FROM wb_walmart_orders")
            _AUTH.reset_site_state(site_reset=reset_local_state, seed_accounts=[])
            token, _ = _AUTH.ensure_session(None)
            self._use_auth_token(token)
            self._redirect("/", cart_id=cart_id, new_cart=new_cart)
            return
        if path == "/account/register":
            next_path = self._safe_next(form.get('next', '/'))
            values = {'display_name': form.get('display_name', ''), 'email': form.get('email', '')}
            try:
                _AUTH.start_registration(self.auth_token, email=values['email'], display_name=values['display_name'], password=form.get('password', ''))
            except AuthConflict:
                self._account_page(cart_id=cart_id, new_cart=new_cart, query={'mode': 'register', 'next': next_path}, error='An account with that email already exists.', values=values)
                return
            except AuthError as error:
                self._account_page(cart_id=cart_id, new_cart=new_cart, query={'mode': 'register', 'next': next_path}, error=str(error), values=values)
                return
            self._redirect(f"/account-entry?verify=1&next={quote(next_path, safe='')}", cart_id=cart_id, new_cart=new_cart)
            return
        if path == "/account/verify":
            next_path = self._safe_next(form.get('next', '/'))
            try:
                _AUTH.verify_registration_code(self.auth_token, form.get('code', ''))
                result = _AUTH.complete_registration(self.auth_token)
            except AuthError as error:
                self._account_page(cart_id=cart_id, new_cart=new_cart, query={'verify': '1', 'next': next_path}, error=str(error))
                return
            self._use_auth_token(result['session_token'])
            self._redirect(next_path, cart_id=cart_id, new_cart=new_cart)
            return
        if path == "/account/login":
            next_path = self._safe_next(form.get('next', '/'))
            email = form.get('email', '')
            try:
                result = _AUTH.sign_in(self.auth_token, email=email, password=form.get('password', ''))
            except (AuthRejected, AuthValidationError):
                self._account_page(cart_id=cart_id, new_cart=new_cart, query={'next': next_path}, error='Email or password is incorrect.', values={'email': email})
                return
            self._use_auth_token(result['session_token'])
            self._redirect(next_path, cart_id=cart_id, new_cart=new_cart)
            return
        if path == "/account/logout":
            _AUTH.sign_out(self.auth_token)
            token, _ = _AUTH.ensure_session(None)
            self._use_auth_token(token)
            self._redirect('/', cart_id=cart_id, new_cart=new_cart)
            return
        if path == "/cart/add":
            product = fetch_product(product_id=form.get("product_id", ""))
            if product is None:
                self.send_error(400, "Unknown product")
                return
            option = next((o for o in product["options"] if o["option_id"] == form.get("option_id")), None)
            try:
                quantity = int(form.get("quantity", "1"))
            except ValueError:
                quantity = 0
            if option is None or not 1 <= quantity <= 20:
                self.send_error(422, "Choose a valid option and quantity")
                return
            with BACKEND.lifecycle.connection(transaction=True) as connection:
                connection.execute(
                    """INSERT INTO wb_walmart_carts(cart_id, product_id, option_id, quantity)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(cart_id, product_id, option_id) DO UPDATE SET
                         quantity = MIN(20, quantity + excluded.quantity), updated_at=CURRENT_TIMESTAMP""",
                    (cart_id, product["id"], option["option_id"], quantity),
                )
            self._redirect("/cart?added=1", cart_id=cart_id, new_cart=new_cart)
            return
        if path == "/cart/update":
            try:
                quantity = int(form.get("quantity", "0"))
            except ValueError:
                quantity = 0
            if not 1 <= quantity <= 20:
                self.send_error(422, "Quantity must be between 1 and 20")
                return
            with BACKEND.lifecycle.connection(transaction=True) as connection:
                connection.execute("UPDATE wb_walmart_carts SET quantity=?, updated_at=CURRENT_TIMESTAMP WHERE cart_id=? AND product_id=? AND option_id=?", (quantity, cart_id, form.get("product_id", ""), form.get("option_id", "")))
            self._redirect("/cart", cart_id=cart_id, new_cart=new_cart)
            return
        if path == "/cart/remove":
            with BACKEND.lifecycle.connection(transaction=True) as connection:
                connection.execute("DELETE FROM wb_walmart_carts WHERE cart_id=? AND product_id=? AND option_id=?", (cart_id, form.get("product_id", ""), form.get("option_id", "")))
            self._redirect("/cart", cart_id=cart_id, new_cart=new_cart)
            return
        if path == "/checkout/review":
            zip_value = form.get("zip", "").strip()
            if not re.fullmatch(r"\d{5}", zip_value):
                self._checkout(cart_id=cart_id, new_cart=new_cart, zip_value=zip_value, error="Enter a valid 5-digit ZIP code.")
                return
            self._redirect(f"/checkout/review?reviewed=1&zip={quote(zip_value)}", cart_id=cart_id, new_cart=new_cart)
            return
        if path == "/checkout/place":
            if not self.account:
                self._redirect('/account-entry?next=/checkout/review', cart_id=cart_id, new_cart=new_cart)
                return
            zip_value = form.get('zip', '').strip()
            lines = cart_lines(cart_id)
            if not re.fullmatch(r"\d{5}", zip_value) or not lines:
                self._redirect('/cart', cart_id=cart_id, new_cart=new_cart)
                return
            subtotal = sum(line['unit_cents'] * line['quantity'] for line in lines)
            tax = round(subtotal * 0.0775)
            order_id = 'WM' + secrets.token_hex(6).upper()
            with BACKEND.lifecycle.connection(transaction=True) as connection:
                connection.execute("INSERT INTO wb_walmart_orders(order_id,account_id,zip_code,subtotal_cents,tax_cents,total_cents) VALUES (?,?,?,?,?,?)", (order_id, self.account['account_id'], zip_value, subtotal, tax, subtotal + tax))
                connection.executemany("INSERT INTO wb_walmart_order_items(order_id,product_id,product_name,option_label,image,quantity,unit_cents) VALUES (?,?,?,?,?,?,?)", [(order_id, line['product_id'], line['name'], line['option_label'], line['image'], line['quantity'], line['unit_cents']) for line in lines])
                connection.execute("DELETE FROM wb_walmart_carts WHERE cart_id=?", (cart_id,))
            self._redirect(f'/order-confirmation?id={quote(order_id)}', cart_id=cart_id, new_cart=new_cart)
            return
        self.send_error(404)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the offline Walmart clone")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "4173")))
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), WalmartHandler)
    print(f"Walmart offline clone: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
