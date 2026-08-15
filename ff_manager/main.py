"""Main entry point and orchestrator for Fantasy Football Auto-Manager."""

import argparse
import logging
import sys
from typing import List

from ff_manager.config import Config
from ff_manager.core.lineup_manager import LineupManager
from ff_manager.models import ActionResult
from ff_manager.notifications.notifier import EmailNotifier
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
    notifier = EmailNotifier(
        smtp_host=config.smtp_host,
        smtp_port=config.smtp_port,
        smtp_user=config.smtp_user,
        smtp_password=config.smtp_password,
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
        has_errors = any(r.error or r.status.upper() in ("FAILED", "NO_REPLACEMENT") for r in all_results)
        subject = "⚠️ [Action/Alert] Fantasy Lineup Auto-Manager Report" if has_errors else "🏈 Fantasy Lineup Auto-Manager Action Report"
        print(f"Subject: {subject}")
        print(f"To:      {config.email_to or '[Not Configured]'}")
        print(f"From:    {config.email_from or '[Not Configured]'}")
        print("-" * 60)
        print(notifier.build_text_report(all_results))
        print("=" * 60 + "\n")

    if not dry_run:
        notifier.send_summary(results=all_results, force=force_email)

    logger.info("Finished.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
