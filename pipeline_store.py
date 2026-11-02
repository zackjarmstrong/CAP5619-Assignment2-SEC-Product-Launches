"""Atomic public-data checkpoints and a persistent, fail-closed request budget."""
import csv
import hashlib
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

AUTHORIZATION_LIMIT = 180  # Three explicit 60-attempt grants; cumulative, never per run.
AUDIT_DIR = Path("audit")
LEDGER = AUDIT_DIR / "api_requests.json"


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def replace_checkpoint(temporary, destination):
    """Allow brief Windows reader/antivirus locks without abandoning a checkpoint."""
    for attempt in range(5):
        try:
            temporary.replace(destination)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.1 * (attempt + 1))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    replace_checkpoint(temporary, path)


def load_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_rows(path):
    if not Path(path).exists():
        return []
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def save_rows(path, rows, columns):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        stream.flush()
        os.fsync(stream.fileno())
    replace_checkpoint(temporary, path)


def filing_id(url):
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]


def journal_path(url):
    return AUDIT_DIR / "filings" / (filing_id(url) + ".json")


def request_history():
    if not LEDGER.exists() and (any((AUDIT_DIR / "responses").glob("*.json"))
                               or any((AUDIT_DIR / "filings").glob("*.json"))
                               or any(grant.get("starting_attempts", 0) > 0 for grant in
                                      load_json(AUDIT_DIR / "authorizations.json", []))):
        raise ValueError("Request ledger is missing beside existing paid checkpoints; restore it")
    value = load_json(LEDGER, [])
    if not isinstance(value, list):
        raise ValueError("Invalid request ledger; restore it before any paid run")
    for i, row in enumerate(value, 1):
        if row.get("attempt") != i or not row.get("filing_url"):
            raise ValueError("Corrupt request ledger; refusing paid requests")
    return value


def reserve_request(url, model):
    """Persist BEFORE sending. An interrupted attempt still consumes a slot."""
    rows = request_history()
    if len(rows) >= AUTHORIZATION_LIMIT:
        raise RuntimeError(f"The cumulative {AUTHORIZATION_LIMIT}-request authorization is exhausted")
    row = {"attempt": len(rows) + 1, "filing_url": url, "model": model,
           "started_utc": utc_now(), "status": "reserved"}
    rows.append(row)
    atomic_json(LEDGER, rows)
    return row["attempt"]


def finish_request(attempt, **details):
    rows = request_history()
    rows[attempt - 1].update(details, finished_utc=utc_now())
    atomic_json(LEDGER, rows)


@contextmanager
def exclusive_run():
    """One writer protects the cap and checkpoints across concurrent processes."""
    path = Path(".pipeline.lock")
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise RuntimeError("Another run owns .pipeline.lock. If it crashed, confirm "
                           "that it stopped before removing that lock.") from None
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        path.unlink(missing_ok=True)
