import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from llm.classifier import Classified, ClassifierError, classify


def _mock_response(data: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = {"message": {"content": json.dumps(data)}}
    resp.raise_for_status.return_value = None
    return resp


def test_classifies_link():
    with patch("llm.classifier.requests.post") as mock_post:
        mock_post.return_value = _mock_response(
            {"type": "link", "title": "Example", "url": "https://example.com",
             "event_dt": None, "description": None}
        )
        result = classify("Read this: https://example.com")
    assert result.type == "link"
    assert result.url == "https://example.com"
    assert result.title == "Example"


def test_classifier_disables_thinking_and_allows_model_loading():
    with patch("llm.classifier.requests.post") as mock_post:
        mock_post.return_value = _mock_response(
            {"type": "task", "title": "Buy fictional supplies"}
        )
        classify("Buy fictional supplies")

    kwargs = mock_post.call_args.kwargs
    assert kwargs["json"]["think"] is False
    assert kwargs["json"]["stream"] is False
    assert kwargs["timeout"] == (5, 120)


def test_classifier_errors_do_not_include_response_or_request_details():
    with patch("llm.classifier.requests.post") as mock_post:
        mock_post.side_effect = requests.exceptions.HTTPError("PRIVATE_REQUEST_DETAIL")
        with pytest.raises(ClassifierError) as error:
            classify("fictional note")
    assert "PRIVATE_REQUEST_DETAIL" not in str(error.value)

    with patch("llm.classifier.requests.post") as mock_post:
        mock_post.return_value = _mock_response(
            {"type": "PRIVATE_MODEL_OUTPUT"}
        )
        with pytest.raises(ClassifierError) as error:
            classify("fictional note")
    assert "PRIVATE_MODEL_OUTPUT" not in str(error.value)


def test_classifies_event():
    with patch("llm.classifier.requests.post") as mock_post:
        mock_post.return_value = _mock_response(
            {"type": "event", "title": "Dentist", "url": None,
             "event_dt": "2026-04-03T10:00:00", "description": None}
        )
        result = classify("Dentist April 3rd 10am")
    assert result.type == "event"
    assert result.event_dt == "2026-04-03T10:00:00"
    assert result.title == "Dentist"


def test_classifies_task():
    with patch("llm.classifier.requests.post") as mock_post:
        mock_post.return_value = _mock_response(
            {"type": "task", "title": "Buy milk", "url": None,
             "event_dt": None, "description": None}
        )
        result = classify("Buy milk")
    assert result.type == "task"
    assert result.title == "Buy milk"


def test_classifies_query():
    with patch("llm.classifier.requests.post") as mock_post:
        mock_post.return_value = _mock_response(
            {"type": "query", "title": None, "url": None,
             "event_dt": None, "description": None}
        )
        result = classify("What's on my calendar today?")
    assert result.type == "query"


def test_classifies_note():
    with patch("llm.classifier.requests.post") as mock_post:
        mock_post.return_value = _mock_response(
            {"type": "note", "title": "Idea", "url": None,
             "event_dt": None, "description": "Use SQLite for local storage"}
        )
        result = classify("Idea: use SQLite for local storage")
    assert result.type == "note"


def test_connection_error_raises_classifier_error():
    with patch("llm.classifier.requests.post") as mock_post:
        mock_post.side_effect = requests.exceptions.ConnectionError()
        with pytest.raises(ClassifierError, match="not reachable"):
            classify("test")


def test_timeout_raises_classifier_error():
    with patch("llm.classifier.requests.post") as mock_post:
        mock_post.side_effect = requests.exceptions.Timeout()
        with pytest.raises(ClassifierError, match="timed out"):
            classify("test")


def test_invalid_json_raises_classifier_error():
    with patch("llm.classifier.requests.post") as mock_post:
        resp = MagicMock()
        resp.json.return_value = {"message": {"content": "not json {"}}
        resp.raise_for_status.return_value = None
        mock_post.return_value = resp
        with pytest.raises(ClassifierError, match="Could not parse"):
            classify("test")


def test_invalid_schema_raises_classifier_error():
    with patch("llm.classifier.requests.post") as mock_post:
        mock_post.return_value = _mock_response({"type": "unknown_type"})
        with pytest.raises(ClassifierError, match="Could not parse"):
            classify("test")
