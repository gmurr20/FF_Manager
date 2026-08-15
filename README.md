# FF_Manager: Fantasy Football Lineup Auto-Manager

A headless Python automation tool that manages fantasy football lineups across ESPN and Sleeper leagues, ensuring active and healthy starting lineups by catching last-minute injury and inactive designations.

---

## Features
- **Decoupled Architecture**: Platform-agnostic core evaluation logic separated from platform integrations via `FantasyPlatformClient` interface.
- **Smart Swap Protocol**:
  - Replaces starters meeting Condition A (`projected_points < 1.0`) or Condition B (`injury_status in ["OUT", "DOUBTFUL", "IR"]`).
  - Filters bench for unlocked (`is_locked == False`), healthy, and position-eligible candidates.
  - Automatically selects the eligible candidate with the highest projected points.
  - Prevents multi-swap collisions (never duplicates a bench player across multiple starter slots).
- **ESPN & Sleeper Integrations**: Seamless adapters for both ESPN and Sleeper leagues.
- **Email Notifications**: Summarizes all executed swaps, warnings, and errors in formatted HTML/Text emails via SMTP.
- **Safe Simulation (`--dry-run`)**: Test and verify lineup swap evaluations without mutating live lineups.
- **Production Ready**: Containerized with `Dockerfile` for deployment on Railway or cron workers.

---

## Project Structure

```
ff_manager/
├── config.py                 # Configuration loader (.env, env variables)
├── models.py                 # Unified domain models (Player, Roster, SwapDecision, ActionResult)
├── interfaces.py             # Abstract base class (FantasyPlatformClient)
├── core/
│   └── lineup_manager.py     # Platform-agnostic lineup evaluation & swap engine
├── platforms/
│   ├── espn.py               # ESPN platform adapter
│   └── sleeper.py            # Sleeper platform adapter
├── notifications/
│   └── notifier.py           # Email notification formatting and delivery
└── main.py                   # CLI orchestrator and entry point
```

---

## Quick Start

### 1. Installation
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configuration
Copy the `.env.example` file to `.env` and fill in your platform credentials:
```bash
cp .env.example .env
```

Key environment variables:
- **ESPN**: `ESPN_S2`, `ESPN_SWID`, `ESPN_LEAGUE_IDS`
- **Sleeper**: `SLEEPER_USER_ID`, `SLEEPER_TOKEN`, `SLEEPER_LEAGUE_IDS`
- **Notifications**: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `NOTIFICATION_EMAIL_TO`

### 3. Usage

#### Run in Dry-Run Mode (Simulation)
```bash
python -m ff_manager.main --dry-run
```

#### Run Live Updates
```bash
python -m ff_manager.main
```

#### Filter by Platform or League
```bash
python -m ff_manager.main --platform sleeper --league-id 123456789012345678
python -m ff_manager.main --platform espn --league-id 12345678
```

---

## Running Tests

Run the comprehensive unit test suite:
```bash
python3 -m unittest discover tests
```
or with pytest:
```bash
pytest tests/ -v
```

---

## Deployment (Railway / Docker)

Build and run using Docker:
```bash
docker build -t ff-manager .
docker run --env-file .env ff-manager
```
