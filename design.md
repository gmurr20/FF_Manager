# System Design Specification: Fantasy Auto-Manager

## 1. Purpose and Scope
**Target Agent:** Read this document to understand the architectural requirements, constraints, and business logic for a new Python automation script.

**Goal:** Create a headless Python script to automatically manage my fantasy football teams (4 on Sleeper, 1 on ESPN). The system will scan active lineups, evaluate health and point projections, execute roster substitutions when strict thresholds are met, and send a summary email of all actions taken.

## 2. Core Business Logic (The "Swap Rules")
The agent must implement strict conditional logic. An active starter should **ONLY** be removed from the starting lineup if they meet one of the following criteria:
- **Condition A (Low Projection):** `projected_points < 1.0`
- **Condition B (Injury Status):** `injury_status` is explicitly `"OUT"` or `"DOUBTFUL"`.

**Replacement Protocol:**
1. Identify all players currently on the bench (`"BE"` slot).
2. Filter the bench to include only players whose `eligibleSlots` match the slot being vacated.
3. Filter out any bench players whose individual games have already started (ensure `locked == False`).
4. Select the eligible bench player with the **highest projected points** based strictly on the current platform's projections.
5. Execute the roster swap.

## 3. Module Architecture

### 3.1 ESPN Manager Module
- **Target:** 1 League.
- **Dependencies:** `espn-api` (Python package).
- **Authentication:** `swid` and `espn_s2` cookies injected via environment variables.
- **Read Operations:** Parse `team.roster` for `projected_points`, `injuryStatus`, `lineupSlot`, and `eligibleSlots`.
- **Write Operations:** If the `espn-api` wrapper does not support the `.submit_roster()` function out of the box for current season types, the agent must implement an authenticated HTTP POST request to ESPN's roster mutation endpoint.

### 3.2 Sleeper Manager Module
- **Target:** 4 Leagues.
- **Dependencies:** `sleeper-sdk` (for read operations), `requests` (for write operations).
- **Authentication:** `SLEEPER_TOKEN` stored in environment variables.
- **Read Operations:**
  - Fetch rosters to get current starting/bench Player IDs.
  - Fetch player metadata for position mappings and `injury_status`.
  - Fetch weekly projections to evaluate `Condition A`.
- **Write Operations:** Formulate the correct GraphQL mutation or REST POST request to Sleeper's undocumented write endpoint using the session token.

### 3.3 Notification & Reporting Module
- **State Management:** The script must maintain a localized `ActionLog` array during its execution loop.
- **Logging requirements:**
  - Record successful swaps (e.g., *"ESPN League: Swapped OUT [Player A] for [Player B] (Proj: 12.4)"*).
  - Record exceptions/failures (e.g., *"Sleeper League 3: No valid bench replacement found for [Player C]"* or *"Auth Token Expired"*).
- **Email Delivery:** Implement an `smtplib` function that compiles the `ActionLog` into a clean HTML/Text summary and emails it to the user. Skip the email if no swaps were made and no errors occurred.

## 4. Deployment & Infrastructure Target
- **Containerization:** The script must include a `Dockerfile` for standardized execution.
- **Hosting:** Designed to be deployed as a scheduled background worker on Railway.
- **Scheduling:** Intended to run via a cron schedule (e.g., Thursday afternoons, Sunday mornings 1 hour prior to kickoff) to catch late-breaking injury designations.