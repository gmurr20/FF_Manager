import logging
import os
from typing import List, Optional

from ff_manager.interfaces import EmailClient
from ff_manager.models import ActionResult, SwapDecision
from ff_manager.notifications.backends import ResendEmailClient

logger = logging.getLogger(__name__)


class EmailNotifier:
    """Compiles execution action logs into clean HTML/Text email summaries and dispatches via an EmailClient."""

    def __init__(
        self,
        client: Optional[EmailClient] = None,
        email_to: Optional[str] = None,
        email_from: Optional[str] = None,
        api_key: Optional[str] = None,
        # Legacy parameters retained for gentle backward compatibility if passed as kwargs
        **kwargs,
    ):
        if client is not None:
            self.client = client
        else:
            self.client = ResendEmailClient(
                api_key=api_key or os.environ.get("RESEND_API_KEY"),
                default_from=email_from,
            )
        self.email_to = (
            email_to
            or os.environ.get("NOTIFICATION_EMAIL_TO")
            or os.environ.get("RESEND_TO_EMAIL")
        )
        self.email_from = (
            email_from
            or getattr(self.client, "default_from", None)
            or os.environ.get("NOTIFICATION_EMAIL_FROM")
            or "onboarding@resend.dev"
        )

    @property
    def is_configured(self) -> bool:
        """Check if email backend and recipient are configured."""
        return bool(self.client and self.client.is_configured and self.email_to)

    def should_send_email(self, results: List[ActionResult]) -> bool:
        """
        Determine if an email should be sent.
        Sends if a roster change was made OR if any errors/failures occurred.
        """
        for r in results:
            if r.swap is not None and "SUCCESS" in r.status.upper():
                return True
            if r.error or r.status.upper() in ("FAILED", "ERROR", "NO_REPLACEMENT"):
                return True
        return False

    @staticmethod
    def format_swap_line(swap: SwapDecision) -> str:
        """
        Format a swap decision in a clean, concise line:
        WR: Keenan Allen (Out): 0 <-> Malik Nabers: 10.3
        """
        # Starter representation
        if swap.starter.is_empty:
            starter_str = "[Empty Slot]"
        else:
            status = swap.starter.injury_status or "Inactive"
            pts = swap.starter.projected_points
            pts_str = f"{int(pts)}" if pts == int(pts) else f"{pts:.1f}"
            starter_str = f"{swap.starter.name} ({status.capitalize()}): {pts_str}"

        # Replacement representation
        repl_pts = swap.replacement.projected_points
        repl_pts_str = f"{int(repl_pts)}" if repl_pts == int(repl_pts) else f"{repl_pts:.1f}"
        replacement_str = f"{swap.replacement.name}: {repl_pts_str}"

        return f"{swap.slot}: {starter_str} <-> {replacement_str}"

    @staticmethod
    def format_team_header(platform: str, league_name: str, team_name: Optional[str]) -> str:
        """Format team section header: 'Platform - League Name - Team Name'."""
        clean_league = (league_name or "").strip()
        clean_team = (team_name or "").strip()
        if clean_team and clean_team != clean_league:
            return f"{platform} - {clean_league} - {clean_team}"
        return f"{platform} - {clean_league}"

    @staticmethod
    def _group_results_by_team(results: List[ActionResult]):
        """Group action results by (platform, league_id, league_name, team_id, team_name)."""
        groups = {}
        for r in results:
            key = (r.platform, r.league_id, r.league_name, r.team_id, r.team_name)
            if key not in groups:
                groups[key] = []
            groups[key].append(r)
        return groups

    def build_text_report(self, results: List[ActionResult]) -> str:
        """Format plain-text summary report grouped by team."""
        lines = [
            "==================================================",
            "        FANTASY FOOTBALL AUTO-MANAGER REPORT      ",
            "==================================================",
            "",
        ]

        if not results:
            lines.append("No leagues evaluated.")
            return "\n".join(lines)

        grouped = self._group_results_by_team(results)

        for (platform, lid, league_name, tid, team_name), team_results in grouped.items():
            header = self.format_team_header(platform, league_name, team_name)

            swaps = [r for r in team_results if r.swap is not None]
            non_swaps = [r for r in team_results if r.swap is None]

            # Determine if this team has any issues
            team_has_issues = any(
                r.swap is not None
                or r.error
                or r.status.upper() in ("FAILED", "ERROR", "NO_REPLACEMENT")
                for r in team_results
            )

            if team_has_issues:
                lines.append(f"🚨 {header}")
            else:
                lines.append(f"✅ {header}")

            for r in swaps:
                is_failed = "FAIL" in r.status.upper() or "ERROR" in r.status.upper()
                prefix = "  ❌ [FAILED]" if is_failed else "  •"
                lines.append(f"{prefix} {self.format_swap_line(r.swap)}")
                if r.error:
                    lines.append(f"     Reason: {r.error}")

            for r in non_swaps:
                is_problem = r.error or r.status.upper() in ("FAILED", "ERROR", "NO_REPLACEMENT")
                if is_problem:
                    lines.append(f"  ⚠️  {r.message}")
                    if r.error:
                        lines.append(f"     Error: {r.error}")
                else:
                    lines.append(f"  {r.message}")

            lines.append("")

        lines.append("==================================================")
        return "\n".join(lines)

    def build_html_report(self, results: List[ActionResult]) -> str:
        """Format clean, modern HTML email report grouped by team."""
        if not results:
            return "<p>No leagues evaluated.</p>"

        grouped = self._group_results_by_team(results)
        leagues_html = []

        for (platform, lid, league_name, tid, team_name), team_results in grouped.items():
            header = self.format_team_header(platform, league_name, team_name)
            swaps = [r for r in team_results if r.swap is not None]
            non_swaps = [r for r in team_results if r.swap is None]

            # Determine if this team has any issues
            team_has_issues = any(
                r.swap is not None
                or r.error
                or r.status.upper() in ("FAILED", "ERROR", "NO_REPLACEMENT")
                for r in team_results
            )

            items_html = []
            for r in swaps:
                swap_line = self.format_swap_line(r.swap)
                is_failed = "FAIL" in r.status.upper() or "ERROR" in r.status.upper()
                if is_failed:
                    error_msg = r.error or "Swap rejected by platform"
                    items_html.append(
                        f"""
                        <div style="background: #fef2f2; border-left: 4px solid #ef4444; padding: 8px 12px; border-radius: 4px; font-family: monospace, Consolas, Courier, monospace; font-size: 14px; color: #991b1b; margin-top: 6px;">
                            <div style="font-weight: 600;">❌ FAILED: {swap_line}</div>
                            <div style="color: #dc2626; font-size: 12px; margin-top: 4px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">Reason: {error_msg}</div>
                        </div>
                        """
                    )
                else:
                    items_html.append(
                        f"""
                        <div style="background: #f1f5f9; border-left: 4px solid #2563eb; padding: 8px 12px; border-radius: 4px; font-family: monospace, Consolas, Courier, monospace; font-size: 14px; color: #0f172a; margin-top: 6px;">
                            {swap_line}
                        </div>
                        """
                    )

            for r in non_swaps:
                is_problem = r.error or r.status.upper() in ("FAILED", "ERROR", "NO_REPLACEMENT")
                if is_problem:
                    error_div = (
                        f'<div style="color: #dc2626; font-size: 12px; margin-top: 2px;">Error: {r.error}</div>'
                        if r.error
                        else ""
                    )
                    items_html.append(
                        f"""
                        <div style="background: #fef2f2; border-left: 4px solid #ef4444; padding: 8px 12px; border-radius: 4px; font-size: 13px; color: #991b1b; margin-top: 6px;">
                            <div style="font-weight: 600;">⚠️ {r.message}</div>
                            {error_div}
                        </div>
                        """
                    )
                else:
                    items_html.append(
                        f"""
                        <div style="color: #94a3b8; font-size: 13px; margin-top: 4px;">
                            ✅ {r.message}
                        </div>
                        """
                    )

            content_html = "".join(items_html)

            # Style the header differently based on whether the team has issues
            if team_has_issues:
                header_style = "font-weight: 600; font-size: 15px; color: #991b1b;"
                header_icon = "🚨 "
            else:
                header_style = "font-weight: 600; font-size: 15px; color: #64748b;"
                header_icon = ""

            leagues_html.append(
                f"""
                <div style="margin-bottom: 20px;">
                    <div style="{header_style}">
                        {header_icon}{header}
                    </div>
                    {content_html}
                </div>
                """
            )

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Fantasy Auto-Manager Lineup Report</title>
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 20px;">
            <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #e2e8f0; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                <h2 style="color: #0f172a; margin-top: 0; margin-bottom: 16px; font-size: 18px; border-bottom: 2px solid #2563eb; padding-bottom: 8px;">
                    🏈 Fantasy Lineup Auto-Manager Report
                </h2>
                {"".join(leagues_html)}
                <p style="color: #94a3b8; font-size: 12px; margin-top: 24px; margin-bottom: 0; text-align: center; border-top: 1px solid #f1f5f9; padding-top: 12px;">
                    Generated automatically by FF Manager Bot
                </p>
            </div>
        </body>
        </html>
        """
        return html

    def is_all_clear(self, results: List[ActionResult]) -> bool:
        """
        Determine if all results represent a clean, healthy state.
        Returns True only when every result is NO_ACTION_NEEDED or pre-draft SKIPPED without errors.
        """
        if not results:
            return False
        return (
            all(
                r.status.upper() == "NO_ACTION_NEEDED"
                or (r.status.upper() == "SKIPPED" and "pre-draft" in r.message.lower())
                for r in results
            )
            and not any(
                bool(r.error)
                or r.swap is not None
                or r.status.upper() in ("FAILED", "ERROR", "NO_REPLACEMENT")
                for r in results
            )
        )

    def build_all_clear_text_report(self, results: List[ActionResult]) -> str:
        """Format plain-text 'all clear' confirmation report."""
        lines = [
            "==================================================",
            "   ✅ SUNDAY ALL CLEAR — ALL STARTERS ACTIVE      ",
            "==================================================",
            "",
        ]

        if not results:
            lines.append("No leagues evaluated.")
            return "\n".join(lines)

        grouped = self._group_results_by_team(results)

        for (platform, lid, league_name, tid, team_name), team_results in grouped.items():
            header = self.format_team_header(platform, league_name, team_name)
            lines.append(f"✅ {header}")
            for r in team_results:
                lines.append(f"   {r.status}: {r.message}")
            lines.append("")

        lines.append("All lineups are set. No action required.")
        lines.append("==================================================")
        return "\n".join(lines)

    def build_all_clear_html_report(self, results: List[ActionResult]) -> str:
        """Format clean HTML 'all clear' confirmation email."""
        if not results:
            return "<p>No leagues evaluated.</p>"

        grouped = self._group_results_by_team(results)
        leagues_html = []

        for (platform, lid, league_name, tid, team_name), team_results in grouped.items():
            header = self.format_team_header(platform, league_name, team_name)

            status_items = []
            for r in team_results:
                status_items.append(
                    f'<div style="color: #15803d; font-size: 13px; margin-top: 4px;">'
                    f"✅ {r.message}</div>"
                )

            leagues_html.append(
                f"""
                <div style="margin-bottom: 16px;">
                    <div style="font-weight: 600; font-size: 15px; color: #1e293b;">
                        {header}
                    </div>
                    <div style="background: #f0fdf4; border-left: 4px solid #22c55e; padding: 8px 12px; border-radius: 4px; margin-top: 6px;">
                        {"".join(status_items)}
                    </div>
                </div>
                """
            )

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>Sunday All Clear</title>
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 20px;">
            <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 8px; border: 1px solid #e2e8f0; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                <h2 style="color: #15803d; margin-top: 0; margin-bottom: 16px; font-size: 18px; border-bottom: 2px solid #22c55e; padding-bottom: 8px;">
                    ✅ Sunday All Clear — All Starters Active
                </h2>
                {"".join(leagues_html)}
                <p style="color: #15803d; font-size: 14px; font-weight: 500; margin-top: 16px; margin-bottom: 8px;">
                    All lineups are set. No action required. Enjoy the games! 🏈
                </p>
                <p style="color: #94a3b8; font-size: 12px; margin-top: 24px; margin-bottom: 0; text-align: center; border-top: 1px solid #f1f5f9; padding-top: 12px;">
                    Generated automatically by FF Manager Bot
                </p>
            </div>
        </body>
        </html>
        """
        return html

    def send_all_clear(
        self,
        results: List[ActionResult],
        dry_run: bool = False,
    ) -> bool:
        """
        Send the Sunday "all clear" heartbeat email.

        Only sends if every result is NO_ACTION_NEEDED or SKIPPED.
        Returns False if results contain problems (caller should fall through
        to the normal alert email path).
        """
        if not self.is_all_clear(results):
            logger.info(
                "Results contain actions or errors. Skipping all-clear email; "
                "normal alert path should handle notification."
            )
            return False

        if not self.is_configured:
            logger.warning("Email client not configured. All-clear email skipped.")
            return False

        subject = "✅ Sunday All Clear — All Starters Active"
        if dry_run:
            subject = f"[DRY RUN] {subject}"

        text_content = self.build_all_clear_text_report(results)
        html_content = self.build_all_clear_html_report(results)

        sent = self.client.send_email(
            to=self.email_to,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            from_email=self.email_from,
        )
        if sent:
            logger.info(f"✅ All-clear notification successfully emailed to {self.email_to}")
        return sent

    def send_summary(
        self,
        results: List[ActionResult],
        force: bool = False,
        dry_run: bool = False,
    ) -> bool:
        """
        Compile and send an email report if required or forced.

        Returns:
            True if email was sent or skipped legitimately, False if sending failed.
        """
        if not self.should_send_email(results) and not force:
            logger.info("No roster changes or actionable alerts. Skipping notification email.")
            return True

        if not self.is_configured:
            logger.warning("Email client not configured. Notification email skipped.")
            return False

        subject = "🏈 Fantasy Lineup Auto-Manager Action Report"
        has_errors = any(
            bool(r.error) or r.status.upper() in ("FAILED", "ERROR", "NO_REPLACEMENT")
            for r in results
        )
        if has_errors:
            subject = "⚠️ [Action/Alert] Fantasy Lineup Auto-Manager Report"

        if dry_run:
            subject = f"[DRY RUN] {subject}"

        text_content = self.build_text_report(results)
        html_content = self.build_html_report(results)

        sent = self.client.send_email(
            to=self.email_to,
            subject=subject,
            html_content=html_content,
            text_content=text_content,
            from_email=self.email_from,
        )
        if sent:
            logger.info(f"Summary notification successfully emailed to {self.email_to}")
        return sent

