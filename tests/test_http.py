"""Unit tests for http utility module and retry logic."""

import unittest
from unittest.mock import MagicMock, call, patch

import requests
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import ReadTimeout, ConnectTimeout

from ff_manager.http import (
    DEFAULT_BACKOFF_FACTOR,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    request_with_retry,
)


class TestRequestWithRetry(unittest.TestCase):
    def setUp(self):
        self.mock_session = MagicMock()

    def test_request_success_first_attempt(self):
        mock_resp = MagicMock(status_code=200)
        self.mock_session.get.return_value = mock_resp

        resp = request_with_retry(
            session=self.mock_session,
            method="GET",
            url="https://api.sleeper.app/v1/user/123",
            timeout=10,
            max_retries=3,
        )

        self.assertEqual(resp, mock_resp)
        self.assertEqual(self.mock_session.get.call_count, 1)
        self.mock_session.get.assert_called_once_with(
            "https://api.sleeper.app/v1/user/123", timeout=10
        )

    @patch("time.sleep")
    def test_request_retries_on_read_timeout_and_succeeds(self, mock_sleep):
        mock_resp = MagicMock(status_code=200)
        self.mock_session.get.side_effect = [
            ReadTimeout("HTTPSConnectionPool: Read timed out. (read timeout=10)"),
            mock_resp,
        ]

        resp = request_with_retry(
            session=self.mock_session,
            method="GET",
            url="https://api.sleeper.app/v1/league/123/rosters",
            timeout=30,
            max_retries=3,
            backoff_factor=1.0,
            platform_name="Sleeper",
        )

        self.assertEqual(resp, mock_resp)
        self.assertEqual(self.mock_session.get.call_count, 2)
        mock_sleep.assert_called_once_with(1.0)

    @patch("time.sleep")
    def test_request_retries_on_connect_timeout_and_succeeds(self, mock_sleep):
        mock_resp = MagicMock(status_code=200)
        self.mock_session.get.side_effect = [
            ConnectTimeout("Connection timed out"),
            mock_resp,
        ]

        resp = request_with_retry(
            session=self.mock_session,
            method="GET",
            url="https://fantasy.espn.com/apis/v3/games/ffl",
            timeout=30,
            max_retries=3,
            backoff_factor=0.5,
            platform_name="ESPN",
        )

        self.assertEqual(resp, mock_resp)
        self.assertEqual(self.mock_session.get.call_count, 2)
        mock_sleep.assert_called_once_with(0.5)

    @patch("time.sleep")
    def test_request_retries_on_connection_error_and_succeeds(self, mock_sleep):
        mock_resp = MagicMock(status_code=200)
        self.mock_session.get.side_effect = [
            RequestsConnectionError("Connection reset by peer"),
            mock_resp,
        ]

        resp = request_with_retry(
            session=self.mock_session,
            method="GET",
            url="https://api.sleeper.app/v1/state/nfl",
            timeout=15,
            max_retries=3,
            backoff_factor=1.0,
        )

        self.assertEqual(resp, mock_resp)
        self.assertEqual(self.mock_session.get.call_count, 2)
        mock_sleep.assert_called_once_with(1.0)

    @patch("time.sleep")
    def test_request_fails_after_max_retries_with_read_timeout(self, mock_sleep):
        timeout_err = ReadTimeout("HTTPSConnectionPool: Read timed out. (read timeout=10)")
        self.mock_session.get.side_effect = timeout_err

        with self.assertRaises(ReadTimeout) as ctx:
            request_with_retry(
                session=self.mock_session,
                method="GET",
                url="https://api.sleeper.app/v1/league/123/rosters",
                timeout=10,
                max_retries=3,
                backoff_factor=1.0,
                platform_name="Sleeper",
            )

        self.assertIn("Read timed out", str(ctx.exception))
        self.assertEqual(self.mock_session.get.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)
        mock_sleep.assert_has_calls([call(1.0), call(2.0)])

    @patch("time.sleep")
    def test_request_retries_on_500_502_503_504_429(self, mock_sleep):
        for status in [429, 500, 502, 503, 504]:
            self.mock_session.reset_mock()
            mock_sleep.reset_mock()

            error_resp = MagicMock(status_code=status)
            ok_resp = MagicMock(status_code=200)
            self.mock_session.get.side_effect = [error_resp, ok_resp]

            resp = request_with_retry(
                session=self.mock_session,
                method="GET",
                url="https://api.sleeper.app/v1/league/123",
                timeout=30,
                max_retries=3,
                backoff_factor=1.0,
            )

            self.assertEqual(resp, ok_resp)
            self.assertEqual(self.mock_session.get.call_count, 2)
            mock_sleep.assert_called_once_with(1.0)

    @patch("time.sleep")
    def test_request_does_not_retry_non_transient_status_codes(self, mock_sleep):
        for status in [400, 401, 403, 404]:
            self.mock_session.reset_mock()
            mock_sleep.reset_mock()

            error_resp = MagicMock(status_code=status)
            self.mock_session.get.return_value = error_resp

            resp = request_with_retry(
                session=self.mock_session,
                method="GET",
                url="https://api.sleeper.app/v1/league/123",
                timeout=30,
                max_retries=3,
            )

            self.assertEqual(resp, error_resp)
            self.assertEqual(self.mock_session.get.call_count, 1)
            mock_sleep.assert_not_called()

    @patch("time.sleep")
    def test_request_post_method_and_retry(self, mock_sleep):
        mock_resp = MagicMock(status_code=200)
        self.mock_session.post.side_effect = [
            ReadTimeout("POST read timeout"),
            mock_resp,
        ]

        resp = request_with_retry(
            session=self.mock_session,
            method="POST",
            url="https://sleeper.app/graphql",
            json={"query": "mutation {}"},
            timeout=30,
            max_retries=2,
            backoff_factor=2.0,
        )

        self.assertEqual(resp, mock_resp)
        self.assertEqual(self.mock_session.post.call_count, 2)
        mock_sleep.assert_called_once_with(2.0)

    def test_session_none_raises_runtime_error(self):
        with self.assertRaises(RuntimeError):
            request_with_retry(
                session=None,
                method="GET",
                url="https://api.sleeper.app/v1/state/nfl",
            )


if __name__ == "__main__":
    unittest.main()
