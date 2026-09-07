"""Windows/local supervisor: one owner, durable health, independent feed publisher."""
import argparse
import contextlib
import json
import logging
from logging.handlers import RotatingFileHandler
import socket
import subprocess
import time

from .config import SETTINGS
from .feed import FEED_PATH
from .hunter import Hunter
from .publish import publish_feed
from .sources import GeckoTerminal
from .storage import RUNTIME, RULES_VERSION, atomic_json


def runner_owner(repo):
    p = subprocess.run(["gh", "api", f"repos/{repo}/actions/variables/MH_RUNNER", "--jq", ".value"],
                       capture_output=True, text=True, timeout=30)
    if p.returncode:
        raise RuntimeError("Cannot verify MH_RUNNER ownership with gh")
    return p.stdout.strip()


class LogStream:
    def __init__(self, logger): self.logger = logger
    def write(self, text):
        if text.strip(): self.logger.info(text.rstrip())
        return len(text)
    def flush(self): pass
    def isatty(self): return False


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="mobius0087x/meme-hunter")
    ap.add_argument("--check", action="store_true", help="Read-only source preflight; no notifications or state changes")
    args = ap.parse_args(argv)
    if args.check:
        gt = GeckoTerminal()
        pools = gt.new_pools() + gt.trending_pools()
        if not pools or not all(r["ok"] for r in gt.requests):
            raise SystemExit("Preflight failed: discovery sources incomplete; cloud remains owner")
        print(f"Preflight OK: {len(pools)} pool rows; rules={RULES_VERSION}; no notifications sent")
        return
    # OS releases this lock on crashes; no stale PID lock files on Windows.
    with socket.socket() as lock:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            lock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        lock.bind(("127.0.0.1", 46630))
        lock.listen(1)
        RUNTIME.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger("memehunter-service")
        logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(RUNTIME / "service.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(handler)
        with contextlib.redirect_stdout(LogStream(logger)), contextlib.redirect_stderr(LogStream(logger)):
            hunter = Hunter()
            health = {"rules_version": RULES_VERSION, "started_at": time.time(), "runner": "windows",
                      "last_cycle_at": None, "last_publish_at": None}
            last_publish = 0
            failures = 0
            while True:
                start = time.monotonic()
                # Fail closed on ownership/API failure before producing alerts.
                try:
                    owner = runner_owner(args.repo)
                except Exception:
                    health.update(status="owner_check_failed", checked_at=time.time())
                    atomic_json(RUNTIME / "health.json", health)
                    raise
                if owner != "windows":
                    health.update(status="not_owner", checked_at=time.time())
                    atomic_json(RUNTIME / "health.json", health)
                    return
                try:
                    hunter.run_cycle()
                    health.update(status="running", last_cycle_at=time.time())
                    if time.time() - last_publish >= 300:
                        sha = publish_feed(FEED_PATH, f"https://github.com/{args.repo}.git", RUNTIME / "publisher.git")
                        last_publish = time.time()
                        health.update(last_publish_at=last_publish, published_commit=sha)
                    failures = 0
                except Exception as exc:
                    failures += 1
                    logger.exception("cycle or publication failed")
                    health.update(status="degraded", error=type(exc).__name__)
                atomic_json(RUNTIME / "health.json", health)
                if failures >= 5:
                    raise RuntimeError("Five consecutive failures; supervisor restart required")
                time.sleep(max(1, SETTINGS.poll_seconds - (time.monotonic() - start)))


if __name__ == "__main__":
    main()
