import pytest
from app.agents.json_agent import process_json

def test_process_json_valid():
    payload = b'''
    {
        "id": "abc123",
        "event": "signup",
        "timestamp": "2025-06-01T12:00:00Z"
    }
    '''
    result = process_json(payload)
    assert result["anomaly"] is False
    assert result["missing_fields"] is None
    assert result["data"]["id"] == "abc123"

def test_process_json_missing_fields():
    payload = b'''
    {
        "event": "signup",
        "timestamp": "2025-06-01T12:00:00Z"
    }
    '''
    result = process_json(payload)
    assert result["anomaly"] is True
    assert "id" in result["missing_fields"]
