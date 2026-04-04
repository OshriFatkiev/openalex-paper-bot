# openalex-paper-bot

Minimal daily paper alerts with OpenAlex + Telegram.

The bot does four things:

1. Loads a YAML watchlist of authors and institutions.
2. Fetches newly published works from OpenAlex, filtered by configurable paper-like work types.
3. Collapses obvious duplicate versions and deduplicates against `data/state.json`.
4. Sends one compact Telegram digest, splitting across a few messages with an explicit omission note if needed.

It is intentionally small: no framework, no database, only `httpx`, `pydantic`, and `pyyaml`.

Identifiers:

- Authors can be defined by `openalex_id`, `orcid`, or `name`.
- Institutions can be defined by `openalex_id`, `ror`, or `name`.
- The bot resolves those to stable OpenAlex IDs and can write them back into `watchlist.yaml`.
- Global keyword discovery can be added with `global_queries`.

## Requirements

- Python 3.11+
- `uv`
- An OpenAlex API key
- A Telegram bot token
- A Telegram chat ID

## Setup

### 1. Create a Telegram bot

1. Open Telegram and talk to `@BotFather`.
2. Run `/newbot`.
3. Save the bot token.

### 2. Get your Telegram chat ID

1. Start a chat with your bot and send it a message.
2. Open:

```text
https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
```

3. Find `message.chat.id` in the JSON response and copy it.

For groups, add the bot to the group first and send a message in that group.

### 3. Get an OpenAlex API key

Sign in to OpenAlex, create an API key from your account dashboard, and store it in `OPENALEX_API_KEY`.

### 4. Configure the repo

Create a local `.env` file from the example:

```bash
cp .env.example .env
```

Fill in:

```dotenv
OPENALEX_API_KEY=your_openalex_api_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

Create a private local watchlist from the example:

```bash
cp watchlist.example.yaml watchlist.yaml
```

Edit `watchlist.yaml`:

```yaml
lookback_days: 2

work_types:
  - article
  - preprint

topic_filters:
  match_mode: primary
  fields:
    - name: Computer Science
      openalex_id: null

targets:
  - type: author
    name: Yann LeCun
    openalex_id: null
    orcid: null

  - type: institution
    name: Meta
    openalex_id: null
    ror: null

global_queries:
  - query: world model
    field: title_and_abstract
    label: Global: world model

keywords:
  include: []
  exclude: []

telegram:
  send_empty_report: false
```

### 5. Sync the project with uv

```bash
uv sync
```

`uv sync` creates a local `.venv` and installs the project plus development tools from `uv.lock`.

## Usage

Resolve names, ORCIDs, or RORs to stable OpenAlex IDs:

```bash
uv run ppb resolve
```

Use `--write` to write the resolved IDs back into `watchlist.yaml`.

Send a Telegram test message:

```bash
uv run ppb test-message
```

Reset `data/state.json` and start fresh:

```bash
uv run ppb reset-state
```

Use `-y` / `--yes` for non-interactive reset.

Run the daily fetch + digest flow:

```bash
uv run ppb run
```

Running the bot twice will not resend the same OpenAlex work IDs because they are stored in `data/state.json`.

If you activate `.venv` manually, `ppb ...` works directly too, but `uv run ppb ...` is the intended workflow.

## Watchlist format

`watchlist.yaml` supports:

```yaml
lookback_days: 2

work_types:
  - article
  - preprint

topic_filters:
  match_mode: primary
  fields:
    - name: Computer Science
      openalex_id: https://openalex.org/fields/17
    - name: Physics
      openalex_id: https://openalex.org/fields/31

targets:
  - type: author
    name: Yann LeCun
    openalex_id: null
    orcid: null

  - type: author
    name: null
    openalex_id: null
    orcid: https://orcid.org/0000-0001-2345-6789

  - type: institution
    name: Meta
    openalex_id: null
    ror: null

  - type: institution
    name: null
    openalex_id: null
    ror: https://ror.org/03yrm5c26

global_queries:
  - query: world model
    field: title_and_abstract
    label: Global: world model

  - query: multimodal agents
    field: search
    label: null

keywords:
  include: []
  exclude: []

telegram:
  send_empty_report: false
```

Notes:

- `work_types` applies across author targets, institution targets, and global keyword queries.
- The default `work_types` is `article` and `preprint`.
- `topic_filters.fields` lets you restrict results to broad OpenAlex fields such as Computer Science or Physics.
- `topic_filters.match_mode: primary` uses `primary_topic.field.id`, which is narrower and usually better.
- `topic_filters.match_mode: any_topic` uses `topics.field.id`, which is broader.
- `resolve --write` also fills in missing OpenAlex field IDs under `topic_filters.fields`.
- Author targets may use `openalex_id`, `orcid`, or `name`.
- Institution targets may use `openalex_id`, `ror`, or `name`.
- `name` is optional when an ID is already present. Running `resolve --write` fills missing names from OpenAlex.
- `global_queries` expands discovery beyond the watched authors and institutions.
- `global_queries.field` may be `title_and_abstract`, `title`, `abstract`, or `search`.
- `search` is broader because it uses OpenAlex full search; `title_and_abstract` is the tighter default.
- The bot collapses obvious duplicate versions when they share a DOI, or when title and lead author are identical.
- When too many papers match, the digest is split across up to a few Telegram messages and ends with a clear `... and N more papers not shown` note.
- Stable IDs are preferred for day-to-day runs.
- `keywords.include` and `keywords.exclude` are still applied after retrieval to the combined result set.

## State format

`data/state.json`:

```json
{
  "sent_work_ids": [],
  "sent_paper_signatures": [],
  "last_run_at": null
}
```

## GitHub Actions

The workflow runs on a daily schedule and on manual dispatch.

By default, `.github/workflows/daily.yml` is scheduled for `07:00 UTC` every day. Adjust the cron expression if you want a different run window.

Add these repository secrets:

- `OPENALEX_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `WATCHLIST_YAML`

Create the watchlist secret from your local private file:

```bash
gh secret set WATCHLIST_YAML < watchlist.yaml
```

The workflow reconstructs `watchlist.yaml` from `WATCHLIST_YAML` at runtime, so your real watchlist does not need to live in the repository.
It also validates the secret before running the bot and fails with a clear GitHub Actions error if the secret is missing or the YAML is invalid.

Privacy note:

- `watchlist.example.yaml` is the public template committed to the repo.
- `watchlist.yaml` is ignored and intended to stay local or be injected via GitHub Actions secrets.
- If `watchlist.yaml` was already committed to your Git history before this change, removing it from the current branch is not enough to erase it from history.

The workflow uses a GitHub Actions cache to restore and save `data/state.json`, so previously sent work IDs survive across runs without adding a database.

## Development

Sync dependencies and run tests:

```bash
uv sync
uv run pytest
```

## Design choices

- Plain Python modules, no framework
- JSON state, no SQLite
- OpenAlex IDs instead of name matching where possible
- Small, deterministic formatting and filtering logic
- Clear failures for missing config and API errors

## License

Licensed under the Apache License, Version 2.0. See `LICENSE`.
