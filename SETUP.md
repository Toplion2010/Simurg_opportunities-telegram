# New-machine setup

This bot is **account-based, not device-locked** — there is no IP or device
setting to configure. Once a machine has the credentials below, it just works.

## 1. Clone

```bash
git clone https://github.com/Toplion2010/Simurg_opportunities-telegram
cd Simurg_opportunities-telegram
```

## 2. Bring over the secrets (NOT in git)

These are intentionally excluded via `.gitignore` and must be copied manually
(AirDrop / USB / password manager / `scp`):

- **`.env`** — real tokens (BOT_TOKEN, GROQ_API_KEY, TELETHON_API_ID/HASH,
  POSTGRES_PASSWORD, etc.). Use `.env.example` as a template if refilling by hand.
- **`telethon_session/simurg.session`** — the logged-in userbot session.
  Alternatively, run `python auth_telethon.py` to log in fresh (Telegram sends a
  login code; approve the "new login" notification — that's expected).

## 3. Install & run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

On Windows, you can now launch the bot with:

```powershell
start_simurg.bat
```

Or use Docker:

```bash
docker-compose up
```

## ⚠️ Important

**Never run two bot instances at once** against the same token/session
(e.g. don't run on the old and new laptop simultaneously).

## Running 24/7 (Windows)

`start_simurg.bat` is for manual/dev runs — closing the window stops the bot, and
a crash just ends it (no auto-restart). For an always-on setup that survives
reboots and crashes with no manual starting, register it as a Windows Task
Scheduler task **once**:

1. Make sure `.venv` exists and dependencies are installed (run `start_simurg.bat`
   once if you haven't already — it creates the venv and installs everything).
2. Open PowerShell **as Administrator**, `cd` into the repo, then run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\install_scheduled_task.ps1
   ```
   It will ask for your Windows account password (needed so the task can run even
   when you're logged out) — entered directly into that prompt, never stored in
   this repo.

This creates a task named `SimurgOpportunitiesBot` that:
- Starts the bot at boot (`pythonw.exe`, no visible console window).
- Re-checks every 5 minutes and relaunches it if it's not running — an unlimited,
  uncapped self-healing loop, so a crash fixes itself within minutes with zero
  manual intervention.

**Logs** now always go to `logs/simurg.log` (rotating, 5 files × 10 MB) in
addition to the console, since `pythonw.exe` has no console to print to. Tail it
to see what the bot is doing:
```powershell
Get-Content logs\simurg.log -Wait -Tail 50
```

**Useful commands:**
```powershell
schtasks /query /tn "SimurgOpportunitiesBot" /v /fo list   # status
Stop-ScheduledTask -TaskName "SimurgOpportunitiesBot"      # stop
Start-ScheduledTask -TaskName "SimurgOpportunitiesBot"     # start
Disable-ScheduledTask -TaskName "SimurgOpportunitiesBot"   # disable (keeps config)
```

## Running 24/7 (Railway — no laptop required)

The Windows Task Scheduler setup above only runs while *your machine is on*. To keep
collecting and processing with the laptop shut, deploy to Railway instead.

The repo is already prepared for this: `railway.json` (Dockerfile build + `alembic
upgrade head` as a pre-deploy step), `DATABASE_URL` auto-rewrites `postgresql://` →
`postgresql+asyncpg://`, and the Telegram session can travel as an env var.

### 1. Export the Telethon session

Railway's filesystem is **ephemeral** — `telethon_session/simurg.session` would be wiped
on every redeploy, and a headless container can't answer a login-code prompt. So export
the session to a string first (locally, on the machine that's already authorized):

```powershell
.\.venv\Scripts\python.exe -m scripts.export_session_string
```

Copy the printed `TELETHON_SESSION_STRING=...` value. **Treat it like a password** —
it grants full access to the Telegram account.

### 2. Create the Railway project

1. https://railway.app → **New Project** → **Deploy from GitHub repo** → pick
   `Simurg_opportunities-telegram`.
2. In the same project: **+ New** → **Database** → **Add PostgreSQL**.
3. **+ New** → **Database** → **Add Redis**.

### 3. Set environment variables

On the **app service** → *Variables*. Reference the databases with Railway's variable
syntax so they stay correct if credentials rotate:

```
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
LOCAL_DEV=false
ENVIRONMENT=production
TELETHON_SESSION_STRING=<from step 1>
```

Then copy the rest from your local `.env`: `BOT_TOKEN`, `ADMIN_IDS`,
`TELETHON_API_ID`, `TELETHON_API_HASH`, `DEST_CHANNEL_ID_SCHOOL`,
`DEST_CHANNEL_ID_UNIVERSITY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, and
`PROCESSOR_CRON_HOURS`.

> `LOCAL_DEV=false` matters: when true the app uses **in-memory fakeredis**, so the
> queue would be lost on every restart — and with batches only running 5×/day, that
> can mean losing hours of collected posts.

### 4. Seed the source channels

Once deployed, run this against the new (empty) Postgres — otherwise the userbot logs
`no_active_channels_configured` and collects nothing:

```
python -m scripts.seed_channels
```

Use Railway's service shell, or a one-off command on the service.

### 5. Stop the laptop instance ⚠️

Two instances must **never** run at once — same bot token and same Telegram session
means conflicting `getUpdates` polling and possible session revocation:

```powershell
Disable-ScheduledTask -TaskName "SimurgOpportunitiesBot"
Stop-ScheduledTask -TaskName "SimurgOpportunitiesBot"
```

### 6. Verify

In Railway's **Deploy Logs**, confirm: `starting_simurg` → `scheduler_started` →
`telethon_connected` → `monitoring_channels count=N` → `all_services_started`.
Then post to a monitored channel and check the admin bot's queue after the next
scheduled batch hour. You should also get a Telegram summary message from the bot
after each run ("Batch run complete: N new opportunities ready for review").

### What can actually "expire"

Every API key here (`BOT_TOKEN`, `GROQ_API_KEY`, `GEMINI_API_KEY`,
`OPENAI_API_KEY`, `TELETHON_API_ID`/`HASH`) is a static credential — none of them
expire on their own. The **one** thing that can: `telethon_session/simurg.session`
is a real logged-in Telegram **user account** session (used only to read source
channels). Telegram can invalidate it — you revoke the "active session" from your
phone, change your 2FA/password, or it flags something as suspicious. If that
happens:
- You'll see a clear `telethon_session_invalid` line in `logs/simurg.log` telling
  you to re-authenticate.
- **The rest of the bot keeps working** — the admin panel, approve/reject queue,
  and scheduled publishing don't depend on the userbot, so this only pauses
  collection of *new* channel messages, not the whole bot.
- Fix: run `python auth_telethon.py` again to log back in, then restart the task
  (`Stop-ScheduledTask` / `Start-ScheduledTask`, or just wait — the 5-minute
  keep-alive trigger will pick it back up once the process is running again if it
  had also crashed).
