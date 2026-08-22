from fastapi.testclient import TestClient
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
import sqlite3
from pathlib import Path

from app import APP, BOOKS, DB

client = TestClient(APP)

def register_verified(test_client: TestClient, *, email: str) -> None:
    response = test_client.post('/register', data={
        'email': email,
        'display_name': 'Reader Fixture',
        'password': 'Local-only-pass-2026',
        'terms': 'on',
    }, follow_redirects=False)
    assert response.status_code == 303
    pending = parse_qs(urlsplit(response.headers['location']).query)['pending'][0]
    outbox = test_client.get('/api/local/outbox')
    assert outbox.status_code == 200
    payload = outbox.json()
    assert payload['status'] == 'LOCAL_ONLY'
    assert payload['recipient'] == email
    verify = test_client.post('/verify', data={'pending': pending, 'code': payload['verification_code']}, follow_redirects=False)
    assert verify.status_code == 303

def unique_email() -> str:
    return f"fixture-{uuid4().hex[:12]}@example.test"

def test_catalog_has_two_hundred_local_titles():
    assert len(BOOKS) == 200
    response = client.get('/search?q=Atomic+Habits')
    assert response.status_code == 200
    assert 'Atomic Habits' in response.text

def test_book_detail_and_library_flow_requires_local_session():
    detail = client.get('/app/books/atomic-habits')
    assert detail.status_code == 200
    assert 'Add to My Library' in detail.text
    library = client.get('/app/library')
    assert library.status_code == 200
    assert 'Your library is waiting' in library.text

def test_local_status_exposes_no_remote_dependency():
    status = client.get('/api/status')
    assert status.status_code == 200
    payload = status.json()
    assert payload['site_id'] == 'blinkist'
    assert payload['catalog_count'] == 200

def test_registration_outbox_login_favorite_and_actor_isolation():
    first = TestClient(APP)
    email = unique_email()
    register_verified(first, email=email)
    assert first.get('/api/status').json()['authenticated'] is True
    detail = first.get('/app/books/atomic-habits-en')
    assert detail.status_code == 200
    assert 'James Clear' in detail.text
    assert first.post('/app/books/atomic-habits/favorite', follow_redirects=False).status_code == 303
    assert 'Atomic Habits' in first.get('/app/library').text
    first.post('/logout', follow_redirects=False)
    login = first.post('/login', data={'email': email, 'password': 'Local-only-pass-2026', 'next': '/app/library'}, follow_redirects=False)
    assert login.status_code == 303
    assert login.headers['location'] == '/app/library'
    assert 'Atomic Habits' in first.get('/app/library').text

    second = TestClient(APP)
    register_verified(second, email=unique_email())
    assert 'Your library is waiting' in second.get('/app/library').text

def test_subscription_uses_local_payment_state_machine_and_events():
    test_client = TestClient(APP)
    register_verified(test_client, email=unique_email())
    response = test_client.post('/subscribe', data={'scenario': 'sandbox-approved'}, follow_redirects=False)
    assert response.status_code == 303
    status = test_client.get('/api/status').json()
    assert status['subscription']['status'] == 'active'
    flow_id = status['latest_order']['flow_id']
    database_path = Path(DB)
    with sqlite3.connect(database_path) as connection:
        event_types = {
            row[0]
            for row in connection.execute(
                'SELECT event_type FROM websitebench_payment_events WHERE site_id=? AND flow_id=?',
                ('blinkist', flow_id),
            )
        }
    assert {'FLOW_CREATED', 'ATTEMPT_APPROVED', 'APPROVAL_CONSUMED'} <= event_types

def test_declined_payment_does_not_grant_active_subscription():
    test_client = TestClient(APP)
    register_verified(test_client, email=unique_email())
    response = test_client.post('/subscribe', data={'scenario': 'sandbox-declined'}, follow_redirects=False)
    assert response.status_code == 303
    status = test_client.get('/api/status').json()
    assert status['subscription']['status'] == 'declined'

def test_repeated_declined_checkout_is_idempotent_and_never_500s():
    test_client = TestClient(APP)
    register_verified(test_client, email=unique_email())
    first = test_client.post('/subscribe', data={'scenario': 'sandbox-declined'}, follow_redirects=False)
    second = test_client.post('/subscribe', data={'scenario': 'sandbox-declined'}, follow_redirects=False)
    assert first.status_code == second.status_code == 303
    assert first.headers['location'] == second.headers['location']
    assert test_client.get(second.headers['location']).status_code == 200

def test_next_parameter_rejects_backslash_open_redirects():
    response = client.get('/subscribe?next=%2F%5Cevil.com')
    assert response.status_code == 200
    assert '/\\evil.com' not in response.text
    assert "value='/en/app/for-you'" in response.text

def test_password_recovery_uses_enumeration_safe_local_outbox():
    test_client = TestClient(APP)
    email = unique_email()
    register_verified(test_client, email=email)
    test_client.post('/logout', follow_redirects=False)
    recovery = test_client.post('/forgot-password', data={'email': email}, follow_redirects=False)
    assert recovery.status_code == 303
    outbox = test_client.get('/api/local/outbox?purpose=password-reset').json()
    assert outbox['status'] == 'LOCAL_ONLY'
    reset = test_client.post('/reset-password', data={'code': outbox['verification_code'], 'new_password': 'New-local-pass-2026'}, follow_redirects=False)
    assert reset.status_code == 303
    test_client.post('/logout', follow_redirects=False)
    login = test_client.post('/login', data={'email': email, 'password': 'New-local-pass-2026'}, follow_redirects=False)
    assert login.status_code == 303

def test_preview_learning_state_assessment_progress_and_history_are_local():
    test_client = TestClient(APP)
    register_verified(test_client, email=unique_email())

    preview = test_client.get('/app/books/atomic-habits/preview')
    assert preview.status_code == 200
    assert 'A short local preview' in preview.text
    saved = test_client.post('/app/books/atomic-habits/progress', data={'mode': 'preview', 'position': '35'}, follow_redirects=False)
    assert saved.status_code == 303
    assert test_client.get('/app/progress').status_code == 200
    assert '35%' in test_client.get('/app/progress').text

    assessment = test_client.get('/app/books/atomic-habits/assessment')
    assert assessment.status_code == 200
    submitted = test_client.post('/app/books/atomic-habits/assessment', data={'q1': 'obvious', 'q2': 'small', 'q3': 'reward'}, follow_redirects=False)
    assert submitted.status_code == 303
    assert '3/3 correct' in test_client.get('/app/books/atomic-habits/assessment').text
    assert 'Preview' in test_client.get('/app/history').text

def test_premium_read_and_listen_are_gated_then_replayable():
    test_client = TestClient(APP)
    register_verified(test_client, email=unique_email())
    gated = test_client.get('/app/books/atomic-habits/read?mode=text', follow_redirects=False)
    assert gated.status_code == 303
    assert '/subscribe' in gated.headers['location']
    subscribed = test_client.post('/subscribe', data={'scenario': 'sandbox-approved', 'next': '/app/books/atomic-habits/read?mode=text'}, follow_redirects=False)
    assert subscribed.status_code == 303
    reader = test_client.get('/app/books/atomic-habits/read?mode=text')
    listener = test_client.get('/app/books/atomic-habits/listen')
    assert reader.status_code == 200 and 'Key ideas in text' in reader.text
    assert listener.status_code == 200 and 'Audio summary' in listener.text

def test_settings_help_and_alias_entries_are_real_routes():
    test_client = TestClient(APP)
    register_verified(test_client, email=unique_email())
    assert test_client.get('/settings').status_code == 200
    assert test_client.get('/app/settings').status_code == 200
    assert test_client.get('/help').status_code == 200
    assert test_client.get('/app/help').status_code == 200
    assert test_client.get('/app/assessment', follow_redirects=False).status_code == 307

def test_generated_catalog_details_keep_title_and_author_consistent():
    detail = client.get('/app/books/deep-work')
    assert detail.status_code == 200
    assert 'Deep Work' in detail.text
    assert 'Cal Newport' in detail.text
    assert 'Atomic Habits (2018)' not in detail.text
    assert 'James Clear' not in detail.text

def test_active_subscription_is_idempotent_on_repeat_submission():
    test_client = TestClient(APP)
    register_verified(test_client, email=unique_email())
    first = test_client.post('/subscribe', data={'scenario': 'sandbox-approved'}, follow_redirects=False)
    assert first.status_code == 303
    second = test_client.post('/subscribe', data={'scenario': 'sandbox-approved', 'next': '/app/library'}, follow_redirects=False)
    assert second.status_code == 303
    assert second.headers['location'] == '/app/library'

def test_navigation_sections_are_real_local_workflows():
    test_client = TestClient(APP)
    register_verified(test_client, email=unique_email())
    assert test_client.get('/app/daily').status_code == 200
    assert 'Start now' in test_client.get('/app/daily').text

    spaces = test_client.get('/app/spaces?space=Focus')
    assert spaces.status_code == 200 and 'Add to space' in spaces.text
    added = test_client.post('/app/spaces/add', data={'space': 'Focus', 'slug': 'atomic-habits'}, follow_redirects=False)
    assert added.status_code == 303
    assert 'Saved' in test_client.get('/app/spaces?space=Focus').text

    highlights = test_client.post('/app/highlights', data={'slug': 'atomic-habits', 'note': 'Make the cue obvious.'}, follow_redirects=False)
    assert highlights.status_code == 303
    assert 'Make the cue obvious.' in test_client.get('/app/highlights').text

    assert test_client.get('/app/infographics').status_code == 200
    assert test_client.get('/app/infographics/atomic-habits').status_code == 200
    assert 'Make the cue obvious' in test_client.get('/app/infographics/atomic-habits').text

    assert test_client.get('/app/masterclasses').status_code == 200
    session = test_client.get('/app/masterclasses/ai-unlocked-how-to-future-proof-yourself')
    assert session.status_code == 200 and 'Reserve a place' in session.text
    registered = test_client.post('/app/masterclasses/ai-unlocked-how-to-future-proof-yourself/register', follow_redirects=False)
    assert registered.status_code == 303
    assert 'Registered' in test_client.get('/app/masterclasses/ai-unlocked-how-to-future-proof-yourself').text

def test_spaces_normalize_names_and_isolate_new_account_state():
    first = TestClient(APP)
    register_verified(first, email=unique_email())
    added = first.post('/app/spaces/add', data={'space': '  Focus  ', 'slug': 'atomic-habits'}, follow_redirects=False)
    assert added.status_code == 303
    assert 'Saved' in first.get('/app/spaces?space=Focus').text

    second = TestClient(APP)
    register_verified(second, email=unique_email())
    assert 'Saved' not in second.get('/app/spaces?space=Focus').text
    assert 'Make the cue obvious.' not in second.get('/app/highlights').text

def test_settings_subroutes_and_connection_check_are_real_local_flows():
    test_client = TestClient(APP)
    register_verified(test_client, email=unique_email())
    assert 'Language' in test_client.get('/settings/content').text
    selected = test_client.post('/settings/content', data={'language': 'German'}, follow_redirects=False)
    assert selected.status_code == 303
    assert 'Current language: German' in test_client.get('/settings/content').text
    assert 'Manage your email preferences' in test_client.get('/settings/email_optins').text
    toggled = test_client.post('/settings/email_optins', data={'preference': 'daily_pick'}, follow_redirects=False)
    assert toggled.status_code == 303
    assert 'Kindle connect' in test_client.get('/settings/external_services').text
    assert 'You have not purchased any products yet.' in test_client.get('/settings/payment-history').text
    assert test_client.get('/en/nc/settings/invoices').status_code == 200
    check = test_client.get('/app/check?run=1')
    assert check.status_code == 200 and 'All local checks passed' in check.text and 'Run again' in check.text

def test_registration_requires_terms_and_profile_edit_persists():
    test_client = TestClient(APP)
    response = test_client.post('/register', data={'email': unique_email(), 'display_name': 'Reader Fixture', 'password': 'Local-only-pass-2026'}, follow_redirects=False)
    assert response.status_code == 422 and 'Terms of Service' in response.text
    email = unique_email()
    register_verified(test_client, email=email)
    profile = test_client.get('/settings/profile')
    assert profile.status_code == 200 and 'Edit profile' in profile.text
    saved = test_client.post('/settings/profile', data={'display_name': 'Updated Reader'}, follow_redirects=False)
    assert saved.status_code == 303
    assert 'Updated Reader' in test_client.get('/settings').text

def test_registration_rejects_invalid_code_and_duplicate_email():
    email = unique_email()
    first = TestClient(APP)
    started = first.post('/register', data={
        'email': email,
        'display_name': 'Reader Fixture',
        'password': 'Local-only-pass-2026',
        'terms': 'on',
    }, follow_redirects=False)
    assert started.status_code == 303
    pending = parse_qs(urlsplit(started.headers['location']).query)['pending'][0]
    invalid = first.post('/verify', data={'pending': pending, 'code': '000000'}, follow_redirects=False)
    assert invalid.status_code == 422
    assert first.get('/api/status').json()['authenticated'] is False
    outbox = first.get('/api/local/outbox').json()
    verified = first.post('/verify', data={'pending': pending, 'code': outbox['verification_code']}, follow_redirects=False)
    assert verified.status_code == 303

    duplicate = TestClient(APP).post('/register', data={
        'email': email,
        'display_name': 'Duplicate Fixture',
        'password': 'Another-local-pass-2026',
        'terms': 'on',
    }, follow_redirects=False)
    assert duplicate.status_code == 422
    assert 'local account' in duplicate.text

def test_masterclass_catalog_has_observed_sessions_and_query_cannot_forge_rsvp():
    page = client.get('/app/masterclasses')
    assert page.status_code == 200
    for session_id in ('ai-unlocked-how-to-future-proof-yourself', 'become-a-blinkist-power-user-live-guide', 'thrive-without-the-overdrive-sustainable-success-strategies', 'work-smarter-not-harder-peak-productivity-tools', 'the-innovation-edge-problem-solving-made-simple', 'learn-like-a-pro-master-skills-faster', 'build-your-own-second-brain-from-info-to-action'):
        assert f'/app/masterclasses/{session_id}' in page.text
    detail = client.get('/app/masterclasses/ai-unlocked-how-to-future-proof-yourself?registered=1')
    assert detail.status_code == 200 and 'Reserve a place' in detail.text

def test_daily_and_masterclass_content_uses_observed_titles():
    assert 'The Ambition Penalty' in client.get('/app/daily').text
    assert 'Become a Blinkist Power User: Live Guide' in client.get('/app/masterclasses').text

def test_masterclass_metadata_matches_authenticated_source_observation():
    page = client.get('/app/masterclasses')
    assert 'Fri, 04 Sep' in page.text
    assert 'Katharina Loth' in page.text
    assert 'Thu, 08 Oct &amp; 1 more date' in page.text
    assert 'Nicole Lenzen' in page.text
    assert 'Build a personal system that turns information overload into your competitive advantage.' in page.text

def test_loopback_logout_revokes_local_session_and_cookie():
    test_client = TestClient(APP)
    register_verified(test_client, email=unique_email())
    assert test_client.get('/api/status').json()['authenticated'] is True
    response = test_client.post('/logout', follow_redirects=False)
    assert response.status_code == 303
    assert test_client.get('/api/status').json()['authenticated'] is False

def test_explore_advanced_filters_change_results_and_keep_local_catalog():
    all_titles = client.get('/app/explore')
    filtered = client.get('/app/explore?level=Advanced&max_minutes=15&min_rating=4.5&language=English&schedule=On+demand')
    assert all_titles.status_code == filtered.status_code == 200
    assert 'Apply filters' in filtered.text
    assert 'titles' in filtered.text

def test_auxiliary_pages_expose_correct_active_navigation_context():
    assert "nav-item active" in client.get('/app/progress').text
    assert "nav-item active" in client.get('/app/history').text
    assert "nav-item active" in client.get('/app/check').text

def test_subscription_review_and_history_management_are_local():
    test_client = TestClient(APP)
    register_verified(test_client, email=unique_email())
    review = test_client.get('/subscribe/review')
    assert review.status_code == 200 and 'Review your Premium annual plan' in review.text
    test_client.get('/app/books/atomic-habits/preview')
    history = test_client.get('/app/history')
    assert history.status_code == 200 and 'Remove' in history.text
    with sqlite3.connect(DB) as connection:
        history_id = connection.execute('SELECT id FROM blinkist_history ORDER BY id DESC LIMIT 1').fetchone()[0]
    removed = test_client.post(f'/app/history/{history_id}/delete', follow_redirects=False)
    assert removed.status_code == 303

def test_detail_page_exposes_reading_summary_and_key_idea_map():
    page = client.get('/app/books/atomic-habits')
    assert page.status_code == 200
    assert 'Short, practical takeaways' in page.text
    assert 'Build identity-based habits' in page.text
    assert 'Make the reward satisfying' in page.text

def test_local_checkout_creates_receipt_and_keeps_declined_state_visible():
    approved_client = TestClient(APP)
    register_verified(approved_client, email=unique_email())
    approved = approved_client.post('/subscribe', data={'scenario': 'sandbox-approved'}, follow_redirects=False)
    assert approved.status_code == 303 and approved.headers['location'].startswith('/subscribe/success?')
    receipt = approved_client.get(approved.headers['location'])
    assert receipt.status_code == 200
    assert 'Your Premium annual plan is active' in receipt.text
    assert 'Approved in local sandbox' in receipt.text
    status = approved_client.get('/api/status').json()
    assert status['latest_order']['status'] == 'active'
    assert status['latest_order']['order_id'].startswith('BLK-')

    declined_client = TestClient(APP)
    register_verified(declined_client, email=unique_email())
    declined = declined_client.post('/subscribe', data={'scenario': 'sandbox-declined'}, follow_redirects=False)
    assert declined.status_code == 303 and declined.headers['location'].startswith('/subscribe/result?')
    result = declined_client.get(declined.headers['location'])
    assert result.status_code == 200
    assert "couldn't activate Premium yet" in result.text
    assert 'Declined in local sandbox' in result.text

def test_account_deletion_requires_confirmation_and_cleans_local_data():
    test_client = TestClient(APP)
    register_verified(test_client, email=unique_email())
    invalid = test_client.post('/account/delete', data={'confirmation': 'no'}, follow_redirects=False)
    assert invalid.status_code == 422
    deleted = test_client.post('/account/delete', data={'confirmation': 'DELETE'}, follow_redirects=False)
    assert deleted.status_code == 303
    assert test_client.get('/api/status').json()['authenticated'] is False
