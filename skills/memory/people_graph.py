"""People graph skill: persons, relations, and per-person preferences.

Real (deterministic, stdlib): a SQLite document store holds typed documents —
``{"type": "person", "name", ...}``, ``{"type": "relation", "a", "b",
"relation"}``, ``{"type": "preference", "person", "key", "value"}`` — with
helper functions to add and look them up.
"""

from __future__ import annotations

from typing import Any

from skills.base import Skill, SkillContext, require_data_dir
from storage.sqlite_store import SQLiteDocumentStore

_DB_NAME = "people.db"


def add_person(store: SQLiteDocumentStore, name: str, **attrs: Any) -> str:
    """Add a person document; returns the document id."""
    doc: dict[str, Any] = {"type": "person", "name": name}
    doc.update(attrs)
    return store.add(doc)


def add_relation(
    store: SQLiteDocumentStore, a: str, b: str, relation: str
) -> str:
    """Add a relation edge between two people; returns the document id."""
    return store.add({"type": "relation", "a": a, "b": b, "relation": relation})


def set_preference(
    store: SQLiteDocumentStore, person: str, key: str, value: str
) -> str:
    """Set a preference for a person; returns the document id."""
    return store.add(
        {"type": "preference", "person": person, "key": key, "value": value}
    )


def lookup(store: SQLiteDocumentStore, name: str) -> dict[str, Any]:
    """Return a person's profile: details, relations, and preferences."""
    people = [
        doc
        for doc in store.search(f"person {name}", limit=1000)
        if doc.get("type") == "person" and str(doc.get("name", "")).lower() == name.lower()
    ]
    person: dict[str, Any] = dict(people[0]) if people else {"name": name}
    relations: list[dict[str, Any]] = [
        dict(doc)
        for doc in store.search(f"relation {name}", limit=1000)
        if doc.get("type") == "relation"
        and name.lower() in (str(doc.get("a", "")).lower(), str(doc.get("b", "")).lower())
    ]
    preferences: dict[str, str] = {}
    for doc in store.search(f"preference {name}", limit=1000):
        if (
            doc.get("type") == "preference"
            and str(doc.get("person", "")).lower() == name.lower()
        ):
            preferences[str(doc.get("key", ""))] = str(doc.get("value", ""))
    return {"person": person, "relations": relations, "preferences": preferences}


class PeopleGraphSkill(Skill):
    """Maintains a graph of people, relations, and preferences."""

    name = "people_graph"
    description = "Stores people, their relations, and per-person preferences."
    intents = ("people.add", "people.lookup", "people.prefer")
    required_capabilities = ("skills.execute", "memory.write", "memory.read")
    background = True
    local_only = True

    async def handle(self, context: SkillContext) -> str:
        """Speak the message protocol.

        ``add person: <name>``, ``add relation: <a> | <b> | <relation>``,
        ``prefer: <person> | <key> = <value>``, ``lookup: <name>``.
        """
        data_dir = require_data_dir(context)
        store = SQLiteDocumentStore(data_dir / _DB_NAME)
        text = context.message.strip()
        lowered = text.lower()
        if lowered.startswith("add person:"):
            name = text.split(":", 1)[1].strip()
            if not name:
                return "people: usage is 'add person: <name>'"
            doc_id = add_person(store, name)
            return f"people: added '{name}' (id={doc_id})"
        if lowered.startswith("add relation:"):
            parts = [p.strip() for p in text.split(":", 1)[1].split("|")]
            if len(parts) != 3 or not all(parts):
                return "people: usage is 'add relation: <a> | <b> | <relation>'"
            doc_id = add_relation(store, parts[0], parts[1], parts[2])
            return f"people: '{parts[0]}' --{parts[2]}--> '{parts[1]}' (id={doc_id})"
        if lowered.startswith("prefer:"):
            rest = text.split(":", 1)[1]
            person, _, kv = rest.partition("|")
            key, _, value = kv.partition("=")
            person, key, value = person.strip(), key.strip(), value.strip()
            if not person or not key or not value:
                return "people: usage is 'prefer: <person> | <key> = <value>'"
            doc_id = set_preference(store, person, key, value)
            return f"people: preference saved for '{person}': {key}={value} (id={doc_id})"
        if lowered.startswith("lookup:"):
            name = text.split(":", 1)[1].strip()
            if not name:
                return "people: usage is 'lookup: <name>'"
            profile = lookup(store, name)
            person_doc = profile["person"]
            details = ", ".join(
                f"{k}={v}"
                for k, v in person_doc.items()
                if k not in ("id", "type", "name")
            )
            relations = "; ".join(
                f"{r.get('a')} --{r.get('relation')}--> {r.get('b')}"
                for r in profile["relations"]
            )
            prefs = ", ".join(
                f"{k}={v}" for k, v in profile["preferences"].items()
            )
            return (
                f"people: '{name}'"
                + (f" [{details}]" if details else "")
                + (f" | relations: {relations}" if relations else " | no relations")
                + (f" | preferences: {prefs}" if prefs else " | no preferences")
            )
        return (
            "people: use 'add person: <name>', 'add relation: <a> | <b> | <relation>', "
            "'prefer: <person> | <key> = <value>', or 'lookup: <name>'"
        )


SKILLS: list[Skill] = [PeopleGraphSkill()]
