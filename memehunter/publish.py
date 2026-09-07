"""Publish only feed/signals.json without touching the running code checkout."""
import json
import os
import subprocess
import tempfile
from pathlib import Path


def git(*args, cwd, data=None, env=None):
    proc = subprocess.run(["git", *args], cwd=cwd, input=data, capture_output=True,
                          env=env, timeout=90)
    if proc.returncode:
        raise RuntimeError(f"git {args[0]} failed (exit {proc.returncode})")
    return proc.stdout.decode().strip()


def publish_feed(feed: Path, remote: str, store: Path) -> str:
    data = feed.read_bytes()
    payload = json.loads(data)
    if payload.get("chain") != "robinhood" or not isinstance(payload.get("generated_at"), int):
        raise ValueError("Invalid feed")
    store.mkdir(parents=True, exist_ok=True)
    if not (store / "HEAD").exists():
        git("init", "--bare", cwd=store)
    env = os.environ.copy()
    env.update(GIT_AUTHOR_NAME="meme-hunter-windows", GIT_AUTHOR_EMAIL="meme-hunter@users.noreply.github.com",
               GIT_COMMITTER_NAME="meme-hunter-windows", GIT_COMMITTER_EMAIL="meme-hunter@users.noreply.github.com",
               GIT_TERMINAL_PROMPT="0")
    # Every retry starts with the remote tree, preserving concurrent code commits.
    for attempt in range(3):
        git("fetch", "--depth=1", remote, "main", cwd=store, env=env)
        parent = git("rev-parse", "FETCH_HEAD", cwd=store, env=env)
        try:
            previous = json.loads(git("show", parent + ":feed/signals.json", cwd=store, env=env))
        except (RuntimeError, ValueError):
            previous = {}
        if previous.get("generated_at", 0) > payload["generated_at"]:
            raise ValueError("Refusing to overwrite a newer remote feed; check clock and runner ownership")
        with tempfile.TemporaryDirectory(dir=store) as tmp:
            env["GIT_INDEX_FILE"] = str(Path(tmp) / "index")
            git("read-tree", parent, cwd=store, env=env)
            blob = git("hash-object", "-w", "--stdin", cwd=store, data=data, env=env)
            git("update-index", "--add", "--cacheinfo", "100644", blob, "feed/signals.json", cwd=store, env=env)
            tree = git("write-tree", cwd=store, env=env)
            if tree == git("rev-parse", parent + "^{tree}", cwd=store, env=env):
                return parent
            commit = git("commit-tree", tree, "-p", parent, cwd=store, env=env,
                         data=f"feed: windows {payload['generated_at']}\n".encode())
        try:
            git("push", remote, f"{commit}:refs/heads/main", cwd=store, env=env)
            return commit
        except RuntimeError:
            if attempt == 2:
                raise
    raise RuntimeError("Feed publish exhausted retries")
