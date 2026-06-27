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

Or use Docker:

```bash
docker-compose up
```

## ⚠️ Important

**Never run two bot instances at once** against the same token/session
(e.g. don't run on the old and new laptop simultaneously).
