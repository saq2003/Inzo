"""Workout planner skill (fully local, deterministic).

A built-in exercise database (bodyweight + gym, tagged by muscle group)
drives ``generate_plan``: pick a goal (strength|cardio|general), a level
(beginner|intermediate|advanced), and days per week (1–7), and get a
structured week plan. Exercise selection is deterministic rotation over
sorted lists — no randomness, no models, no network.
"""

from __future__ import annotations

from dataclasses import dataclass

from skills.base import Skill, SkillContext


@dataclass(frozen=True)
class Exercise:
    """One exercise with its muscle focus and equipment requirement."""

    name: str
    muscle: str
    equipment: str  # "bodyweight" or "gym"
    kind: str  # "strength" or "cardio"


@dataclass(frozen=True)
class PlanExercise:
    """One planned exercise with its set/rep prescription."""

    name: str
    muscle: str
    equipment: str
    sets: int
    reps: str


@dataclass(frozen=True)
class PlanDay:
    """One training day."""

    day: int
    focus: str
    exercises: tuple[PlanExercise, ...]


@dataclass(frozen=True)
class WeekPlan:
    """A structured weekly plan."""

    goal: str
    level: str
    days_per_week: int
    days: tuple[PlanDay, ...]


EXERCISES: tuple[Exercise, ...] = (
    Exercise("Push-up", "chest", "bodyweight", "strength"),
    Exercise("Pull-up", "back", "gym", "strength"),
    Exercise("Bodyweight Squat", "legs", "bodyweight", "strength"),
    Exercise("Barbell Squat", "legs", "gym", "strength"),
    Exercise("Deadlift", "back", "gym", "strength"),
    Exercise("Overhead Press", "shoulders", "gym", "strength"),
    Exercise("Pike Push-up", "shoulders", "bodyweight", "strength"),
    Exercise("Bench Press", "chest", "gym", "strength"),
    Exercise("Dumbbell Row", "back", "gym", "strength"),
    Exercise("Superman Hold", "back", "bodyweight", "strength"),
    Exercise("Plank", "core", "bodyweight", "strength"),
    Exercise("Hanging Leg Raise", "core", "gym", "strength"),
    Exercise("Bicycle Crunch", "core", "bodyweight", "strength"),
    Exercise("Lunge", "legs", "bodyweight", "strength"),
    Exercise("Romanian Deadlift", "legs", "gym", "strength"),
    Exercise("Dip", "arms", "gym", "strength"),
    Exercise("Diamond Push-up", "arms", "bodyweight", "strength"),
    Exercise("Burpee", "full body", "bodyweight", "cardio"),
    Exercise("Mountain Climber", "core", "bodyweight", "cardio"),
    Exercise("Jump Squat", "legs", "bodyweight", "cardio"),
    Exercise("Rowing Machine", "full body", "gym", "cardio"),
    Exercise("Treadmill Run", "full body", "gym", "cardio"),
    Exercise("Skipping", "legs", "bodyweight", "cardio"),
    Exercise("Box Step-up", "legs", "bodyweight", "strength"),
)

VOLUME: dict[str, tuple[int, str]] = {
    "beginner": (2, "10-12 reps"),
    "intermediate": (3, "8-12 reps"),
    "advanced": (4, "6-10 reps"),
}

GOALS = ("strength", "cardio", "general")
LEVELS = ("beginner", "intermediate", "advanced")


def _select(pool: list[Exercise], day_index: int, count: int) -> list[Exercise]:
    """Deterministically rotate through the sorted pool for a day's picks."""
    if not pool:
        return []
    pool = sorted(pool, key=lambda e: (e.muscle, e.name))
    offset = (day_index * count) % len(pool)
    return [pool[(offset + i) % len(pool)] for i in range(count)]


def generate_plan(goal: str, level: str, days_per_week: int) -> WeekPlan:
    """Build a structured week plan.

    ``goal``: strength | cardio | general. ``level``: beginner |
    intermediate | advanced. ``days_per_week``: 1–7.
    """
    if goal not in GOALS:
        raise ValueError(f"goal must be one of {GOALS}")
    if level not in LEVELS:
        raise ValueError(f"level must be one of {LEVELS}")
    if not 1 <= days_per_week <= 7:
        raise ValueError("days_per_week must be 1–7")
    sets, reps = VOLUME[level]
    strength = [e for e in EXERCISES if e.kind == "strength"]
    cardio = [e for e in EXERCISES if e.kind == "cardio"]
    per_day = 3 if goal == "cardio" else 4
    days: list[PlanDay] = []
    for day in range(1, days_per_week + 1):
        if goal == "strength":
            picks = _select(strength, day, per_day)
            focus = "full-body strength"
        elif goal == "cardio":
            picks = _select(cardio, day, per_day)
            focus = "cardio conditioning"
        else:
            picks = _select(strength, day, 3) + _select(cardio, day, 2)
            focus = "strength + cardio mix"
        days.append(
            PlanDay(
                day=day,
                focus=focus,
                exercises=tuple(
                    PlanExercise(
                        name=e.name,
                        muscle=e.muscle,
                        equipment=e.equipment,
                        sets=sets,
                        reps=reps,
                    )
                    for e in picks
                ),
            )
        )
    return WeekPlan(goal=goal, level=level, days_per_week=days_per_week, days=tuple(days))


class WorkoutPlannerSkill(Skill):
    """Generates deterministic weekly workout plans from a local DB."""

    name = "workout_planner"
    description = (
        "Builds a structured weekly workout plan from a built-in exercise "
        "database by goal (strength|cardio|general), level, and days/week."
    )
    intents = ("workout.plan",)
    required_capabilities = ("skills.execute",)
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        tokens = context.message.strip().lower().replace("=", " ").split()
        goal = "general"
        level = "beginner"
        days = 3
        for token in tokens:
            if token in GOALS:
                goal = token
            elif token in LEVELS:
                level = token
        for i, token in enumerate(tokens):
            if token in ("days", "day") and i + 1 < len(tokens):
                try:
                    days = int(tokens[i + 1])
                except ValueError:
                    pass
        try:
            plan = generate_plan(goal, level, days)
        except ValueError as exc:
            return f"could not build plan: {exc}"
        lines = [f"{plan.goal} plan — {plan.level}, {plan.days_per_week} days/week:"]
        for day in plan.days:
            lines.append(f"day {day.day} ({day.focus}):")
            for ex in day.exercises:
                lines.append(f"  - {ex.name} [{ex.muscle}, {ex.equipment}] {ex.sets}×{ex.reps}")
        return "\n".join(lines)


SKILLS: list[Skill] = [WorkoutPlannerSkill()]
