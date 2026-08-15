"""Email notification and reporting module."""

import email.message
import logging
import smtplib
from typing import List, Optional

from ff_manager.models import ActionResult, SwapDecision

logger = logging.getLogger(__name__)


class EmailNotifier:
    """Compiles execution action logs into clean HTML/Text email summaries."""

    def __init__(
        self,
        smtp_host: Optional[str] = None,
        smtp_port: int = 587,
        smtp_user: Optional[str] = None,
        smtp_password: Optional[str] = None,
        email_to: Optional[str] = None,
        email_from: Optional[str] = None,
        use_tls: bool = True,
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.email_to = email_to
        self.email_from = email_from or smtp_user
        self.use_tls = use_tls

    @property
    def is_configured(self) -> bool:
        """Check if SMTP credentials and recipients are fully configured."""
        return bool(self.smtp_host and self.smtp_user and self.smtp_password and self.email_to)

    def should_send_email(self, results: List[ActionResult]) -> bool:
        """
        Determine if an email should be sent.
        Sends if and only if a roster change was actually made (at least one successful swap).
        """
        for r in results:
            if r.swap is not None and "SUCCESS" in r.status.upper():
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

    def build_text_report(self, results: List[ActionResult]) -> str:
        """Format plain-text summary report."""
        lines = [
            "==================================================",
            "        FANTASY FOOTBALL AUTO-MANAGER REPORT      ",
            "==================================================",
            "",
        ]

        if not results:
            lines.append("No leagues evaluated.")
            return "\n".join(lines)

        for r in results:
            lines.append(f"[{r.platform}] {r.league_name} ({r.team_name})")
            if r.swap:
                lines.append(f"  • {self.format_swap_line(r.swap)}")
            else:
                lines.append(f"  Status: {r.status} - {r.message}")
            if r.error:
                lines.append(f"  Error: {r.error}")
            lines.append("")

        lines.append("==================================================")
        return "\n".join(lines)

    def build_html_report(self, results: List[ActionResult]) -> str:
        """Format clean, modern HTML email report."""
        leagues_html = []
        for r in results:
            if r.swap:
                swap_line = self.format_swap_line(r.swap)
                content_html = f"""
                <div style="background: #f1f5f9; border-left: 4px solid #2563eb; padding: 8px 12px; border-radius: 4px; font-family: monospace, Consolas, Courier, monospace; font-size: 14px; color: #0f172a; margin-top: 6px;">
                    {swap_line}
                </div>
                """
            else:
                content_html = f"""
                <div style="color: #64748b; font-size: 13px; margin-top: 4px;">
                    {r.status}: {r.message}
                </div>
                """

            leagues_html.append(
                f"""
                <div style="margin-bottom: 18px;">
                    <div style="font-weight: 600; font-size: 15px; color: #1e293b;">
                        [{r.platform}] {r.league_name} <span style="font-weight: normal; color: #64748b; font-size: 13px;">({r.team_name})</span>
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
                    Generated automatically by FF_Manager
                </p>
            </div>
        </body>
        </html>
        """
        return html

    def send_summary(self, results: List[ActionResult], force: bool = False) -> bool:
        """
        Compile and send an email report if required or forced.

        Returns:
            True if email was sent or skipped legitimately, False if sending failed.
        """
        if not self.should_send_email(results) and not force:
            logger.info("No roster changes made. Skipping notification email.")
            return True

        if not self.is_configured:
            logger.warning("SMTP settings not configured. Notification email skipped.")
            return False

        subject = "🏈 Fantasy Lineup Auto-Manager Action Report"
        has_errors = any(r.error or r.status.upper() in ("FAILED", "NO_REPLACEMENT") for r in results)
        if has_errors:
            subject = "⚠️ [Action/Alert] Fantasy Lineup Auto-Manager Report"

        msg = email.message.EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.email_from
        msg["To"] = self.email_to

        text_content = self.build_text_report(results)
        html_content = self.build_html_report(results)

        msg.set_content(text_content)
        msg.add_alternative(html_content, subtype="html")

        try:
            logger.info(f"Connecting to SMTP server {self.smtp_host}:{self.smtp_port}...")
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15) as server:
                if self.use_tls:
                    server.starttls()
                if self.smtp_user and self.smtp_password:
                    server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)
            logger.info(f"Summary notification successfully emailed to {self.email_to}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email notification: {e}", exc_info=True)
            return False
