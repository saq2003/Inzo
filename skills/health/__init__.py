"""Health skills: sleep analysis, workout planning, med reminders, mood, diet.

Every skill here is deterministic, stdlib-only, and fully local
(``local_only=True``). They read exports / user input, compute real
statistics or plans, and persist to ``data_dir/"health.db"``. No
hardware, no network, no paid keys.
"""
