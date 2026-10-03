"""Research skills: web research, document Q&A, video summaries, news, fact-checks.

``video_summary`` needs a transcript provider through its ``Protocol``
adapter and is therefore ``local_only=False``. Everything else runs
fully locally on the stdlib with bounded public-web fetching (urllib,
timeouts, retries with backoff).
"""
