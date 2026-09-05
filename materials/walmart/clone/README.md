# Walmart offline clone

Start the exact local candidate from this directory:

```bash
../../../.venv/bin/python app.py --host 127.0.0.1 --port 4173
```

The runtime is local-only. It uses the generated WebsiteBench backend integration with `../backend/runtime.json` and `../backend/data/walmart.sqlite3`. Registration, sign-in, password hashing, local sessions, search, filters, product options, cart mutations, checkout, order history, and persistence are implemented locally. A checkout creates a test order on this device and never submits an order or payment to Walmart.

Run the candidate tests from the repository root:

```bash
.venv/bin/python -m unittest discover -s materials/walmart/clone/tests -v
```
