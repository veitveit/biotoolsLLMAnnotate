"""Tests for bio.tools entry upload functionality."""

import csv

import requests

from biotoolsllmannotate.cli.run import write_upload_report_csv
from biotoolsllmannotate.io.biotools_api import create_biotools_entry


def test_create_biotools_entry_success_201(monkeypatch):
    """Test successful entry creation returns 201 Created."""

    class FakeResp:
        status_code = 201

        def json(self):
            return {"biotoolsID": "test-tool", "name": "Test Tool"}

    def fake_post(url, json, headers, timeout):
        return FakeResp()

    monkeypatch.setattr(requests, "post", fake_post)

    entry = {
        "biotoolsID": "test-tool",
        "name": "Test Tool",
        "description": "A test tool",
        "homepage": "https://example.com",
    }

    result = create_biotools_entry(entry, token="test-token")

    assert result["success"] is True
    assert result["biotools_id"] == "test-tool"
    assert result["status_code"] == 201
    assert result["error"] is None


def test_create_biotools_entry_conflict_409(monkeypatch):
    """Test entry already exists returns 409 Conflict."""

    class FakeResp:
        status_code = 409

        def json(self):
            return {"detail": "Entry already exists"}

    def fake_post(url, json, headers, timeout):
        return FakeResp()

    monkeypatch.setattr(requests, "post", fake_post)

    entry = {
        "biotoolsID": "existing-tool",
        "name": "Existing Tool",
        "description": "Already exists",
        "homepage": "https://example.com",
    }

    result = create_biotools_entry(entry, token="test-token")

    assert result["success"] is False
    assert result["status_code"] == 409
    assert "already exists" in result["error"].lower()


def test_create_biotools_entry_validation_error_400(monkeypatch):
    """Test validation error returns 400 Bad Request."""

    class FakeResp:
        status_code = 400

        def json(self):
            return {"name": ["This field is required."]}

    def fake_post(url, json, headers, timeout):
        return FakeResp()

    monkeypatch.setattr(requests, "post", fake_post)

    entry = {
        "biotoolsID": "invalid-tool",
        "description": "Missing name",
        "homepage": "https://example.com",
    }

    result = create_biotools_entry(entry, token="test-token")

    assert result["success"] is False
    assert result["status_code"] == 400
    assert "validation" in result["error"].lower()


def test_create_biotools_entry_unauthorized_401(monkeypatch):
    """Test invalid token returns 401 Unauthorized."""

    class FakeResp:
        status_code = 401

        def json(self):
            return {"detail": "Authentication credentials were not provided."}

    def fake_post(url, json, headers, timeout):
        return FakeResp()

    monkeypatch.setattr(requests, "post", fake_post)

    entry = {
        "biotoolsID": "test-tool",
        "name": "Test Tool",
        "description": "A test tool",
        "homepage": "https://example.com",
    }

    result = create_biotools_entry(entry, token="invalid-token")

    assert result["success"] is False
    assert result["status_code"] == 401
    assert "authentication" in result["error"].lower()


def test_create_biotools_entry_server_error_all_retries_fail(monkeypatch):
    """Test server error with retry logic exhausting all retries."""
    call_count = 0

    class FakeResp:
        status_code = 503

        def json(self):
            return {"error": "Service temporarily unavailable"}

    def fake_post(url, json, headers, timeout):
        nonlocal call_count
        call_count += 1
        return FakeResp()

    monkeypatch.setattr(requests, "post", fake_post)

    entry = {
        "biotoolsID": "test-tool",
        "name": "Test Tool",
        "description": "A test tool",
        "homepage": "https://example.com",
    }

    result = create_biotools_entry(
        entry,
        token="test-token",
        retry_attempts=3,
        retry_delay=0.01,  # Very short delay for testing
    )

    assert result["success"] is False
    assert result["status_code"] == 503
    assert "after" in result["error"].lower() and "retries" in result["error"].lower()
    assert call_count == 4  # Should have attempted 1 initial + 3 retries


def test_create_biotools_entry_server_error_then_success(monkeypatch):
    """Test server error followed by successful retry."""
    call_count = 0

    class FakeResp:
        def __init__(self, status):
            self.status_code = status

        def json(self):
            if self.status_code == 503:
                return {"error": "Service temporarily unavailable"}
            return {"biotoolsID": "test-tool", "name": "Test Tool"}

    def fake_post(url, json, headers, timeout):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return FakeResp(503)
        return FakeResp(201)

    monkeypatch.setattr(requests, "post", fake_post)

    entry = {
        "biotoolsID": "test-tool",
        "name": "Test Tool",
        "description": "A test tool",
        "homepage": "https://example.com",
    }

    result = create_biotools_entry(
        entry,
        token="test-token",
        retry_attempts=3,
        retry_delay=0.01,
    )

    assert result["success"] is True
    assert result["status_code"] == 201
    assert call_count == 2  # Should have attempted 1 initial + 1 retry


def test_create_biotools_entry_timeout(monkeypatch):
    """Test timeout error is retried."""
    call_count = 0

    def fake_post(url, json, headers, timeout):
        nonlocal call_count
        call_count += 1
        raise requests.Timeout("Connection timeout")

    monkeypatch.setattr(requests, "post", fake_post)

    entry = {
        "biotoolsID": "test-tool",
        "name": "Test Tool",
        "description": "A test tool",
    }

    result = create_biotools_entry(
        entry,
        token="test-token",
        retry_attempts=2,
        retry_delay=0.01,
    )

    assert result["success"] is False
    assert "timeout" in result["error"].lower()
    assert call_count == 3  # Should have attempted 1 initial + 2 retries


def test_write_upload_report_csv(tmp_path):
    """Test writing upload report CSV with bio.tools URLs."""
    upload_stats = {
        "uploaded": 2,
        "failed": 1,
        "skipped": 1,
        "results": [
            {
                "biotools_id": "tool-one",
                "status": "uploaded",
                "error": None,
                "response_code": 201,
                "timestamp": "2024-01-15T10:30:00Z",
            },
            {
                "biotools_id": "tool-two",
                "status": "failed",
                "error": "Validation error: missing name field",
                "response_code": 400,
                "timestamp": "2024-01-15T10:30:05Z",
            },
            {
                "biotools_id": "tool-three",
                "status": "skipped",
                "error": "Entry already exists",
                "response_code": 409,
                "timestamp": "2024-01-15T10:30:10Z",
            },
            {
                "biotools_id": "tool-four",
                "status": "uploaded",
                "error": None,
                "response_code": 201,
                "timestamp": "2024-01-15T10:30:15Z",
            },
        ],
    }

    report_path = tmp_path / "upload_report.csv"
    write_upload_report_csv(upload_stats, tmp_path)

    # Verify file was created
    assert report_path.exists()

    # Read and verify content
    with report_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 4

    # Check uploaded entry has URL
    assert rows[0]["biotoolsID"] == "tool-one"
    assert rows[0]["status"] == "uploaded"
    assert rows[0]["bio_tools_url"] == "https://bio.tools/api/tool/tool-one"
    assert rows[0]["error"] == ""

    # Check failed entry with validation error has no URL but has error
    assert rows[1]["biotoolsID"] == "tool-two"
    assert rows[1]["status"] == "failed"
    assert rows[1]["bio_tools_url"] == ""
    assert "Validation error" in rows[1]["error"]
    assert rows[1]["response_code"] == "400"

    # Check skipped entry (already exists) still gets a URL
    assert rows[2]["biotoolsID"] == "tool-three"
    assert rows[2]["status"] == "skipped"
    assert rows[2]["bio_tools_url"] == "https://bio.tools/api/tool/tool-three"
    assert "already exists" in rows[2]["error"]

    # Check second uploaded entry also has URL
    assert rows[3]["biotoolsID"] == "tool-four"
    assert rows[3]["status"] == "uploaded"
    assert rows[3]["bio_tools_url"] == "https://bio.tools/api/tool/tool-four"
