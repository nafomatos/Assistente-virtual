# Artificial Price Radar

Personal copilot for detecting artificial prices in public markets. Once a day
it pulls market data for a curated list of US stocks and commodities, runs
local behavioral analyzers (volume spike, price velocity), builds a compact
paste-ready report, and emails it to you. You then paste the report into
Claude.ai to get recommendations.

This is the Phase 1 + Phase 2 build: local signal collection + daily email.
No Claude API calls are made from the code yet — that comes in Phase 3.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env     # fill in Gmail creds (see below)
python main.py           # default tickers: NVDA TSLA GLD ...
python main.py --no-email
python main.py NVDA TSLA AAPL
```

The generated report is saved at `output/daily_report_YYYY-MM-DD.txt`.

## Gmail App Password

Gmail SMTP requires an *App Password*, not your Google account password, when
2-step verification is on.

1. Enable 2-step verification: https://myaccount.google.com/signinoptions/twosv
2. Create an App Password: https://myaccount.google.com/apppasswords
   - Select app: **Mail**
   - Select device: **Other** → name it *Artificial Price Radar*
3. Copy the 16-character password into `GMAIL_APP_PASSWORD`. Use the same
   Gmail address for `GMAIL_ADDRESS` and `EMAIL_RECIPIENT` for a personal setup.

## GitHub Actions (daily cron)

Workflow file: `.github/workflows/daily_radar.yml`. It runs every day at
**06:00 UTC** (08:00 Berlin CEST / 07:00 Berlin CET) and can also be
triggered manually from the Actions tab (*Run workflow*).

### Configure repository secrets

In GitHub: **Settings → Secrets and variables → Actions → New repository
secret**. Add these three (names must match exactly):

| Secret name          | Value                                           |
|----------------------|-------------------------------------------------|
| `GMAIL_ADDRESS`      | the sending Gmail address                       |
| `GMAIL_APP_PASSWORD` | the 16-character App Password from above        |
| `EMAIL_RECIPIENT`    | where the report should land (usually the same) |

### Verify the Action ran successfully

1. Open the **Actions** tab → *Daily Radar* workflow.
2. Click the most recent run.
3. Confirm the *Run radar* step finished with a green check and logs end
   with `email sent`.
4. Check your inbox for `[Radar] Artificial Price Signals — YYYY-MM-DD`.
5. On the run page, scroll to **Artifacts** and download `daily-report` to
   inspect the generated `.txt` (retained 14 days).

If the run fails, the artifact is still uploaded (when the report file was
created) and the failing step's logs show which env var or external call
broke.

## Adjusting tickers and thresholds

Edit `config.py`:
- `US_STOCKS`, `COMMODITIES` — the asset list
- `VOLUME_SPIKE_THRESHOLD`, `PRICE_VELOCITY_SIGMA` — analyzer sensitivity
- `SOCIAL_HEAT_THRESHOLD`, `LOOKBACK_DAYS` — other pre-filter inputs

No code changes needed.

## Roadmap

- **Phase 3**: Claude API integration with prompt caching and token logging,
  replacing the manual paste-into-Claude.ai step.
- **Phase 4**: Twitter/X sentiment collector.
