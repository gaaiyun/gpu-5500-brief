"""Once-a-day guard for the group pushes: the scheduled run and its backups skip a channel that already delivered today."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "data/push_log.json"
TZ = timezone(timedelta(hours=8))


def today():
    return datetime.now(TZ).date().isoformat()


def load():
    try:
        log = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return log if isinstance(log, dict) else {}


def sent(channel):
    return load().get(channel) == today()


def record(channel):
    log = load()
    log[channel] = today()
    PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    action, channel = sys.argv[1], sys.argv[2]
    if action == "check":
        print("sent" if sent(channel) else "pending")
    elif action == "record":
        record(channel)
    else:
        sys.exit(f"unknown action {action}")
