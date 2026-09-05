from __future__ import annotations

import concurrent.futures
import http.cookiejar
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


CLONE_ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class RunningClone:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.port = free_port()
        self.process: subprocess.Popen[str] | None = None

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        env = os.environ.copy()
        env["WEBSITEBENCH_SITE_BACKEND_DATABASE"] = str(self.database_path)
        self.process = subprocess.Popen(
            [sys.executable, "app.py", "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=CLONE_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.time() + 12
        while time.time() < deadline:
            if self.process.poll() is not None:
                stdout, stderr = self.process.communicate()
                raise AssertionError(f"clone stopped during startup\n{stdout}\n{stderr}")
            try:
                with urllib.request.urlopen(f"{self.origin}/__websitebench/health", timeout=1) as response:
                    if response.status == 200:
                        return
            except OSError:
                time.sleep(0.08)
        raise AssertionError("clone health endpoint did not become ready")

    def stop(self) -> None:
        if self.process is None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        if self.process.stdout is not None:
            self.process.stdout.close()
        if self.process.stderr is not None:
            self.process.stderr.close()
        self.process = None


class WalmartCloneTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="walmart-clone-test-")
        self.database = Path(self.tempdir.name) / "walmart.sqlite3"
        self.server = RunningClone(self.database)
        self.server.start()
        self.jar = http.cookiejar.CookieJar()
        self.browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def tearDown(self) -> None:
        self.server.stop()
        self.tempdir.cleanup()

    def get(self, path: str, *, opener=None):
        return (opener or self.browser).open(f"{self.server.origin}{path}", timeout=5)

    def post(self, path: str, fields: dict[str, str], *, opener=None):
        request = urllib.request.Request(
            f"{self.server.origin}{path}",
            data=urllib.parse.urlencode(fields).encode(),
            method="POST",
        )
        return (opener or self.browser).open(request, timeout=5)

    def add_dawn(self, *, option: str = "fresh-rain-18", quantity: str = "1") -> str:
        with self.post("/cart/add", {"product_id": "dawn-18", "option_id": option, "quantity": quantity}) as response:
            return response.read().decode()

    def register(self, email: str = "shopper@example.com", password: str = "local-pass-123") -> str:
        with self.post("/account/register", {"display_name": "Local Shopper", "email": email, "password": password, "next": "/account-entry"}) as response:
            verification = response.read().decode()
        match = re.search(r'<strong>(\d{6})</strong>', verification)
        self.assertIsNotNone(match)
        with self.post("/account/verify", {"code": match.group(1), "next": "/account-entry"}) as response:
            return response.read().decode()

    def test_public_routes_assets_and_truthful_boundaries(self) -> None:
        expected = {
            "/": "Members get movies &amp; more",
            "/all-departments": "All Departments",
            "/category/household-essentials": "Household Essentials",
            "/category/personal-care": "Degree Advanced Men",
            "/search?q=dish%20soap": "Results for",
            "/search?q=zzzz-no-match-websitebench": "No matching items",
            "/product/dawn-ultra-original-18oz": "Choose an option",
            "/cart": "Your cart is empty",
            "/checkout/review": "Add an item before continuing",
            "/help": "Help Center",
            "/account-entry": "Sign in to your account",
        }
        for path, text in expected.items():
            with self.subTest(path=path), self.get(path) as response:
                body = response.read().decode()
                self.assertEqual(response.status, 200)
                self.assertIn(text, body)
                self.assertIn("Content-Security-Policy", response.headers)
        with self.get("/static/assets/dawn-original-18oz.jpg") as response:
            self.assertEqual(response.headers.get_content_type(), "image/jpeg")
            self.assertGreater(len(response.read()), 20_000)
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.get("/not-a-real-route")
        self.assertEqual(error.exception.code, 404)

    def test_search_filter_sort_and_server_validation(self) -> None:
        with self.get("/search?q=dish%20soap&brand=Dawn&sort=price-low") as response:
            body = response.read().decode()
            self.assertIn("Dawn Ultra", body)
            self.assertNotIn("Gain EZ-Squeeze", body)
            self.assertLess(body.index("$1.06"), body.index("$3.18"))
        with self.get("/search?q=dish%20soap&brand=Dawn&min_price=2&max_price=4") as response:
            body = response.read().decode()
            self.assertIn("$3.18", body)
            self.assertNotIn("$1.06", body)
        request = urllib.request.Request(
            f"{self.server.origin}/cart/add",
            data=urllib.parse.urlencode({"product_id": "dawn-18", "option_id": "forged", "quantity": "99"}).encode(),
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.browser.open(request)
        self.assertEqual(error.exception.code, 422)
        with self.get("/cart") as response:
            self.assertIn("Your cart is empty", response.read().decode())

    def test_cart_checkout_validation_isolation_and_restart(self) -> None:
        self.assertIn("Welcome, Local Shopper", self.register())
        self.add_dawn()
        with self.get("/cart") as response:
            body = response.read().decode()
            self.assertIn("Fresh Rain, 18 fl oz", body)
            self.assertIn("$3.38", body)
        with self.post("/cart/update", {"product_id": "dawn-18", "option_id": "fresh-rain-18", "quantity": "2"}) as response:
            body = response.read().decode()
            self.assertIn("$6.76", body)
        with self.post("/checkout/review", {"zip": "abc"}) as response:
            body = response.read().decode()
            self.assertIn("Enter a valid 5-digit ZIP code", body)
            self.assertIn('aria-invalid="true"', body)
        with self.post("/checkout/review", {"zip": "95829"}) as response:
            body = response.read().decode()
            self.assertIn("Review your order", body)
            self.assertIn("Place order", body)
            self.assertIn("No payment details are collected", body)
        with self.post("/checkout/place", {"zip": "95829"}) as response:
            body = response.read().decode()
            self.assertIn("Thanks, Local Shopper", body)
            self.assertIn("Local preview order", body)
        with self.get("/account-entry?view=purchases") as response:
            self.assertIn("Purchase history", response.read().decode())
        with self.get("/cart") as response:
            self.assertIn("Your cart is empty", response.read().decode())

        isolated_jar = http.cookiejar.CookieJar()
        isolated = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(isolated_jar))
        with self.get("/cart", opener=isolated) as response:
            self.assertIn("Your cart is empty", response.read().decode())

        self.server.stop()
        self.server = RunningClone(self.database)
        self.server.start()
        with self.get("/cart") as response:
            self.assertIn("Your cart is empty", response.read().decode())
        with self.get("/account-entry?view=purchases") as response:
            self.assertIn("Purchase history", response.read().decode())

    def test_registration_login_logout_and_cart_checkout_gate(self) -> None:
        with self.post("/account/register", {"display_name": "A", "email": "bad", "password": "short"}) as response:
            self.assertIn("email is invalid", response.read().decode())
        self.register(email="account@example.com", password="correct-horse")
        with self.post("/account/logout", {}) as response:
            self.assertIn("Members get movies", response.read().decode())
        with self.post("/account/login", {"email": "account@example.com", "password": "wrong-password"}) as response:
            self.assertIn("Email or password is incorrect", response.read().decode())
        with self.post("/account/login", {"email": "account@example.com", "password": "correct-horse", "next": "/account-entry"}) as response:
            self.assertIn("Welcome, Local Shopper", response.read().decode())

    def test_concurrent_cart_mutations_and_deterministic_reset(self) -> None:
        with self.get("/"):
            pass
        cookie = next(item for item in self.jar if item.name == "wb_walmart_cart")

        def add_once(_: int) -> int:
            request = urllib.request.Request(
                f"{self.server.origin}/cart/add",
                data=urllib.parse.urlencode({"product_id": "dawn-18", "option_id": "original-18", "quantity": "1"}).encode(),
                method="POST",
                headers={"Cookie": f"wb_walmart_cart={cookie.value}"},
            )
            with urllib.request.urlopen(request, timeout=6) as response:
                response.read()
                return response.status

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            statuses = list(pool.map(add_once, range(4)))
        self.assertEqual(statuses, [200, 200, 200, 200])
        with self.get("/cart") as response:
            body = response.read().decode()
            self.assertIn("$12.72", body)
        with self.post("/__websitebench/reset", {}) as response:
            self.assertIn("Members get movies &amp; more", response.read().decode())
        with self.get("/cart") as response:
            self.assertIn("Your cart is empty", response.read().decode())
        with self.get("/search?q=dish%20soap") as response:
            self.assertIn("5 results", response.read().decode())


if __name__ == "__main__":
    unittest.main(verbosity=2)
