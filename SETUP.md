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
