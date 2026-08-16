"""Main entry point and orchestrator for Fantasy Football Auto-Manager."""

import argparse
import logging
import sys
from typing import List

from ff_manager.config import Config
from ff_manager.core.lineup_manager import LineupManager
from ff_manager.db import (
    clear_fingerprint,
    compute_fingerprint,
    get_connection,
    get_last_fingerprint,
    get_nfl_week,
    init_db,
    save_fingerprint,
)
from ff_manager.models import ActionResult
from ff_manager.notifications import EmailNotifier, ResendEmailClient
from ff_manager.platforms.espn import ESPNAdapter
from ff_manager.platforms.sleeper import SleeperAdapter


def setup_logging(log_level: str) -> None:
    """Configure structured console logging."""
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def run() -> int:
    """Main execution loop."""
    parser = argparse.ArgumentParser(description="Fantasy Football Lineup Auto-Manager")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate roster swaps without executing mutations on platforms.",
    )
    parser.add_argument(
        "--platform",
        choices=["all", "espn", "sleeper"],
        default="all",
        help="Target specific fantasy platform (default: all).",
    )
    parser.add_argument(
        "--league-id",
        type=str,
        default=None,
        help="Target a single specific league ID.",
    )
    parser.add_argument(
        "--force-email",
        action="store_true",
        help="Send summary email even if no swaps were made.",
    )
    parser.add_argument(
        "--all-clear",
        action="store_true",
        help="Send a confirmation 'all clear' email if all starters are healthy. Intended for the Sunday 11:30 AM CT cron run.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=None,
        help="Logging level (DEBUG, INFO, WARNING, ERROR).",
    )

    args = parser.parse_args()
    config = Config.load()

    # CLI flag overrides
    dry_run = args.dry_run or config.dry_run
    log_level = args.log_level or config.log_level
    force_email = args.force_email or config.force_email
    all_clear = args.all_clear

    setup_logging(log_level)
    logger = logging.getLogger("ff_manager")
    logger.info("🏈 Starting Fantasy Football Auto-Manager...")
    if dry_run:
        logger.info("🔍 DRY-RUN MODE: No live roster changes will be submitted.")

    all_results: List[ActionResult] = []

    # ----------------------------------------------------
    # 1. Process ESPN Leagues
    # ----------------------------------------------------
    if args.platform in ("all", "espn"):
        if config.espn_s2 and config.espn_swid:
            logger.info("Initializing ESPN Adapter...")
            espn_adapter = ESPNAdapter(
                espn_s2=config.espn_s2,
                swid=config.espn_swid,
                year=config.season_year,
            )
            espn_manager = LineupManager(client=espn_adapter, dry_run=dry_run)

            target_espn_leagues = (
                [args.league_id]
                if args.league_id and args.platform == "espn"
                else config.espn_league_ids
            )

            if not target_espn_leagues:
                logger.warning(
                    "ESPN credentials provided but no ESPN_LEAGUE_IDS configured. Skipping ESPN."
                )

            for lid in target_espn_leagues:
                logger.info(f"[ESPN] Processing league {lid}...")
                results = espn_manager.evaluate_and_fix_roster(
                    league_id=lid, team_id=config.espn_team_id
                )
                all_results.extend(results)
        else:
            if args.platform == "espn":
                logger.error("ESPN requested but ESPN_S2 and/or ESPN_SWID not configured.")

    # ----------------------------------------------------
    # 2. Process Sleeper Leagues
    # ----------------------------------------------------
    if args.platform in ("all", "sleeper"):
        if config.sleeper_user_id:
            logger.info("Initializing Sleeper Adapter...")
            sleeper_adapter = SleeperAdapter(
                auth_token=config.sleeper_token,
                user_id=config.sleeper_user_id,
                year=config.season_year,
            )
            sleeper_manager = LineupManager(client=sleeper_adapter, dry_run=dry_run)

            target_sleeper_leagues = []
            if args.league_id and args.platform == "sleeper":
                target_sleeper_leagues = [args.league_id]
            elif config.sleeper_league_ids:
                target_sleeper_leagues = config.sleeper_league_ids
            else:
                # Auto-discover leagues for user
                logger.info("[Sleeper] Auto-discovering user leagues...")
                discovered = sleeper_adapter.get_user_leagues()
                target_sleeper_leagues = [l["league_id"] for l in discovered]
                logger.info(f"[Sleeper] Found {len(target_sleeper_leagues)} leagues.")

            if not target_sleeper_leagues:
                logger.warning("No Sleeper leagues found or configured. Skipping Sleeper.")

            for lid in target_sleeper_leagues:
                logger.info(f"[Sleeper] Processing league {lid}...")
                results = sleeper_manager.evaluate_and_fix_roster(league_id=lid)
                all_results.extend(results)
        else:
            if args.platform == "sleeper":
                logger.error("Sleeper requested but SLEEPER_USER_ID not configured.")

    # ----------------------------------------------------
    # 3. Notification and Summary Reporting
    # ----------------------------------------------------
    email_client = ResendEmailClient(
        api_key=config.resend_api_key,
        default_from=config.email_from,
    )
    notifier = EmailNotifier(
        client=email_client,
        email_to=config.email_to,
        email_from=config.email_from,
    )

    logger.info("Execution complete. Summary of actions:")
    for r in all_results:
        logger.info(f" -> [{r.platform}] {r.league_name}: {r.status} - {r.message}")

    # Output Email Preview in dry-run mode or when requested
    if dry_run or not notifier.is_configured:
        print("\n" + "=" * 60)
        print("                EMAIL NOTIFICATION PREVIEW                 ")
        print("=" * 60)
        if all_clear and notifier.is_all_clear(all_results):
            subject = "✅ Sunday All Clear — All Starters Active"
            print(f"Subject: {subject}")
            print(f"To:      {config.email_to or '[Not Configured]'}")
            print(f"From:    {config.email_from or '[Not Configured]'}")
            print("-" * 60)
            print(notifier.build_all_clear_text_report(all_results))
        else:
            has_errors = any(
                bool(r.error) or r.status.upper() in ("FAILED", "ERROR", "NO_REPLACEMENT")
                for r in all_results
            )
            subject = "⚠️ [Action/Alert] Fantasy Lineup Auto-Manager Report" if has_errors else "🏈 Fantasy Lineup Auto-Manager Action Report"
            if dry_run:
                subject = f"[DRY RUN] {subject}"
            print(f"Subject: {subject}")
            print(f"To:      {config.email_to or '[Not Configured]'}")
            print(f"From:    {config.email_from or '[Not Configured]'}")
            print("-" * 60)
            print(notifier.build_text_report(all_results))
        print("=" * 60 + "\n")

    # ----------------------------------------------------
    # 4. Notification Deduplication
    # ----------------------------------------------------
    db_conn = None
    if config.database_url:
        db_conn = get_connection(config.database_url)
        if db_conn:
            init_db(db_conn)

    nfl_week = get_nfl_week()
    fingerprint = compute_fingerprint(all_results, nfl_week)
    logger.info(f"Notification fingerprint: {fingerprint[:12]}... (NFL week: {nfl_week})" if fingerprint else f"No problems to fingerprint (NFL week: {nfl_week})")

    # Email delivery logic
    if not dry_run or force_email:
        if all_clear:
            # Attempt the all-clear email. If results aren't clean, send_all_clear
            # returns False and we fall through to the normal alert path.
            if notifier.send_all_clear(all_results, dry_run=dry_run):
                logger.info("All-clear email sent successfully.")
                # Clear any saved fingerprint since everything is healthy
                if db_conn:
                    clear_fingerprint(db_conn, config.notification_user_id)
            else:
                # Problems exist — send the normal action/alert email instead
                email_sent = notifier.send_summary(results=all_results, force=True, dry_run=dry_run)
                if email_sent and db_conn and fingerprint:
                    save_fingerprint(db_conn, config.notification_user_id, fingerprint)
        else:
            # Check deduplication before sending
            should_send = True
            if db_conn and fingerprint and not force_email:
                last_fp = get_last_fingerprint(db_conn, config.notification_user_id)
                if last_fp == fingerprint:
                    logger.info("Notification fingerprint unchanged — suppressing duplicate email.")
                    should_send = False

            if should_send:
                email_sent = notifier.send_summary(results=all_results, force=force_email, dry_run=dry_run)
                # Only save fingerprint after successful email delivery (or clear if no problems)
                if db_conn:
                    if fingerprint and email_sent:
                        save_fingerprint(db_conn, config.notification_user_id, fingerprint)
                    elif not fingerprint:
                        clear_fingerprint(db_conn, config.notification_user_id)
    else:
        logger.info("Dry-run mode enabled and --force-email not set. Email delivery skipped.")

    if db_conn:
        db_conn.close()

    logger.info("Finished.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
