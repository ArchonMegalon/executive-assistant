from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Callable


def tool_shim_package_scope_text(latest_user_text: str) -> str:
    match = re.search(
        r"^[ \t]*Package scope:\s+([^\n]+)$",
        str(latest_user_text or ""),
        flags=re.MULTILINE,
    )
    if not match:
        return ""
    return str(match.group(1) or "").strip()


def tool_shim_bulleted_section_paths(latest_user_text: str, heading: str) -> list[str]:
    prompt = str(latest_user_text or "")
    if not prompt or not heading:
        return []
    marker = f"{heading}:"
    marker_index = prompt.find(marker)
    if marker_index < 0:
        return []
    trailing_lines = prompt[marker_index + len(marker):].splitlines()
    paths: list[str] = []
    seen_paths: set[str] = set()
    for raw_line in trailing_lines:
        line = str(raw_line or "").strip()
        if not line:
            if paths:
                break
            continue
        if not line.startswith("- "):
            if paths:
                break
            continue
        candidate = line[2:].strip()
        if candidate.startswith("`") and candidate.endswith("`") and len(candidate) >= 2:
            candidate = candidate[1:-1].strip()
        if not candidate.startswith("/"):
            if paths:
                break
            continue
        normalized_candidate = candidate.rstrip(",:;")
        if normalized_candidate in seen_paths:
            continue
        paths.append(normalized_candidate)
        seen_paths.add(normalized_candidate)
    return paths


def build_tool_shim_active_slice_followup_paths(
    *,
    is_package_work_prompt: Callable[[str], bool],
    tool_shim_bulleted_section_paths: Callable[[str, str], list[str]],
) -> Callable[[str], list[str]]:
    def tool_shim_active_slice_followup_paths(latest_user_text: str) -> list[str]:
        prompt = str(latest_user_text or "")
        if not is_package_work_prompt(prompt):
            return []
        result: list[str] = []
        seen_paths: set[str] = set()
        for heading, limit in (
            ("Edit these files first for this pass", 3),
            ("Map or strengthen these tests first for this pass", 2),
        ):
            for path_text in tool_shim_bulleted_section_paths(prompt, heading)[:limit]:
                if path_text in seen_paths:
                    continue
                result.append(path_text)
                seen_paths.add(path_text)
        return result

    tool_shim_active_slice_followup_paths.__name__ = "tool_shim_active_slice_followup_paths"
    tool_shim_active_slice_followup_paths.__qualname__ = "tool_shim_active_slice_followup_paths"
    return tool_shim_active_slice_followup_paths


def tool_shim_package_current_slice_text(latest_user_text: str) -> str:
    prompt = str(latest_user_text or "")
    if not prompt:
        return ""
    match = re.search(
        r"^[ \t]*Current slice:\s*(.*?)^\s*Package scope:\s+",
        prompt,
        flags=re.MULTILINE | re.DOTALL,
    )
    if not match:
        return ""
    return " ".join(str(match.group(1) or "").split())


def tool_shim_package_worktree(latest_user_text: str) -> str:
    match = re.search(
        r"^[ \t]*Isolated worktree:\s+([^\s].*)$",
        str(latest_user_text or ""),
        flags=re.MULTILINE,
    )
    if not match:
        return ""
    worktree = str(match.group(1) or "").strip()
    return worktree if worktree.startswith("/") else ""


def tool_shim_package_allowed_scope_tokens(latest_user_text: str) -> list[str]:
    match = re.search(
        r"^[ \t]*Allowed paths:\s+([^\n]+)$",
        str(latest_user_text or ""),
        flags=re.MULTILINE,
    )
    if not match:
        return []
    tokens: list[str] = []
    seen_tokens: set[str] = set()
    for raw_token in str(match.group(1) or "").split(","):
        token = str(raw_token or "").strip().strip("/")
        if (
            not token
            or token in seen_tokens
            or "*" in token
            or "?" in token
            or token.startswith(".")
        ):
            continue
        tokens.append(token)
        seen_tokens.add(token)
    return tokens


def build_tool_shim_package_allowed_scope_paths(
    *,
    tool_shim_package_worktree: Callable[[str], str],
    tool_shim_package_allowed_scope_tokens: Callable[[str], list[str]],
) -> Callable[[str], list[str]]:
    def tool_shim_package_allowed_scope_paths(latest_user_text: str) -> list[str]:
        worktree = tool_shim_package_worktree(latest_user_text)
        if not worktree:
            return []
        worktree_path = Path(worktree)
        scope_paths: list[str] = []
        seen_paths: set[str] = set()
        for token in tool_shim_package_allowed_scope_tokens(latest_user_text):
            candidate = str((worktree_path / token).resolve())
            if candidate in seen_paths:
                continue
            scope_paths.append(candidate)
            seen_paths.add(candidate)
        if scope_paths:
            return scope_paths
        return [str(worktree_path)]

    tool_shim_package_allowed_scope_paths.__name__ = "tool_shim_package_allowed_scope_paths"
    tool_shim_package_allowed_scope_paths.__qualname__ = "tool_shim_package_allowed_scope_paths"
    return tool_shim_package_allowed_scope_paths


def build_tool_shim_package_scope_pathspecs(
    *,
    tool_shim_package_worktree: Callable[[str], str],
    tool_shim_package_allowed_scope_paths: Callable[[str], list[str]],
) -> Callable[[str], list[str]]:
    def tool_shim_package_scope_pathspecs(latest_user_text: str) -> list[str]:
        worktree = tool_shim_package_worktree(latest_user_text)
        if not worktree:
            return []
        worktree_path = Path(worktree)
        pathspecs: list[str] = []
        seen_specs: set[str] = set()
        for absolute_path in tool_shim_package_allowed_scope_paths(latest_user_text):
            try:
                rel_path = str(Path(absolute_path).relative_to(worktree_path))
            except Exception:
                continue
            if rel_path.startswith("./"):
                rel_path = rel_path[2:]
            rel_path = rel_path.strip()
            if not rel_path or rel_path in seen_specs:
                continue
            pathspecs.append(rel_path)
            seen_specs.add(rel_path)
        return pathspecs

    tool_shim_package_scope_pathspecs.__name__ = "tool_shim_package_scope_pathspecs"
    tool_shim_package_scope_pathspecs.__qualname__ = "tool_shim_package_scope_pathspecs"
    return tool_shim_package_scope_pathspecs


def build_tool_shim_build_package_scope_repo_diff_command(
    *,
    tool_shim_package_worktree: Callable[[str], str],
    tool_shim_package_scope_pathspecs: Callable[[str], list[str]],
) -> Callable[[str], str | None]:
    def tool_shim_build_package_scope_repo_diff_command(latest_user_text: str) -> str | None:
        worktree = tool_shim_package_worktree(latest_user_text)
        pathspecs = tool_shim_package_scope_pathspecs(latest_user_text)
        if not worktree or not pathspecs:
            return None
        quoted_worktree = shlex.quote(worktree)
        quoted_paths = " ".join(shlex.quote(pathspec) for pathspec in pathspecs)
        return (
            f"git -C {quoted_worktree} status --short -- {quoted_paths}"
            f" ; git -C {quoted_worktree} diff --stat -- {quoted_paths}"
        )

    tool_shim_build_package_scope_repo_diff_command.__name__ = "tool_shim_build_package_scope_repo_diff_command"
    tool_shim_build_package_scope_repo_diff_command.__qualname__ = "tool_shim_build_package_scope_repo_diff_command"
    return tool_shim_build_package_scope_repo_diff_command


def build_tool_shim_build_package_scope_repo_hunks_command(
    *,
    tool_shim_package_worktree: Callable[[str], str],
    tool_shim_package_scope_pathspecs: Callable[[str], list[str]],
) -> Callable[[str], str | None]:
    def tool_shim_build_package_scope_repo_hunks_command(latest_user_text: str) -> str | None:
        worktree = tool_shim_package_worktree(latest_user_text)
        pathspecs = tool_shim_package_scope_pathspecs(latest_user_text)
        if not worktree or not pathspecs:
            return None
        quoted_worktree = shlex.quote(worktree)
        quoted_paths = " ".join(shlex.quote(pathspec) for pathspec in pathspecs)
        return f"git -C {quoted_worktree} diff --unified=0 -- {quoted_paths} | sed -n '1,120p'"

    tool_shim_build_package_scope_repo_hunks_command.__name__ = "tool_shim_build_package_scope_repo_hunks_command"
    tool_shim_build_package_scope_repo_hunks_command.__qualname__ = "tool_shim_build_package_scope_repo_hunks_command"
    return tool_shim_build_package_scope_repo_hunks_command


def build_tool_shim_package_scope_search_terms(
    *,
    tool_shim_package_current_slice_text: Callable[[str], str],
) -> Callable[[str], list[str]]:
    def tool_shim_package_scope_search_terms(latest_user_text: str) -> list[str]:
        current_slice = tool_shim_package_current_slice_text(latest_user_text)
        if not current_slice:
            return []
        stop_words = {
            "and",
            "artifact",
            "before",
            "coding",
            "compare",
            "compile",
            "current",
            "export",
            "for",
            "from",
            "house",
            "print",
            "proof",
            "proofs",
            "route",
            "routes",
            "specific",
            "supplement",
            "the",
            "then",
            "workflow",
            "workflows",
        }
        terms: list[str] = []
        seen_terms: set[str] = set()
        normalized_slice = current_slice.lower().replace("-", " ")
        for token in re.findall(r"[a-z0-9]{3,}", normalized_slice):
            if token in stop_words or token in seen_terms:
                continue
            terms.append(token)
            seen_terms.add(token)
            if len(terms) >= 8:
                break
        if "sr6" in normalized_slice and "sr6" not in seen_terms:
            terms.append("sr6")
            seen_terms.add("sr6")
        if "house rule" in normalized_slice and "house rule" not in seen_terms:
            terms.append("house rule")
        return terms

    tool_shim_package_scope_search_terms.__name__ = "tool_shim_package_scope_search_terms"
    tool_shim_package_scope_search_terms.__qualname__ = "tool_shim_package_scope_search_terms"
    return tool_shim_package_scope_search_terms


def build_tool_shim_build_package_scope_search_command(
    *,
    tool_shim_package_allowed_scope_paths: Callable[[str], list[str]],
    tool_shim_package_scope_search_terms: Callable[[str], list[str]],
) -> Callable[[str], str | None]:
    def tool_shim_build_package_scope_search_command(latest_user_text: str) -> str | None:
        scope_paths = tool_shim_package_allowed_scope_paths(latest_user_text)
        search_terms = tool_shim_package_scope_search_terms(latest_user_text)
        if not scope_paths or not search_terms:
            return None
        pattern_args = " ".join(
            f"-e {shlex.quote(term)}"
            for term in search_terms
            if str(term or "").strip()
        )
        if not pattern_args:
            return None
        quoted_paths = " ".join(shlex.quote(path_text) for path_text in scope_paths)
        return f"rg -n -i -F -m 80 {pattern_args} -- {quoted_paths} | sed -n '1,120p'"

    tool_shim_build_package_scope_search_command.__name__ = "tool_shim_build_package_scope_search_command"
    tool_shim_build_package_scope_search_command.__qualname__ = "tool_shim_build_package_scope_search_command"
    return tool_shim_build_package_scope_search_command
