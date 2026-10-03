"""INZO headless daemon: background skill ticks, NL schedules, notifications.

Run with ``python -m inzo.daemon``. This is a pure background process:
no GUI, no web server, no interactive prompts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

from app.dependencies import DEFAULT_CAPABILITIES
from app.logging_config import get_logger, setup_logging
from core.event_bus import EventBus
from core.nl_cron import ScheduleSpec, next_run, parse_nl_schedule
from core.notifications import NotificationCenter
from security.permissions import PermissionManager
from skills.discovery import build_skill_registry
from skills.engine import SkillEngine
from skills.registry import SkillRegistry
from workers.queue import InProcessQueue, TaskFactory
from workers.scheduler import JobFactory, Scheduler

logger = get_logger(__name__)

_DISPATCH_INTERVAL_S = 60.0


@dataclass
class _NLSchedule:
    """One entry from ``schedules.json`` with its parsed spec."""

    name: str
    spec: ScheduleSpec
    skill: str
    message: str


def _build_parser() -> argparse.ArgumentParser:
    default_data_dir = os.environ.get("INZO_DATA_DIR") or str(
        Path.home() / ".local" / "share" / "inzo"
    )
    parser = argparse.ArgumentParser(
        prog="inzo-daemon",
        description=(
            "INZO headless background daemon: runs skill ticks, "
            "natural-language schedules, and the notification center."
        ),
    )
    parser.add_argument(
        "--data-dir",
        default=default_data_dir,
        help="data directory (default: $INZO_DATA_DIR or ~/.local/share/inzo)",
    )
    parser.add_argument(
        "--pid-file",
        default=None,
        help="pid file path (default: <data-dir>/inzo-daemon.pid)",
    )
    parser.add_argument(
        "--webhook-url",
        default=os.environ.get("INZO_WEBHOOK_URL"),
        help="optional webhook URL for notification fan-out",
    )
    return parser


def _pid_alive(pid: int) -> bool:
    """True when a process with ``pid`` exists (ours or not)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _claim_pid_file(pid_file: Path) -> None:
    """Write our PID; refuse when another live daemon holds the file."""
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    if pid_file.exists():
        try:
            existing = int(pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            existing = 0
        if existing > 0 and _pid_alive(existing):
            raise SystemExit(
                f"another inzo daemon (pid {existing}) holds {pid_file}; "
                "refusing to start"
            )
        if existing > 0:
            logger.warning("removing stale pid file", extra={"pid": existing})
    try:
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"cannot write pid file {pid_file}: {exc}") from exc


def _release_pid_file(pid_file: Path) -> None:
    try:
        pid_file.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("could not remove pid file", extra={"error": str(exc)})


def _wire_subscriptions(
    event_bus: EventBus, notifications: NotificationCenter
) -> None:
    """Subscribe the daemon's housekeeping handlers."""

    async def _on_skill_completed(payload: dict[str, Any]) -> None:
        logger.info(
            "skill completed",
            extra={"skill": payload.get("skill"), "actor": payload.get("actor")},
        )

    async def _on_anomaly_detected(payload: dict[str, Any]) -> None:
        detail = payload.get("detail", payload)
        await notifications.notify(
            "Anomaly detected", str(detail), channels=("inbox",)
        )

    async def _on_notification(payload: dict[str, Any]) -> None:
        logger.info("notification event", extra={"title": payload.get("title")})

    event_bus.subscribe("skill.completed", _on_skill_completed)
    event_bus.subscribe("anomaly.detected", _on_anomaly_detected)
    event_bus.subscribe("notification", _on_notification)


def _make_tick_factory(engine: SkillEngine, skill_name: str) -> JobFactory:
    """Build the periodic tick job for one skill (exceptions are logged)."""

    async def _tick() -> None:
        try:
            await engine.run_skill("daemon", skill_name, message=f"tick:{skill_name}")
        except Exception:
            logger.exception("background skill tick failed", extra={"skill": skill_name})

    return _tick


def _schedule_ticks(
    scheduler: Scheduler, registry: SkillRegistry, engine: SkillEngine
) -> int:
    """Schedule periodic ticks for background skills; return job count."""
    count = 0
    for skill in registry.enabled_skills():
        interval = skill.tick_interval_s
        if skill.background and interval is not None:
            scheduler.schedule(
                f"tick:{skill.name}", interval, _make_tick_factory(engine, skill.name)
            )
            count += 1
    return count


def _load_schedules(data_dir: Path) -> list[_NLSchedule]:
    """Load and parse ``data_dir/schedules.json``; invalid entries are skipped."""
    path = data_dir / "schedules.json"
    if not path.exists():
        return []
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("cannot read schedules.json", extra={"error": str(exc)})
        return []
    try:
        entries = cast("list[dict[str, Any]]", json.loads(raw_text))
    except ValueError as exc:
        logger.warning("schedules.json is not valid JSON", extra={"error": str(exc)})
        return []
    if not isinstance(entries, list):
        logger.warning("schedules.json must contain a list")
        return []

    schedules: list[_NLSchedule] = []
    for entry in entries:
        if not isinstance(entry, dict):
            logger.warning("skipping non-object schedule entry")
            continue
        try:
            name = str(entry["name"])
            schedule_text = str(entry["schedule"])
            skill_name = str(entry["skill"])
            message = str(entry.get("message", ""))
        except KeyError as exc:
            logger.warning("skipping schedule entry missing key", extra={"key": str(exc)})
            continue
        try:
            spec = parse_nl_schedule(schedule_text)
        except ValueError as exc:
            logger.warning(
                "skipping unparseable schedule",
                extra={"name": name, "error": str(exc)},
            )
            continue
        schedules.append(
            _NLSchedule(name=name, spec=spec, skill=skill_name, message=message)
        )
    logger.info("loaded nl schedules", extra={"count": len(schedules)})
    return schedules


def _make_schedule_runner(schedule: _NLSchedule, engine: SkillEngine) -> TaskFactory:
    async def _run() -> str:
        return await engine.run_skill("daemon", schedule.skill, message=schedule.message)

    return _run


def _schedule_nl_dispatcher(
    scheduler: Scheduler,
    queue: InProcessQueue,
    engine: SkillEngine,
    schedules: list[_NLSchedule],
) -> None:
    """Every 60s, submit queue tasks for schedules whose time has come."""
    if not schedules:
        return
    started_at = datetime.now()
    last_fired: dict[str, datetime] = {}

    async def _dispatch() -> None:
        now = datetime.now()
        for schedule in schedules:
            previous = last_fired.get(schedule.name)
            anchor = (
                previous + timedelta(seconds=1)
                if previous is not None
                else started_at
            )
            try:
                due_at = next_run(schedule.spec, anchor)
            except ValueError as exc:
                logger.warning(
                    "schedule next_run failed",
                    extra={"schedule": schedule.name, "error": str(exc)},
                )
                continue
            if now >= due_at:
                last_fired[schedule.name] = now
                await queue.submit(
                    f"schedule:{schedule.name}",
                    _make_schedule_runner(schedule, engine),
                )
                logger.info(
                    "schedule fired",
                    extra={"schedule": schedule.name, "skill": schedule.skill},
                )

    scheduler.schedule("nl-schedules", _DISPATCH_INTERVAL_S, _dispatch)


async def _serve_forever(
    scheduler: Scheduler,
    queue: InProcessQueue,
    pid_file: Path,
    data_dir: Path,
    skill_count: int,
) -> None:
    """Run until SIGTERM/SIGINT, then stop jobs, drain the queue, exit."""
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError, ValueError) as exc:
            logger.warning(
                "signal handler unavailable", extra={"signal": sig, "error": str(exc)}
            )
    scheduler.start()
    logger.info(
        "inzo daemon started",
        extra={"data_dir": str(data_dir), "skills": skill_count, "pid": os.getpid()},
    )
    try:
        await stop.wait()
    except KeyboardInterrupt:
        logger.info("keyboard interrupt received")
    logger.info("inzo daemon stopping")
    await scheduler.stop()
    await queue.shutdown()
    _release_pid_file(pid_file)


def main(argv: list[str] | None = None) -> None:
    """Daemon entrypoint (``python -m inzo.daemon``)."""
    args = _build_parser().parse_args(argv)
    setup_logging("INFO")

    data_dir = Path(str(args.data_dir)).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    pid_file = (
        Path(str(args.pid_file)).expanduser()
        if args.pid_file
        else data_dir / "inzo-daemon.pid"
    )
    _claim_pid_file(pid_file)

    registry = build_skill_registry()
    event_bus = EventBus()
    notifications = NotificationCenter(data_dir, webhook_url=args.webhook_url)
    scheduler = Scheduler()
    queue = InProcessQueue()

    permissions = PermissionManager()
    for capability in DEFAULT_CAPABILITIES:
        permissions.grant("daemon", capability)

    engine = SkillEngine(
        registry=registry,
        permissions=permissions,
        memory=None,
        tools=None,
        data_dir=data_dir,
        scheduler=scheduler,
        notifications=notifications,
        event_bus=event_bus,
    )

    _wire_subscriptions(event_bus, notifications)
    tick_jobs = _schedule_ticks(scheduler, registry, engine)
    logger.info("background tick jobs scheduled", extra={"jobs": tick_jobs})
    _schedule_nl_dispatcher(scheduler, queue, engine, _load_schedules(data_dir))

    try:
        asyncio.run(
            _serve_forever(scheduler, queue, pid_file, data_dir, len(registry.all_skills()))
        )
    finally:
        _release_pid_file(pid_file)


if __name__ == "__main__":
    main()
