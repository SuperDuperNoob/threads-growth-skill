import pytest
from unittest.mock import patch, MagicMock
from orbit.platforms.youtube import YouTubeClient

@pytest.fixture
def client():
    return YouTubeClient(api_key="test-key", channel_id="UC123")

def test_client_requires_api_key():
    with pytest.raises(ValueError):
        YouTubeClient(api_key=None, channel_id="UC123")

def test_get_videos_returns_list(client):
    mock_search = {
        "items": [{"id": {"videoId": "vid123"}}]
    }
    mock_details = {
        "items": [{
            "id": "vid123",
            "snippet": {"title": "Test Video", "publishedAt": "2026-01-01T00:00:00Z"},
            "statistics": {"viewCount": "5000", "likeCount": "200", "commentCount": "30"},
        }]
    }
    with patch.object(client._http, "get") as mock_get:
        mock_get.side_effect = [
            MagicMock(status_code=200, json=lambda: mock_search, raise_for_status=lambda: None),
            MagicMock(status_code=200, json=lambda: mock_details, raise_for_status=lambda: None),
        ]
        videos = client.get_videos()
    assert len(videos) == 1
    assert videos[0]["external_id"] == "vid123"
    assert videos[0]["platform"] == "youtube"

def test_get_metrics_from_video_list(client):
    videos = [{
        "external_id": "vid123",
        "views": 5000,
        "likes": 200,
        "comments": 30,
    }]
    metrics = client.extract_metrics(videos)
    assert metrics["vid123"]["views"] == 5000
