"""Unit tests for ResendEmailClient and EmailNotifier."""

import os
import unittest
from unittest.mock import MagicMock, patch

import resend.exceptions

from ff_manager.interfaces import EmailClient
from ff_manager.models import ActionResult, Player, SwapDecision
from ff_manager.notifications.backends import ResendEmailClient
from ff_manager.notifications.notifier import EmailNotifier


class TestResendEmailClient(unittest.TestCase):
    """Tests for ResendEmailClient delivery backend."""

    def test_is_configured_true_when_api_key_set(self):
        client = ResendEmailClient(api_key="re_123456")
        self.assertTrue(client.is_configured)

    def test_is_configured_false_when_no_api_key(self):
        with patch.dict(os.environ, {}, clear=True):
            client = ResendEmailClient(api_key=None)
            self.assertFalse(client.is_configured)

    @patch("resend.Emails.send")
    def test_send_email_success(self, mock_send):
        mock_send.return_value = {"id": "msg_abc123"}
        client = ResendEmailClient(api_key="re_test_key", default_from="bot@test.com")

        sent = client.send_email(
            to="user@example.com",
            subject="Test Subject",
            html_content="<p>Hello</p>",
            text_content="Hello",
        )

        self.assertTrue(sent)
        mock_send.assert_called_once_with(
            {
                "from": "bot@test.com",
                "to": ["user@example.com"],
                "subject": "Test Subject",
                "html": "<p>Hello</p>",
                "text": "Hello",
            }
        )

    @patch("resend.Emails.send")
    def test_send_email_with_multiple_recipients_and_custom_from(self, mock_send):
        mock_send.return_value = {"id": "msg_xyz789"}
        client = ResendEmailClient(api_key="re_test_key", default_from="default@test.com")

        sent = client.send_email(
            to=["user1@example.com", "user2@example.com"],
            subject="Multi Alert",
            html_content="<p>Alert</p>",
            from_email="custom@test.com",
        )

        self.assertTrue(sent)
        mock_send.assert_called_once_with(
            {
                "from": "custom@test.com",
                "to": ["user1@example.com", "user2@example.com"],
                "subject": "Multi Alert",
                "html": "<p>Alert</p>",
            }
        )

    def test_send_email_skipped_when_unconfigured(self):
        with patch.dict(os.environ, {}, clear=True):
            client = ResendEmailClient(api_key=None)
            sent = client.send_email(
                to="user@example.com",
                subject="Test",
                html_content="<p>Test</p>",
            )
            self.assertFalse(sent)

    @patch("resend.Emails.send")
    def test_send_email_handles_resend_error(self, mock_send):
        mock_send.side_effect = resend.exceptions.ResendError(
            code=401,
            error_type="invalid_api_key",
            message="Invalid API Key",
            suggested_action="Please provide a valid API key.",
        )
        client = ResendEmailClient(api_key="re_invalid")

        sent = client.send_email(
            to="user@example.com",
            subject="Test",
            html_content="<p>Test</p>",
        )

        self.assertFalse(sent)

    @patch("resend.Emails.send")
    def test_send_email_handles_generic_exception(self, mock_send):
        mock_send.side_effect = ConnectionError("Network unreachable")
        client = ResendEmailClient(api_key="re_test")

        sent = client.send_email(
            to="user@example.com",
            subject="Test",
            html_content="<p>Test</p>",
        )

        self.assertFalse(sent)


class TestEmailNotifier(unittest.TestCase):
    """Tests for EmailNotifier formatting and dispatching."""

    def test_notifier_should_send_email(self):
        notifier = EmailNotifier(
            api_key="re_test",
            email_to="recipient@test.com",
        )

        # Only NO_ACTION_NEEDED
        no_action_results = [
            ActionResult(
                league_id="1",
                league_name="L1",
                platform="Sleeper",
                team_id="T1",
                team_name="Team 1",
                status="NO_ACTION_NEEDED",
                message="All healthy",
            )
        ]
        self.assertFalse(notifier.should_send_email(no_action_results))

        # With SUCCESS swap
        swap = SwapDecision(
            starter=Player("1", "P1", "WR", "WR", ["WR"], "OUT", 0.0),
            replacement=Player("2", "P2", "WR", "BE", ["WR"], "ACTIVE", 12.0),
            slot="WR",
            reason="Injury: OUT",
        )
        success_results = [
            ActionResult(
                league_id="1",
                league_name="L1",
                platform="Sleeper",
                team_id="T1",
                team_name="Team 1",
                status="SUCCESS",
                message="Swapped",
                swap=swap,
            )
        ]
        self.assertTrue(notifier.should_send_email(success_results))

        # With FAILURE but no swap -> Should alert user
        failed_results = [
            ActionResult(
                league_id="1",
                league_name="L1",
                platform="ESPN",
                team_id="T1",
                team_name="Team 1",
                status="FAILED",
                message="Auth error",
                error="Token expired",
            )
        ]
        self.assertTrue(notifier.should_send_email(failed_results))

    def test_html_and_text_report_generation(self):
        notifier = EmailNotifier()
        swap = SwapDecision(
            starter=Player("1", "Injured Star", "RB", "RB", ["RB"], "OUT", 0.0),
            replacement=Player("2", "Backup Beast", "RB", "BE", ["RB"], "ACTIVE", 14.5),
            slot="RB",
            reason="Injury: OUT",
        )
        results = [
            ActionResult(
                league_id="101",
                league_name="Champions League",
                platform="ESPN",
                team_id="1",
                team_name="Top Dogs",
                status="SUCCESS",
                message="Swapped",
                swap=swap,
            )
        ]

        text_report = notifier.build_text_report(results)
        self.assertIn("FANTASY FOOTBALL AUTO-MANAGER REPORT", text_report)
        self.assertIn("ESPN - Champions League - Top Dogs", text_report)
        self.assertIn("RB: Injured Star (Out): 0 <-> Backup Beast: 14.5", text_report)

        html_report = notifier.build_html_report(results)
        self.assertIn("Fantasy Lineup Auto-Manager Report", html_report)
        self.assertIn("ESPN - Champions League - Top Dogs", html_report)
        self.assertIn("RB: Injured Star (Out): 0 &lt;-&gt; Backup Beast: 14.5", html_report.replace("<->", "&lt;-&gt;"))
        self.assertIn("Backup Beast: 14.5", html_report)

    def test_grouping_multiple_swaps_under_single_header(self):
        notifier = EmailNotifier()
        swap1 = SwapDecision(
            starter=Player("1", "P1", "WR", "WR", ["WR"], "OUT", 0.0),
            replacement=Player("2", "P2", "WR", "BE", ["WR"], "ACTIVE", 12.0),
            slot="WR",
            reason="Injury: OUT",
        )
        swap2 = SwapDecision(
            starter=Player("3", "P3", "QB", "QB", ["QB"], "OUT", 0.0),
            replacement=Player("4", "P4", "QB", "BE", ["QB"], "ACTIVE", 18.0),
            slot="QB",
            reason="Injury: OUT",
        )
        results = [
            ActionResult(
                league_id="1",
                league_name="ILLest League",
                platform="Sleeper",
                team_id="T1",
                team_name="Ben Johnson Glazer",
                status="SUCCESS",
                message="Swapped WR",
                swap=swap1,
            ),
            ActionResult(
                league_id="1",
                league_name="ILLest League",
                platform="Sleeper",
                team_id="T1",
                team_name="Ben Johnson Glazer",
                status="SUCCESS",
                message="Swapped QB",
                swap=swap2,
            ),
        ]

        html_report = notifier.build_html_report(results)
        self.assertEqual(html_report.count("Sleeper - ILLest League - Ben Johnson Glazer"), 1)
        self.assertIn("WR: P1 (Out): 0", html_report)
        self.assertIn("QB: P3 (Out): 0", html_report)

    @patch("resend.Emails.send")
    def test_send_summary_with_resend(self, mock_send):
        mock_send.return_value = {"id": "msg_summary123"}

        notifier = EmailNotifier(
            api_key="re_test_key",
            email_to="me@gmail.com",
            email_from="bot@domain.com",
        )

        swap = SwapDecision(
            starter=Player("1", "P1", "WR", "WR", ["WR"], "OUT", 0.0),
            replacement=Player("2", "P2", "WR", "BE", ["WR"], "ACTIVE", 10.0),
            slot="WR",
            reason="Injury: OUT",
        )
        results = [
            ActionResult(
                league_id="1",
                league_name="L1",
                platform="Sleeper",
                team_id="T1",
                team_name="Team 1",
                status="SUCCESS",
                message="Swapped",
                swap=swap,
            )
        ]

        sent = notifier.send_summary(results)
        self.assertTrue(sent)
        mock_send.assert_called_once()
        params = mock_send.call_args[0][0]
        self.assertEqual(params["to"], ["me@gmail.com"])
        self.assertEqual(params["from"], "bot@domain.com")
        self.assertIn("Fantasy Lineup Auto-Manager Action Report", params["subject"])

    @patch("resend.Emails.send")
    def test_send_summary_dry_run_and_force(self, mock_send):
        mock_send.return_value = {"id": "msg_dry123"}

        notifier = EmailNotifier(
            api_key="re_test_key",
            email_to="me@gmail.com",
            email_from="bot@domain.com",
        )

        sent = notifier.send_summary(results=[], force=True, dry_run=True)
        self.assertTrue(sent)
        mock_send.assert_called_once()
        params = mock_send.call_args[0][0]
        self.assertTrue(params["subject"].startswith("[DRY RUN]"))

    def test_is_all_clear_with_healthy_results(self):
        notifier = EmailNotifier()
        results = [
            ActionResult(
                league_id="1", league_name="L1", platform="Sleeper",
                team_id="T1", team_name="Team 1",
                status="NO_ACTION_NEEDED", message="All healthy",
            ),
            ActionResult(
                league_id="2", league_name="L2", platform="ESPN",
                team_id="T2", team_name="Team 2",
                status="SKIPPED", message="Pre-draft",
            ),
        ]
        self.assertTrue(notifier.is_all_clear(results))

    def test_is_all_clear_false_with_failures(self):
        notifier = EmailNotifier()
        results = [
            ActionResult(
                league_id="1", league_name="L1", platform="Sleeper",
                team_id="T1", team_name="Team 1",
                status="NO_ACTION_NEEDED", message="All healthy",
            ),
            ActionResult(
                league_id="2", league_name="L2", platform="ESPN",
                team_id="T2", team_name="Team 2",
                status="FAILED", message="Auth error", error="Token expired",
            ),
        ]
        self.assertFalse(notifier.is_all_clear(results))

    def test_is_all_clear_false_with_swaps(self):
        notifier = EmailNotifier()
        swap = SwapDecision(
            starter=Player("1", "P1", "WR", "WR", ["WR"], "OUT", 0.0),
            replacement=Player("2", "P2", "WR", "BE", ["WR"], "ACTIVE", 12.0),
            slot="WR", reason="Injury: OUT",
        )
        results = [
            ActionResult(
                league_id="1", league_name="L1", platform="Sleeper",
                team_id="T1", team_name="Team 1",
                status="SUCCESS", message="Swapped", swap=swap,
            ),
        ]
        self.assertFalse(notifier.is_all_clear(results))

    def test_is_all_clear_false_with_empty_results(self):
        notifier = EmailNotifier()
        self.assertFalse(notifier.is_all_clear([]))

    def test_build_all_clear_text_report(self):
        notifier = EmailNotifier()
        results = [
            ActionResult(
                league_id="1", league_name="Champions League",
                platform="ESPN", team_id="T1", team_name="Top Dogs",
                status="NO_ACTION_NEEDED",
                message="All starters are healthy and scheduled to play.",
            ),
            ActionResult(
                league_id="2", league_name="ILLest League",
                platform="Sleeper", team_id="T2", team_name="Ben Johnson Glazer",
                status="NO_ACTION_NEEDED",
                message="All starters are healthy and scheduled to play.",
            ),
        ]
        text = notifier.build_all_clear_text_report(results)
        self.assertIn("SUNDAY ALL CLEAR", text)
        self.assertIn("ESPN - Champions League - Top Dogs", text)
        self.assertIn("Sleeper - ILLest League - Ben Johnson Glazer", text)
        self.assertIn("All lineups are set. No action required.", text)

    def test_build_all_clear_html_report(self):
        notifier = EmailNotifier()
        results = [
            ActionResult(
                league_id="1", league_name="Champions League",
                platform="ESPN", team_id="T1", team_name="Top Dogs",
                status="NO_ACTION_NEEDED",
                message="All starters are healthy and scheduled to play.",
            ),
        ]
        html = notifier.build_all_clear_html_report(results)
        self.assertIn("Sunday All Clear", html)
        self.assertIn("ESPN - Champions League - Top Dogs", html)
        self.assertIn("#22c55e", html)
        self.assertIn("Enjoy the games!", html)

    @patch("resend.Emails.send")
    def test_send_all_clear_sends_when_healthy(self, mock_send):
        mock_send.return_value = {"id": "msg_all_clear123"}

        notifier = EmailNotifier(
            api_key="re_test_key",
            email_to="me@gmail.com",
            email_from="bot@domain.com",
        )
        results = [
            ActionResult(
                league_id="1", league_name="L1", platform="Sleeper",
                team_id="T1", team_name="Team 1",
                status="NO_ACTION_NEEDED", message="All healthy",
            ),
        ]
        sent = notifier.send_all_clear(results)
        self.assertTrue(sent)
        mock_send.assert_called_once()
        params = mock_send.call_args[0][0]
        self.assertIn("All Clear", params["subject"])

    @patch("resend.Emails.send")
    def test_send_all_clear_dry_run(self, mock_send):
        mock_send.return_value = {"id": "msg_all_clear_dry"}

        notifier = EmailNotifier(
            api_key="re_test_key",
            email_to="me@gmail.com",
            email_from="bot@domain.com",
        )
        results = [
            ActionResult(
                league_id="1", league_name="L1", platform="Sleeper",
                team_id="T1", team_name="Team 1",
                status="NO_ACTION_NEEDED", message="All healthy",
            ),
        ]
        sent = notifier.send_all_clear(results, dry_run=True)
        self.assertTrue(sent)
        mock_send.assert_called_once()
        params = mock_send.call_args[0][0]
        self.assertTrue(params["subject"].startswith("[DRY RUN]"))

    @patch("resend.Emails.send")
    def test_send_all_clear_skips_when_problems_exist(self, mock_send):
        notifier = EmailNotifier(
            api_key="re_test_key",
            email_to="me@gmail.com",
            email_from="bot@domain.com",
        )
        results = [
            ActionResult(
                league_id="1", league_name="L1", platform="ESPN",
                team_id="T1", team_name="Team 1",
                status="FAILED", message="Auth error", error="Token expired",
            ),
        ]
        sent = notifier.send_all_clear(results)
        self.assertFalse(sent)
        mock_send.assert_not_called()

    def test_notifier_should_send_email_on_empty_slot_no_replacement(self):
        notifier = EmailNotifier(
            api_key="re_test_key",
            email_to="recipient@test.com",
        )
        results = [
            ActionResult(
                league_id="s3",
                league_name="Shadynasty",
                platform="Sleeper",
                team_id="t3",
                team_name="Team 3",
                status="NO_REPLACEMENT",
                message="No valid bench replacement found for [Empty K] (K, Slot: K, Empty starting slot).",
            )
        ]
        self.assertTrue(notifier.should_send_email(results))

    def test_notifier_should_send_email_on_locked_starter_error(self):
        notifier = EmailNotifier(
            api_key="re_test_key",
            email_to="recipient@test.com",
        )
        results = [
            ActionResult(
                league_id="1",
                league_name="L1",
                platform="Sleeper",
                team_id="T1",
                team_name="Team 1",
                status="SKIPPED",
                message="Starter Keenan Allen (WR) is locked (Injury: OUT).",
                error="Starter Keenan Allen is locked and cannot be swapped (Injury: OUT).",
            )
        ]
        self.assertTrue(notifier.should_send_email(results))
        self.assertFalse(notifier.is_all_clear(results))

    @patch("resend.Emails.send")
    def test_send_summary_sends_alert_on_no_replacement(self, mock_send):
        mock_send.return_value = {"id": "msg_alert123"}

        notifier = EmailNotifier(
            api_key="re_test_key",
            email_to="me@gmail.com",
            email_from="bot@domain.com",
        )
        results = [
            ActionResult(
                league_id="s3",
                league_name="Shadynasty",
                platform="Sleeper",
                team_id="t3",
                team_name="Team 3",
                status="NO_REPLACEMENT",
                message="No valid bench replacement found for [Empty K] (K, Slot: K, Empty starting slot).",
            )
        ]
        sent = notifier.send_summary(results)
        self.assertTrue(sent)
        mock_send.assert_called_once()
        params = mock_send.call_args[0][0]
        self.assertIn("Action/Alert", params["subject"])

    def test_custom_email_client_injection(self):
        """Verify that any custom EmailClient backend can be injected and used seamlessly."""
        mock_client = MagicMock(spec=EmailClient)
        mock_client.is_configured = True
        mock_client.send_email.return_value = True

        notifier = EmailNotifier(
            client=mock_client,
            email_to="custom@test.com",
            email_from="custom_sender@test.com",
        )

        self.assertTrue(notifier.is_configured)
        results = [
            ActionResult(
                league_id="1",
                league_name="L1",
                platform="ESPN",
                team_id="T1",
                team_name="Team 1",
                status="SUCCESS",
                message="Swapped",
                swap=SwapDecision(
                    starter=Player("1", "P1", "WR", "WR", ["WR"], "OUT", 0.0),
                    replacement=Player("2", "P2", "WR", "BE", ["WR"], "ACTIVE", 10.0),
                    slot="WR",
                    reason="Injury: OUT",
                ),
            )
        ]

        sent = notifier.send_summary(results)
        self.assertTrue(sent)
        mock_client.send_email.assert_called_once()
        kwargs = mock_client.send_email.call_args[1]
        self.assertEqual(kwargs["to"], "custom@test.com")
        self.assertEqual(kwargs["from_email"], "custom_sender@test.com")


if __name__ == "__main__":
    unittest.main()
