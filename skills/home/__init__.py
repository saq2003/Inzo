"""Home automation skills: lights, temperature, camera Q&A, appliance schedules.

Every skill here needs real hardware (a light hub, a temperature sensor, a
camera, smart plugs) through a ``Protocol`` adapter and is therefore
``local_only=False``. Each module ships a stub adapter that raises
``NotConfigured`` so the skill fails honestly instead of faking results.
Scheduling, validation, logging, threshold checks, and energy math are
fully real and local (stdlib only, ``data_dir/"home.db"``).
"""
