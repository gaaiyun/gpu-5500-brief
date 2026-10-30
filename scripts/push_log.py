"""Once-a-day guard for the group pushes: the scheduled run and its backups skip a channel that already delivered today.

The first push of each report also keeps a copy of that state in data/reported/: the next morning report and the
day's flash alerts count changes from what the group last received."""
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "data/push_log.json"
STATE = PATH.parent / "state.json"
REPORTED = PATH.parent / "reported"
KEEP_REPORTS = 10
TZ = timezone(timedelta(hours=8))


def today():
    return datetime.now(TZ).date().isoformat()


def load():
    try:
        log = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return log if isinstance(log, dict) else {}


def save(log):
    PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sent(channel):
    return load().get(channel) == today()


def snapshot():
    """Keep the state a report was built from; a backup run that retries one channel later does not replace it."""
    state = json.loads(STATE.read_text(encoding="utf-8"))
    target = REPORTED / f"{state['date']}.json"
    if not target.exists():
        REPORTED.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(STATE, target)
    prune()


def prune():
    for old in sorted(REPORTED.glob("*.json"))[:-KEEP_REPORTS]:
        old.unlink()


def last_report(day, include_day=True):
    """The newest reported state dated on or before `day` (strictly before it when include_day is False)."""
    days = sorted(p for p in REPORTED.glob("*.json") if (p.stem <= day if include_day else p.stem < day))
    return json.loads(days[-1].read_text(encoding="utf-8")) if days else None


def record(channel):
    log = load()
    log[channel] = today()
    save(log)
    snapshot()


if __name__ == "__main__":
    action, channel = sys.argv[1], sys.argv[2]
    if action == "check":
        print("sent" if sent(channel) else "pending")
    elif action == "record":
        record(channel)
    else:
        sys.exit(f"unknown action {action}")
