from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from astra.twitter.client import (
    TwitterAuthError,
    TwitterClient,
    TwitterError,
    TwitterRateLimitError,
)

API_BASE = "https://api.twitter.com/2"


@pytest.fixture()
def tw_client() -> TwitterClient:
    return TwitterClient(
        api_key="ck",
        api_secret="cs",
        access_token="at",
        access_secret="as",
        bearer_token="bt",
    )


def _user_me_response(user_id: str = "12345") -> dict:
    return {"data": {"id": user_id}}


def _tweet_response(tweet_id: str = "t1", text: str = "Hello") -> dict:
    return {"data": {"id": tweet_id, "text": text}}


class TestPostTweet:
    @respx.mock
    async def test_post_tweet_success(self, tw_client: TwitterClient) -> None:
        respx.get(f"{API_BASE}/users/me").mock(
            return_value=httpx.Response(200, json=_user_me_response())
        )
        respx.post(f"{API_BASE}/tweets").mock(
            return_value=httpx.Response(201, json=_tweet_response("t42", "Hello!"))
        )

        async with tw_client:
            tweet = await tw_client.post_tweet("Hello!")

        assert tweet.id == "t42"
        assert tweet.text == "Hello!"

    @respx.mock
    async def test_post_tweet_exceeds_280_raises(self, tw_client: TwitterClient) -> None:
        async with tw_client:
            with pytest.raises(TwitterError, match="280"):
                await tw_client.post_tweet("x" * 281)

    @respx.mock
    async def test_post_tweet_reply_to(self, tw_client: TwitterClient) -> None:
        respx.get(f"{API_BASE}/users/me").mock(
            return_value=httpx.Response(200, json=_user_me_response())
        )

        posted_body: dict = {}

        def capture_request(request: httpx.Request) -> httpx.Response:
            import json

            posted_body.update(json.loads(request.content))
            return httpx.Response(201, json=_tweet_response("t99", "Reply"))

        respx.post(f"{API_BASE}/tweets").mock(side_effect=capture_request)

        async with tw_client:
            await tw_client.post_tweet("Reply", reply_to="original_id")

        assert posted_body["reply"]["in_reply_to_tweet_id"] == "original_id"


class TestSearchRecent:
    @respx.mock
    async def test_search_recent_returns_tweets(self, tw_client: TwitterClient) -> None:
        respx.get(f"{API_BASE}/tweets/search/recent").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "t1", "text": "Tweet 1", "author_id": "a1"},
                        {"id": "t2", "text": "Tweet 2", "author_id": "a2"},
                    ],
                    "meta": {"result_count": 2},
                },
            )
        )

        async with tw_client:
            result = await tw_client.search_recent("test query")

        assert len(result.tweets) == 2
        assert result.tweets[0].id == "t1"

    @respx.mock
    async def test_search_recent_empty(self, tw_client: TwitterClient) -> None:
        respx.get(f"{API_BASE}/tweets/search/recent").mock(
            return_value=httpx.Response(200, json={"meta": {"result_count": 0}})
        )

        async with tw_client:
            result = await tw_client.search_recent("no results")

        assert result.tweets == []


class TestErrorHandling:
    @respx.mock
    async def test_401_raises_auth_error(self, tw_client: TwitterClient) -> None:
        respx.get(f"{API_BASE}/users/me").mock(
            return_value=httpx.Response(401, text="Unauthorized")
        )

        async with tw_client:
            with pytest.raises(TwitterAuthError):
                await tw_client.health_check()

    @respx.mock
    async def test_429_raises_rate_limit_error(self, tw_client: TwitterClient) -> None:
        reset_ts = str(int(datetime(2026, 1, 1, tzinfo=UTC).timestamp()))
        respx.get(f"{API_BASE}/users/me").mock(
            return_value=httpx.Response(
                429,
                text="Rate limited",
                headers={"x-rate-limit-reset": reset_ts},
            )
        )

        async with tw_client:
            with pytest.raises(TwitterRateLimitError) as exc_info:
                await tw_client.health_check()
            assert exc_info.value.reset_at is not None


class TestLikeTweet:
    @respx.mock
    async def test_like_tweet_success(self, tw_client: TwitterClient) -> None:
        respx.get(f"{API_BASE}/users/me").mock(
            return_value=httpx.Response(200, json=_user_me_response("u1"))
        )
        respx.post(f"{API_BASE}/users/u1/likes").mock(
            return_value=httpx.Response(200, json={"data": {"liked": True}})
        )

        async with tw_client:
            result = await tw_client.like_tweet("tweet_123")

        assert result is True
