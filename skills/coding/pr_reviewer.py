"""PR review skill: local unified-diff heuristics plus an optional GitHub adapter.

Local analysis is real and dependency-free: :func:`analyze_diff` parses a
unified diff and flags added functions missing docstrings, debug leftovers
(``print``/``breakpoint``/``pdb``), TODO/FIXME markers, and oversized
diffs.

Fetching a diff from GitHub goes through the :class:`GitHubAPI` Protocol.
The bundled :class:`UrllibGitHubAPI` is urllib-based and needs a
user-supplied personal access token; without one it raises
:class:`NotConfiguredError` instead of faking a review. This codebase never
stores tokens — pass the token in from your own config when wiring the
adapter.
"""

from __future__ import annotations

import re
import urllib.request
from typing import Protocol

from skills.base import Skill, SkillContext, SkillError


class NotConfiguredError(RuntimeError):
    """Raised when an external adapter is not wired up yet."""


class GitHubAPI(Protocol):
    """Boundary for fetching pull-request data from GitHub."""

    def fetch_diff(self, repo: str, pr_number: int) -> str:
        """Return the unified diff for ``repo`` pull request ``pr_number``."""
        ...


class UrllibGitHubAPI:
    """GitHubAPI over urllib (stdlib only).

    ``token`` must be a user-supplied personal access token with repository
    read access. It is kept in memory only for the life of this object and
    is never written to disk by this module.
    """

    _API = "https://api.github.com"

    def __init__(self, token: str | None = None) -> None:
        self._token = token

    def fetch_diff(self, repo: str, pr_number: int) -> str:
        """Fetch the PR diff via the GitHub REST API (diff media type)."""
        if not self._token:
            raise NotConfiguredError(
                "GitHub adapter has no token: construct UrllibGitHubAPI(token=...) "
                "with a user-supplied token before fetching PR diffs."
            )
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo or ""):
            raise ValueError(f"invalid repo slug: {repo!r}")
        url = f"{self._API}/repos/{repo}/pulls/{pr_number}"
        # S310 noqa below: repo slug is regex-validated; scheme/host are fixed.
        request = urllib.request.Request(  # noqa: S310
            url,
            headers={
                "Accept": "application/vnd.github.diff",
                "Authorization": f"Bearer {self._token}",
                "User-Agent": "inzo-pr-reviewer",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
                return bytes(response.read()).decode("utf-8", "replace")
        except OSError as exc:
            raise SkillError(f"github diff fetch failed: {exc}") from exc


_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_DEF_RE = re.compile(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_DEBUG_RE = re.compile(r"\b(print\(|breakpoint\(|pdb\.set_trace|ipdb|debugger\b|console\.log\()")
_TODO_RE = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")
_REPO_PR_RE = re.compile(r"repo=([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)\s+pr=(\d+)")

_MAX_DIFF_LINES = 500


def analyze_diff(diff: str) -> list[dict[str, str]]:
    """Analyze a unified diff; return findings as string-valued dicts.

    Each finding has ``severity`` (info/warning), ``rule``, ``line`` (new-file
    line number, "0" when not applicable), and ``detail``. The docstring
    check is textual: an added ``def`` whose next added line is not a
    docstring opener is flagged.
    """
    findings: list[dict[str, str]] = []
    lines = diff.splitlines()
    added = sum(1 for ln in lines if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in lines if ln.startswith("-") and not ln.startswith("---"))
    if added + removed > _MAX_DIFF_LINES:
        findings.append(
            {
                "severity": "info",
                "rule": "diff-too-large",
                "line": "0",
                "detail": (
                    f"diff touches {added + removed} lines "
                    f"(> {_MAX_DIFF_LINES}); consider splitting the PR"
                ),
            }
        )
    # Collect added lines with their new-file line numbers.
    numbered: list[tuple[int, str]] = []
    new_no = 0
    for ln in lines:
        hunk = _HUNK_RE.match(ln)
        if hunk:
            new_no = int(hunk.group(1))
            continue
        if ln.startswith("+") and not ln.startswith("+++"):
            numbered.append((new_no, ln[1:]))
            new_no += 1
        elif ln.startswith("-") and not ln.startswith("---"):
            continue
        else:
            new_no += 1
    for idx, (lineno, text) in enumerate(numbered):
        stripped = text.strip()
        if _TODO_RE.search(stripped):
            findings.append(
                {
                    "severity": "info",
                    "rule": "todo-marker",
                    "line": str(lineno),
                    "detail": f"TODO/FIXME marker left in added code: {stripped[:80]}",
                }
            )
        if _DEBUG_RE.search(stripped):
            findings.append(
                {
                    "severity": "warning",
                    "rule": "debug-leftover",
                    "line": str(lineno),
                    "detail": f"possible debug leftover: {stripped[:80]}",
                }
            )
        def_match = _DEF_RE.match(text)
        if def_match:
            next_added = numbered[idx + 1][1].strip() if idx + 1 < len(numbered) else ""
            if not (next_added.startswith('"""') or next_added.startswith("'''")):
                findings.append(
                    {
                        "severity": "info",
                        "rule": "missing-docstring",
                        "line": str(lineno),
                        "detail": f"added function '{def_match.group(1)}' has no docstring",
                    }
                )
    return findings


def _extract_diff(text: str) -> str:
    lowered = text.lower()
    marker = "diff="
    idx = lowered.find(marker)
    if idx != -1:
        return text[idx + len(marker) :].strip()
    stripped = text.lstrip()
    if stripped.startswith(("diff --git", "@@", "*** Begin Patch", "Index: ")):
        return text
    return ""


def _format_findings(findings: list[dict[str, str]]) -> str:
    if not findings:
        return "pr review: no issues found by local heuristics"
    lines = ["pr review findings:"]
    for item in findings:
        lines.append(
            f"[{item['severity']}] {item['rule']} (line {item['line']}): {item['detail']}"
        )
    return "\n".join(lines)


class PRReviewerSkill(Skill):
    """Reviews unified diffs with local heuristics; optional GitHub fetch."""

    name = "pr_reviewer"
    description = (
        "Reviews unified diffs with local heuristics (missing docstrings, "
        "debug leftovers, TODOs, oversized diffs); can fetch PR diffs from "
        "GitHub when a token-backed adapter is wired."
    )
    intents = ("pr.review",)
    required_capabilities = ("skills.execute", "network.fetch")
    background = True
    local_only = False
    adapter_note = (
        "Fetching PR diffs needs a user-supplied GitHub personal access token. "
        "Wire it with PRReviewerSkill(api=UrllibGitHubAPI(token=...)) outside "
        "this codebase; local diff analysis works with no adapter."
    )

    def __init__(self, api: GitHubAPI | None = None) -> None:
        self._api: GitHubAPI = api if api is not None else UrllibGitHubAPI()

    async def handle(self, context: SkillContext) -> str:
        text = context.message.strip()
        diff = _extract_diff(text)
        if diff:
            return _format_findings(analyze_diff(diff))
        repo_pr = _REPO_PR_RE.search(text)
        if repo_pr:
            repo, pr_number = repo_pr.group(1), int(repo_pr.group(2))
            try:
                fetched = self._api.fetch_diff(repo, pr_number)
            except NotConfiguredError as exc:
                return f"cannot fetch PR without a configured GitHub adapter: {exc}"
            except (SkillError, ValueError) as exc:
                return f"PR fetch failed: {exc}"
            return _format_findings(analyze_diff(fetched))
        return (
            "pr_reviewer: paste a unified diff after 'diff=' (or as the message) "
            "or give 'repo=owner/name pr=123'. Local analysis flags missing "
            "docstrings, debug leftovers, TODOs, and huge diffs."
        )


SKILLS: list[Skill] = [PRReviewerSkill()]
