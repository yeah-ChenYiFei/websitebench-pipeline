"""Document attachment journeys for the TripIt clone.

Documents are a free-tier feature: a traveler attaches a PDF or image to a trip,
previews it inline, downloads it, and deletes it, with every byte stored inline
in the single site sqlite file (BLOB) so migration-copy / reset / ephemeral
semantics stay identical. These tests pin the P0 journeys the blind test depends
on — ``upload -> preview -> download -> delete`` and the oversize (>2 MB)
failure — plus the invariants that keep the feature honest: the seed holds
exactly one document, the content type is derived from the extension (never the
client-declared type), colliding names are disambiguated rather than
overwritten, and a foreign or missing document is a 404 that never discloses
existence.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SITE_DIR = Path(__file__).resolve().parents[2]
CLONE_DIR = SITE_DIR / "clone"
APP_FILE = CLONE_DIR / "app.py"

# Isolate this module into a throwaway data dir, set before import so the backend
# resolves its single sqlite file inside it.
DATA_DIR = Path(tempfile.mkdtemp(prefix="tripit-documents-tests-"))
os.environ["WEBSITEBENCH_TRIPIT_DATA_DIR"] = str(DATA_DIR)

LOGIN_URL = "/account/login"
SEED_DOCUMENT_ID = "document-new-york-ny-hotel-quote"
SEED_DOCUMENT_NAME = "ny-hotel-quote.pdf"

# A minimal but real PNG (1x1) so extension-derived typing has honest bytes.
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
    b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)
PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


app_module = load_module(APP_FILE, "tripit_clone_app_document_tests")
db = sys.modules["tripit_clone_backend_db"]
app = app_module.app

PASSWORDS = {row["email"]: row["password"] for row in db.AUTH_FIXTURES}


@pytest.fixture(autouse=True)
def pinned_data_dir(monkeypatch):
    monkeypatch.setenv("WEBSITEBENCH_TRIPIT_DATA_DIR", str(DATA_DIR))
    yield


@pytest.fixture()
def client():
    app_module.reset_fixture_state()
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    app_module.reset_fixture_state()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def sign_in(client: TestClient, email: str = "traveler@example.com"):
    response = client.post(
        LOGIN_URL,
        data={"login_email_address": email, "login_password": PASSWORDS[email]},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    return response


def owner_for(subject: str = "traveler") -> str:
    with closing(db.connect()) as connection:
        return db.owner_for_subject(connection, subject)


def ny_trip_id(owner: str) -> str:
    with closing(db.connect()) as connection:
        trips = db.list_trips(connection, owner, "upcoming")
    return next(t["trip_id"] for t in trips if t["name"] == "New York")


def documents_for(owner: str, trip_id: str) -> list[dict]:
    with closing(db.connect()) as connection:
        return db.list_documents(connection, owner, trip_id)


def document_id_by_name(owner: str, trip_id: str, filename: str) -> str:
    for document in documents_for(owner, trip_id):
        if document["filename"] == filename:
            return document["document_id"]
    raise AssertionError(f"no document named {filename!r}")


def total_documents() -> int:
    with closing(db.connect()) as connection:
        return connection.execute(
            "SELECT COUNT(*) FROM tripit_documents"
        ).fetchone()[0]


def upload(client: TestClient, trip_id: str, filename: str, blob: bytes,
           content_type: str = "application/octet-stream"):
    return client.post(
        f"/trips/{trip_id}/documents",
        files={"document": (filename, blob, content_type)},
        follow_redirects=False,
    )


# ---------------------------------------------------------------------------
# seed invariants
# ---------------------------------------------------------------------------


def test_seed_holds_exactly_one_document(client: TestClient):
    # Frozen data assertion document::tripit_documents::count=1.
    assert total_documents() == 1
    owner = owner_for("traveler")
    seeded = documents_for(owner, ny_trip_id(owner))
    assert [d["filename"] for d in seeded] == [SEED_DOCUMENT_NAME]
    assert seeded[0]["content_type"] == "application/pdf"
    assert seeded[0]["byte_size"] > 0


def test_reset_restores_single_seed_document(client: TestClient):
    sign_in(client)
    owner = owner_for("traveler")
    trip = ny_trip_id(owner)
    upload(client, trip, "extra.pdf", PDF_BYTES, "application/pdf")
    assert len(documents_for(owner, trip)) == 2
    app_module.reset_fixture_state()
    assert total_documents() == 1
    assert [d["filename"] for d in documents_for(owner, trip)] == [SEED_DOCUMENT_NAME]


def test_documents_page_lists_seeded_document(client: TestClient):
    sign_in(client)
    trip = ny_trip_id(owner_for("traveler"))
    response = client.get(f"/trips/{trip}/documents")
    assert response.status_code == 200
    assert SEED_DOCUMENT_NAME in response.text
    # The trip detail exposes an entry point to the documents page.
    detail = client.get(f"/trips/{trip}")
    assert f"/trips/{trip}/documents" in detail.text


# ---------------------------------------------------------------------------
# upload -> preview -> download -> delete (P0)
# ---------------------------------------------------------------------------


def test_upload_preview_download_delete(client: TestClient):
    sign_in(client)
    owner = owner_for("traveler")
    trip = ny_trip_id(owner)

    created = upload(client, trip, "boarding-pass.pdf", PDF_BYTES, "application/pdf")
    assert created.status_code == 303
    assert created.headers["location"] == f"/trips/{trip}/documents"

    listing = client.get(f"/trips/{trip}/documents")
    assert "boarding-pass.pdf" in listing.text
    assert len(documents_for(owner, trip)) == 2

    document_id = document_id_by_name(owner, trip, "boarding-pass.pdf")

    preview = client.get(f"/documents/{document_id}")
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("application/pdf")
    assert preview.headers["content-disposition"] == (
        'inline; filename="boarding-pass.pdf"'
    )
    assert preview.content == PDF_BYTES

    download = client.get(f"/documents/{document_id}/download")
    assert download.status_code == 200
    assert download.headers["content-disposition"] == (
        'attachment; filename="boarding-pass.pdf"'
    )
    assert download.content == PDF_BYTES

    removed = client.post(f"/documents/{document_id}/delete", follow_redirects=False)
    assert removed.status_code == 303
    assert removed.headers["location"] == f"/trips/{trip}/documents"
    assert len(documents_for(owner, trip)) == 1
    assert client.get(f"/documents/{document_id}").status_code == 404


def test_content_type_derived_from_extension_not_client(client: TestClient):
    sign_in(client)
    owner = owner_for("traveler")
    trip = ny_trip_id(owner)
    # Client lies about the type; the server must trust the .png extension.
    upload(client, trip, "scan.png", PNG_BYTES, "application/octet-stream")
    document_id = document_id_by_name(owner, trip, "scan.png")
    preview = client.get(f"/documents/{document_id}")
    assert preview.headers["content-type"].startswith("image/png")
    with closing(db.connect()) as connection:
        row = db.get_document(connection, owner, document_id)
    assert row["content_type"] == "image/png"


def test_duplicate_filename_is_disambiguated(client: TestClient):
    sign_in(client)
    owner = owner_for("traveler")
    trip = ny_trip_id(owner)
    upload(client, trip, "receipt.pdf", b"%PDF-1.4 first", "application/pdf")
    upload(client, trip, "receipt.pdf", b"%PDF-1.4 second", "application/pdf")
    names = sorted(d["filename"] for d in documents_for(owner, trip))
    assert names == ["ny-hotel-quote.pdf", "receipt-2.pdf", "receipt.pdf"]
    first = client.get(
        f"/documents/{document_id_by_name(owner, trip, 'receipt.pdf')}"
    )
    second = client.get(
        f"/documents/{document_id_by_name(owner, trip, 'receipt-2.pdf')}"
    )
    assert first.content == b"%PDF-1.4 first"
    assert second.content == b"%PDF-1.4 second"


# ---------------------------------------------------------------------------
# failure UX
# ---------------------------------------------------------------------------


def test_oversize_upload_is_rejected(client: TestClient):
    sign_in(client)
    owner = owner_for("traveler")
    trip = ny_trip_id(owner)
    before = len(documents_for(owner, trip))
    oversize = b"%PDF-1.4 " + b"A" * (db.MAX_DOCUMENT_BYTES + 10)
    response = upload(client, trip, "huge.pdf", oversize, "application/pdf")
    assert response.status_code == 400
    assert "2 MB" in response.text
    assert len(documents_for(owner, trip)) == before


def test_upload_at_the_two_megabyte_ceiling_succeeds(client: TestClient):
    sign_in(client)
    owner = owner_for("traveler")
    trip = ny_trip_id(owner)
    at_ceiling = b"A" * db.MAX_DOCUMENT_BYTES
    response = upload(client, trip, "atlimit.pdf", at_ceiling, "application/pdf")
    assert response.status_code == 303
    document_id = document_id_by_name(owner, trip, "atlimit.pdf")
    fetched = client.get(f"/documents/{document_id}/download")
    assert len(fetched.content) == db.MAX_DOCUMENT_BYTES


def test_unknown_extension_is_rejected(client: TestClient):
    sign_in(client)
    owner = owner_for("traveler")
    trip = ny_trip_id(owner)
    before = len(documents_for(owner, trip))
    response = upload(client, trip, "malware.exe", b"MZ...", "application/octet-stream")
    assert response.status_code == 400
    assert "PDF or image" in response.text
    assert len(documents_for(owner, trip)) == before


def test_empty_file_is_rejected(client: TestClient):
    sign_in(client)
    owner = owner_for("traveler")
    trip = ny_trip_id(owner)
    response = upload(client, trip, "blank.pdf", b"", "application/pdf")
    assert response.status_code == 400
    assert "empty" in response.text


def test_missing_file_is_rejected(client: TestClient):
    sign_in(client)
    trip = ny_trip_id(owner_for("traveler"))
    # A form post with no file part at all.
    response = client.post(
        f"/trips/{trip}/documents", data={"noise": "1"}, follow_redirects=False
    )
    assert response.status_code == 400
    assert "Choose a file" in response.text


# ---------------------------------------------------------------------------
# authorization / isolation
# ---------------------------------------------------------------------------


def test_documents_require_authentication(client: TestClient):
    trip = ny_trip_id(owner_for("traveler"))
    for method, url in [
        ("get", f"/trips/{trip}/documents"),
        ("get", f"/documents/{SEED_DOCUMENT_ID}"),
        ("get", f"/documents/{SEED_DOCUMENT_ID}/download"),
    ]:
        response = getattr(client, method)(url, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == LOGIN_URL
    posted = client.post(
        f"/trips/{trip}/documents", data={"x": "1"}, follow_redirects=False
    )
    assert posted.status_code == 303
    assert posted.headers["location"] == LOGIN_URL


def test_foreign_document_is_not_found(client: TestClient):
    # The seeded document belongs to traveler@; other@ must not see it, and the
    # 404 must not distinguish "not yours" from "does not exist".
    sign_in(client, "other@example.com")
    assert client.get(f"/documents/{SEED_DOCUMENT_ID}").status_code == 404
    assert client.get(f"/documents/{SEED_DOCUMENT_ID}/download").status_code == 404
    missing = client.get("/documents/document-does-not-exist")
    assert missing.status_code == 404
    # Deleting someone else's document is a 404 and leaves it intact.
    deleted = client.post(
        f"/documents/{SEED_DOCUMENT_ID}/delete", follow_redirects=False
    )
    assert deleted.status_code == 404
    assert total_documents() == 1


def test_foreign_trip_documents_page_is_not_found(client: TestClient):
    trip = ny_trip_id(owner_for("traveler"))
    sign_in(client, "other@example.com")
    assert client.get(f"/trips/{trip}/documents").status_code == 404
    assert upload(client, trip, "sneaky.pdf", PDF_BYTES, "application/pdf").status_code == 404


def test_upload_persists_across_restart(client: TestClient):
    sign_in(client)
    owner = owner_for("traveler")
    trip = ny_trip_id(owner)
    upload(client, trip, "keeper.pdf", PDF_BYTES, "application/pdf")
    document_id = document_id_by_name(owner, trip, "keeper.pdf")
    # A fresh client (new "process") over the same on-disk data dir still serves
    # it — the BLOB lives in the single persistent sqlite file, not memory.
    with TestClient(app, base_url="https://testserver") as reborn:
        sign_in(reborn)
        again = reborn.get(f"/documents/{document_id}/download")
    assert again.status_code == 200
    assert again.content == PDF_BYTES
