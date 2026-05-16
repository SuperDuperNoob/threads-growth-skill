import pytest
from unittest.mock import patch, MagicMock
from orbit.platforms.linkedin import LinkedInClient

@pytest.fixture
def client():
    return LinkedInClient(access_token="test-token")

def test_client_requires_token():
    with pytest.raises(ValueError):
        LinkedInClient(access_token=None)

def test_get_posts_returns_list(client):
    mock_response = {
        "elements": [
            {
                "id": "urn:li:share:123",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": "Test post content"}
                    }
                },
                "created": {"time": 1700000000000},
            }
        ]
    }
    with patch.object(client._http, "get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: mock_response,
            raise_for_status=lambda: None,
        )
        posts = client.get_posts(author_urn="urn:li:person:abc")
    assert len(posts) == 1
    assert posts[0]["external_id"] == "urn:li:share:123"
    assert posts[0]["platform"] == "linkedin"

def test_get_metrics_returns_dict(client):
    mock_response = {
        "elements": [
            {
                "share": "urn:li:share:123",
                "organizationalEntity": "urn:li:person:abc",
                "totalShareStatistics": {
                    "impressionCount": 1500,
                    "likeCount": 42,
                    "commentCount": 7,
                    "shareCount": 3,
                    "clickCount": 89,
                }
            }
        ]
    }
    with patch.object(client._http, "get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: mock_response,
            raise_for_status=lambda: None,
        )
        metrics = client.get_metrics(["urn:li:share:123"])
    assert metrics["urn:li:share:123"]["views"] == 1500
    assert metrics["urn:li:share:123"]["likes"] == 42
