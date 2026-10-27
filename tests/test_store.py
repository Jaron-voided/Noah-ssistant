import pytest

import config
from db.store import Capture, init_db, recent, save, search


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    init_db()


def test_save_and_search_note():
    cap = Capture(type="note", raw="Hello world", title="Hello")
    row_id = save(cap)
    assert row_id == 1
    results = search("Hello")
    assert len(results) == 1
    assert results[0]["raw"] == "Hello world"
    assert results[0]["type"] == "note"


def test_save_link_with_url():
    cap = Capture(type="link", raw="https://example.com", url="https://example.com", title="Example")
    save(cap)
    results = search("example")
    assert results[0]["type"] == "link"
    assert results[0]["url"] == "https://example.com"


def test_save_event_with_dt():
    cap = Capture(type="event", raw="Dentist 10am", title="Dentist", event_dt="2026-04-03T10:00:00")
    save(cap)
    results = search("Dentist")
    assert results[0]["event_dt"] == "2026-04-03T10:00:00"


def test_recent_returns_newest_first():
    for i in range(3):
        save(Capture(type="note", raw=f"Note {i}"))
    rows = recent(limit=3)
    assert rows[0]["raw"] == "Note 2"


def test_search_no_results():
    results = search("xyzzy_does_not_exist")
    assert results == []


def test_multiple_saves_increment_id():
    id1 = save(Capture(type="note", raw="First"))
    id2 = save(Capture(type="note", raw="Second"))
    assert id2 == id1 + 1
