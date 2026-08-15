"""Unit tests for EmailNotifier using standard unittest."""

import unittest
from unittest.mock import MagicMock, patch

from ff_manager.models import ActionResult, Player, SwapDecision
from ff_manager.notifications.notifier import EmailNotifier


class TestEmailNotifier(unittest.TestCase):
    def test_notifier_should_send_email(self):
        notifier = EmailNotifier(
            smtp_host="smtp.test.com",
            smtp_user="user@test.com",
            smtp_password="pwd",
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

        # With FAILURE but no swap
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
        self.assertFalse(notifier.should_send_email(failed_results))

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
        self.assertIn("Champions League", text_report)
        self.assertIn("ESPN", text_report)
        self.assertIn("RB: Injured Star (Out): 0 <-> Backup Beast: 14.5", text_report)

        html_report = notifier.build_html_report(results)
        self.assertIn("Fantasy Lineup Auto-Manager Report", html_report)
        self.assertIn("RB: Injured Star (Out): 0 &lt;-&gt; Backup Beast: 14.5", html_report.replace("<->", "&lt;-&gt;"))
        self.assertIn("Backup Beast: 14.5", html_report)

    @patch("smtplib.SMTP")
    def test_send_summary_smtp(self, mock_smtp_class):
        mock_server = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_server

        notifier = EmailNotifier(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            smtp_user="me@gmail.com",
            smtp_password="password",
            email_to="me@gmail.com",
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
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("me@gmail.com", "password")
        mock_server.send_message.assert_called_once()


if __name__ == "__main__":
    unittest.main()
