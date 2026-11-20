# Discord price tracker

A small Discord bot that watches product pages and privately notifies you when a price reaches your target. It uses ZenRows to fetch rendered pages, Gemini to extract title/price/currency, and SQLite to save products. All slash-command responses are private.

## Setup

Python 3.10+ is required. From this folder:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Fill in the three API credentials in `.env`. Create a Discord application and bot in the Discord Developer Portal, and invite it with the `bot` and `applications.commands` scopes. Allow it to send messages and embed links. No privileged Message Content intent is required. Enable direct messages from server members to receive alerts.

```sh
python -m pricebot
```

Keep the process running for scheduled checks. Commands sync once on startup. Global commands can take time to appear; optionally set `DISCORD_GUILD_ID` for a test server. Changing registration scope does not delete previously registered commands in the other scope.

## Commands

| Command | Behavior |
| --- | --- |
| `/check url` | One-time product check, without saving |
| `/track url target_price` | Save a product; target is in the detected product currency |
| `/list page` | View ten saved products per page |
| `/price item_id` | View saved price and last successful check time, without API use |
| `/check_now item_id` | Refresh a saved product |
| `/target item_id target_price` | Change its target and rearm its alert |
| `/untrack item_id` | Delete your saved product |
| `/checks_left` | Bot owner only: inspect available ZenRows cap information |

Each user can track 25 products by default. Scheduled checks run on startup after connection and every nine hours thereafter. `.env.example` documents configurable limits, interval, model, and database location. Gemini model availability depends on your account; set `GEMINI_MODEL` as needed.

## Price and alert behavior

Invalid, missing, ambiguous, zero, negative, and non-finite prices are rejected. Currency is stored alongside the price; a currency change does not overwrite a saved price. All currencies currently use two decimal places, and there is no currency conversion. AI extraction can still select an incorrect price; verify the seller’s price at checkout.

An alert is sent once when a scheduled check sees a price at or below target. It rearms after a successful check above target or after `/target`. Adding a product already below target shows that status immediately and suppresses an extra initial DM. Manual checks do not consume a pending scheduled alert. Failed DM delivery leaves the alert pending for the next scheduled pass. A crash between sending a DM and recording delivery can cause a duplicate notification.

Fetches and AI calls are asynchronous with timeouts and bounded retries. Paid scraping operations are serialized, and identical URLs share a 60-second cache. `/check`, `/track`, and `/check_now` each have a per-user cooldown. Retries and JavaScript/premium scraping can use additional credits. These controls are suitable for a small trusted server; use account spending caps for budget control. Run only one bot process per database.

Public HTTP(S) URLs are accepted; obvious local/private addresses, credentials and unusual ports are rejected. Fetching is delegated to ZenRows, not performed directly against submitted URLs. Hostname resolution and redirect policy are governed by the provider.

## Existing data

The default database is `tracker.db` in the project root (beside the compatibility launcher `bot.py`), independent of the shell working directory. Set `DATABASE_PATH` if your old database is elsewhere. Back up an existing database before first startup (stop the old bot before copying it).

The old `tracking_v2` table is migrated in place: existing IDs and products remain, and currency, check timestamp, and alert-state columns are added. Legacy products are assumed to be USD because the old version displayed dollar amounts without recording currency. Re-add legacy items in other currencies. Previously saved zero prices appear as unavailable until successfully refreshed. Existing duplicate records are retained; new exact-URL duplicates per user are rejected.

No credentials or database files should be committed. Errors sent to users omit provider response bodies and keys; logs identify failed commands/items without raw provider exception text.

## Tests

```sh
python -m unittest discover -s tests -v
```

Tests use temporary databases and mocked providers; no Discord login or API credits are needed. They cover migration, ownership, duplicate/limit enforcement, price validation, alert rearming/delivery failures, and shared scraping/cache behavior.

## API references

- [Discord.py API](https://discordpy.readthedocs.io/en/latest/ext/commands/api.html)
- [Gemini structured output](https://ai.google.dev/gemini-api/docs/structured-output)
- [ZenRows API](https://www.zenrows.com/for/developers)

## Project layout

```text
.
├── bot.py                 # Compatibility launcher
├── pricebot/
│   ├── __init__.py
│   ├── __main__.py        # python -m pricebot entry point
│   ├── bot.py             # Startup, configuration and command errors
│   ├── database.py        # SQLite storage and migrations
│   ├── models.py          # Product data model
│   ├── validation.py      # Price and URL validation
│   ├── scraper.py         # ZenRows/Gemini requests and caching
│   ├── embeds.py          # Shared Discord display formatting
│   └── cogs/
│       ├── __init__.py
│       ├── search.py      # One-time price checks
│       └── tracker.py     # Tracking commands and scheduled alerts
├── tests/
│   ├── test_core.py       # Validation, storage and migration tests
│   └── test_scraper.py    # Scraper, alert and command-loading tests
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

Run commands from the project root. `python bot.py` remains supported. Configuration (`.env`) and the default database remain in the root; moving the source files does not change their locations. The local `.venv/`, generated Python caches, credentials and database files are excluded from version control.
