# Agent handoff

Read [MEMO.md](MEMO.md) before working in this repository. [WINDOWS.md](WINDOWS.md) defines the Windows takeover and recovery procedure. Keep actual runtime status distinct from code/CI readiness and update the memo after verifying a takeover.

This is a read-only monitoring and research project: no wallet signing or order execution. Do not commit .env, state.json or .runtime data. Run `python -m unittest discover -s tests -v` for implementation changes; documentation-only handoffs need link/content checks, not market or notification calls.
