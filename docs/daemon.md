# INZO Background Daemon

The daemon is INZO's headless background process: no GUI, no web server, no
interactive prompts. It runs skill **ticks** (periodic background skills),
**natural-language schedules** from `schedules.json`, and the
**notification center** — so reminders, budget alerts, habit nudges, and
market checks keep working while you're away.

```bash
python3 -m inzo.daemon
```

## Usage / flags

```bash
python3 -m inzo.daemon [--data-dir DIR] [--pid-file PATH] [--webhook-url URL]
```

| Flag | Default | Meaning |
|---|---|---|
| `--data-dir` | `$INZO_DATA_DIR` or `~/.local/share/inzo` | All daemon state lives here: skill databases, `schedules.json`, the PID file, the notification inbox |
| `--pid-file` | `<data-dir>/inzo-daemon.pid` | PID lock file |
| `--webhook-url` | `$INZO_WEBHOOK_URL` | Optional webhook URL for notification fan-out |

**PID file.** On startup the daemon writes its PID to the PID file and refuses
to start if another live daemon already holds it (`_claim_pid_file`). A stale
file (PID no longer alive) is removed with a warning. On clean shutdown
(SIGTERM/SIGINT) the file is released.

**Signals.** `SIGTERM` and `SIGINT` trigger a graceful shutdown: scheduler jobs
stop, the work queue drains, then the PID file is released and the process
exits.

## What it does on boot

1. Claims the PID file.
2. Builds the full skill registry (84 skills), wires an `EventBus`, a
   `NotificationCenter`, an asyncio `Scheduler`, and an `InProcessQueue`.
3. Grants the `daemon` actor the default capability set and creates a
   `SkillEngine`.
4. Schedules a periodic **tick** for every enabled skill with
   `background=True` and a `tick_interval_s` set (e.g. `reminders` ticks every
   60 s; ticks run as the `daemon` actor with message `tick:<skill-name>`).
5. Loads NL schedules from `<data-dir>/schedules.json` and starts the
   60-second dispatcher that submits due schedules to the queue.
6. Subscribes housekeeping handlers: `skill.completed` is logged,
   `anomaly.detected` sends an inbox notification.

A skill tick that raises is logged and never kills the daemon.

## Tick skills

A skill opts into periodic execution by setting `tick_interval_s` (seconds).
The daemon sends `tick:<skill-name>` as the message. Examples:

- `reminders` (60 s) — fires due reminders
- `med_reminders`, `focus_pomodoro`, `email_triage`, `price_alerts`,
  `budget_alerts`, `predictive_reminders`, `autonomous_goals`, `privacy_firewall`…

## schedules.json

`<data-dir>/schedules.json` is a JSON list; each entry has `name`,
`schedule` (natural language — English or Hinglish), `skill`, and an optional
`message`:

```json
[
  {"name": "morning brief", "schedule": "har subah 8 baje",
   "skill": "morning_briefing", "message": ""},
  {"name": "evening review", "schedule": "roz shaam 7 baje",
   "skill": "daily_planner", "message": "review today"},
  {"name": "market pulse", "schedule": "every weekday at 9pm",
   "skill": "news_digest", "message": "markets"},
  {"name": "water plants", "schedule": "har 30 minute me",
   "skill": "reminders", "message": "tick:reminders"}
]
```

The `schedule` text is parsed by `core.nl_cron.parse_nl_schedule`
(`"har subah 8 baje"` → daily 08:00, `"every 5 minutes"` → interval 300 s,
`"every weekday at 9pm"` → Mon–Fri 21:00, …). Entries that fail to parse are
logged and skipped — one bad entry never breaks the others. The dispatcher
checks every 60 seconds and submits due schedules as queue tasks.

## Notification channels

Every notification is persisted to a SQLite-backed inbox first
(`GET /notifications/inbox` on the API). Optional fan-out channels:

| Channel | How it works |
|---|---|
| `inbox` | Always-on: SQLite inbox under the data dir |
| `desktop` | Best-effort popup via `plyer` (logs a line when `plyer` isn't installed) |
| `webhook` | POSTs JSON to `--webhook-url` (http/https only, 2 retries, 5 s timeout) |

Channel failures are logged, never raised.

## systemd user-service example

Run the daemon at login as a user service:

```ini
[Unit]
Description=INZO background daemon
After=network-online.target

[Service]
ExecStart=/usr/bin/python3 -m inzo.daemon --data-dir %h/.local/share/inzo
Restart=on-failure

[Install]
WantedBy=default.target
```

Install and start:

```bash
mkdir -p ~/.config/systemd/user
cp inzo-daemon.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now inzo-daemon.service
```

## Runtime status

While the API server runs, the daemon's live state is visible at:

- `GET /daemon/status` — skill counts, scheduler jobs, queue depth
- `GET /notifications/inbox` — newest-first notification inbox
- `POST /skills/run` — run any registered skill on demand
