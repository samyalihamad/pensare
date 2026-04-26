#!/usr/bin/env python3
"""update-memory.py — PostToolUse hook (matcher: Write|Edit)

Extracts actionable patterns from pensare context files and writes them
to MEMORY.md in all discovered Claude project memory directories.

Triggered after Write or Edit operations on pensare context files.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEBOUNCE_FILE = "/tmp/.pensare-memory-update-ts"
DEBOUNCE_SECONDS = 10
MAX_ITEMS_PER_CATEGORY = 18
MAX_MEMORY_LINES = 200

CONTEXTS_DIR = Path.home() / ".claude" / "contexts"
PROJECTS_DIR = Path.home() / ".claude" / "projects"

# Files to skip — these are structural, not knowledge sources
SKIP_FILENAMES = {"journal.md", "sources.json"}

# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

CLI_COMMANDS = re.compile(
    r"(?:^|\s|`)"
    r"((?:npm|cargo|make|docker|python3?|go|pip|yarn|gradle|mvn|bazel|cmake)"
    r"\s+[^\s`][^`\n]{0,120})"
    r"(?:`|$|\s)",
    re.MULTILINE,
)

URL_PATTERN = re.compile(
    r"(https?://[^\s\)\]\"'`>,;]+)",
    re.MULTILINE,
)

FILE_PATH_PATTERN = re.compile(
    r"(?:^|\s|`)"
    r"((?:src|lib|pkg|cmd|internal|app|config|test|tests|spec|docs|scripts|bin|tools)"
    r"/[A-Za-z0-9_/.\-]+)"
    r"(?:`|$|\s)",
    re.MULTILINE,
)

CONFIG_KEY_PATTERN = re.compile(
    r"\b([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*){2,})\b",
)

SERVICE_PATTERN = re.compile(
    r"\b(Redis|PostgreSQL|MySQL|MongoDB|Elasticsearch|Kafka|RabbitMQ|"
    r"Memcached|DynamoDB|Cassandra|SQLite|InfluxDB|Neo4j|CouchDB|"
    r"MariaDB|S3|GCS|BigQuery|Snowflake|Spark|Airflow|Celery|"
    r"Kubernetes|Docker|Nginx|Envoy|gRPC|GraphQL|REST\s+API)\b",
    re.IGNORECASE,
)

API_ENDPOINT_PATTERN = re.compile(
    r"((?:GET|POST|PUT|DELETE|PATCH)\s+/[a-zA-Z0-9_/\-{}]+)",
)


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------


def parse_stdin() -> dict:
    """Read and parse JSON from stdin. Returns empty dict on failure."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        return {}


def extract_hook_info(data: dict) -> tuple:
    """Extract tool_name and file_path from hook input JSON.

    Returns (tool_name, file_path) or (None, None) if not available.
    """
    tool_name = data.get("tool_name", data.get("toolName"))
    file_path = data.get("file_path", data.get("filePath"))

    # Try nested structures
    if not file_path:
        tool_input = data.get("tool_input", data.get("toolInput", {}))
        if isinstance(tool_input, dict):
            file_path = tool_input.get("file_path", tool_input.get("filePath"))

    return tool_name, file_path


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def should_process(file_path: str) -> bool:
    """Determine whether this file edit should trigger a memory update."""
    if not file_path:
        return False

    path = Path(file_path).resolve()
    contexts = CONTEXTS_DIR.resolve()

    # Must be under ~/.claude/contexts/
    try:
        path.relative_to(contexts)
    except ValueError:
        return False

    # Skip non-markdown files
    if path.suffix.lower() != ".md":
        return False

    # Skip structural files
    if path.name.lower() in SKIP_FILENAMES:
        return False

    return True


def check_debounce() -> bool:
    """Return True if enough time has passed since last run."""
    try:
        ts = float(Path(DEBOUNCE_FILE).read_text().strip())
        if time.time() - ts < DEBOUNCE_SECONDS:
            return False
    except (FileNotFoundError, ValueError, OSError):
        pass
    return True


def update_debounce():
    """Write current timestamp to debounce file."""
    try:
        Path(DEBOUNCE_FILE).write_text(str(time.time()))
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Project discovery
# ---------------------------------------------------------------------------


def find_project_dir(file_path: str) -> Path | None:
    """Find the pensare project directory containing the edited file.

    The project directory is the first subdirectory under ~/.claude/contexts/.
    """
    path = Path(file_path).resolve()
    contexts = CONTEXTS_DIR.resolve()

    try:
        relative = path.relative_to(contexts)
    except ValueError:
        return None

    # The project dir is the first component
    parts = relative.parts
    if not parts:
        return None

    return contexts / parts[0]


def collect_project_content(project_dir: Path) -> str:
    """Read and concatenate all .md files in the project directory."""
    if not project_dir.is_dir():
        return ""

    content_parts = []
    for md_file in sorted(project_dir.glob("*.md")):
        if md_file.name.lower() in SKIP_FILENAMES:
            continue
        try:
            text = md_file.read_text(encoding="utf-8", errors="replace")
            if text.strip():
                content_parts.append(text)
        except OSError:
            continue

    # Also check one level of subdirectories for kb/ or similar
    for subdir in sorted(project_dir.iterdir()):
        if subdir.is_dir() and not subdir.name.startswith("."):
            for md_file in sorted(subdir.glob("*.md")):
                if md_file.name.lower() in SKIP_FILENAMES:
                    continue
                try:
                    text = md_file.read_text(encoding="utf-8", errors="replace")
                    if text.strip():
                        content_parts.append(text)
                except OSError:
                    continue

    return "\n\n".join(content_parts)


# ---------------------------------------------------------------------------
# Pattern extraction
# ---------------------------------------------------------------------------


def extract_patterns(content: str) -> dict:
    """Extract actionable patterns from content across 5 categories."""
    patterns = {
        "CLI": set(),
        "URL": set(),
        "File": set(),
        "Config": set(),
        "Service": set(),
    }

    # CLI commands
    for match in CLI_COMMANDS.finditer(content):
        cmd = match.group(1).strip()
        if len(cmd) > 10:  # Skip trivially short matches
            patterns["CLI"].add(cmd)

    # URLs
    for match in URL_PATTERN.finditer(content):
        url = match.group(1).rstrip(".")
        # Skip very long URLs (tracking params, etc.)
        if len(url) <= 200:
            patterns["URL"].add(url)

    # File paths
    for match in FILE_PATH_PATTERN.finditer(content):
        fp = match.group(1).strip()
        if len(fp) > 5:
            patterns["File"].add(fp)

    # Config keys (dotted identifiers with 3+ segments)
    for match in CONFIG_KEY_PATTERN.finditer(content):
        key = match.group(1)
        # Filter out things that look like version numbers or URLs
        if not re.match(r"^\d", key) and ".." not in key:
            patterns["Config"].add(key)

    # Services and databases
    for match in SERVICE_PATTERN.finditer(content):
        patterns["Service"].add(match.group(1))

    # API endpoints
    for match in API_ENDPOINT_PATTERN.finditer(content):
        patterns["Service"].add(match.group(1))

    return patterns


# ---------------------------------------------------------------------------
# Memory formatting
# ---------------------------------------------------------------------------


def format_section(project_name: str, patterns: dict) -> str:
    """Format extracted patterns into a MEMORY.md section."""
    lines = [f"## {project_name}", ""]

    total_items = 0

    for category, items in patterns.items():
        if not items or total_items >= MAX_ITEMS_PER_CATEGORY:
            continue

        remaining = MAX_ITEMS_PER_CATEGORY - total_items
        sorted_items = sorted(items)[:remaining]

        if not sorted_items:
            continue

        lines.append(f"### {category}")
        for item in sorted_items:
            lines.append(f"- `{item}`")
            total_items += 1
        lines.append("")

    # If no patterns were found, add a minimal note
    if total_items == 0:
        lines.append("_No actionable patterns extracted yet._")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Memory file management
# ---------------------------------------------------------------------------


def find_memory_files() -> list:
    """Find all MEMORY.md files under ~/.claude/projects/*/memory/."""
    results = []
    if not PROJECTS_DIR.is_dir():
        return results

    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        memory_dir = project_dir / "memory"
        memory_file = memory_dir / "MEMORY.md"
        if memory_file.is_file():
            results.append(memory_file)

    return results


def update_memory_file(memory_file: Path, project_name: str, new_section: str):
    """Update a MEMORY.md file with the new project section.

    Replaces the existing section for this project, or appends if new.
    Respects the 200-line limit.
    """
    try:
        existing = memory_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        existing = ""

    # Pattern to match the full section: from ## {project_name} to the next
    # ## heading or end of file
    escaped_name = re.escape(project_name)
    section_pattern = re.compile(
        rf"^## {escaped_name}\s*\n.*?(?=^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )

    match = section_pattern.search(existing)
    if match:
        # Replace existing section
        updated = (
            existing[: match.start()] + new_section + "\n" + existing[match.end() :]
        )
    else:
        # Append new section
        separator = "\n" if existing and not existing.endswith("\n") else ""
        extra_newline = "\n" if existing.strip() else ""
        updated = existing + separator + extra_newline + new_section + "\n"

    # Enforce line limit
    lines = updated.split("\n")
    if len(lines) > MAX_MEMORY_LINES:
        updated = "\n".join(lines[:MAX_MEMORY_LINES]) + "\n"

    # Only write if content actually changed
    if updated.strip() == existing.strip():
        return False

    try:
        memory_file.write_text(updated, encoding="utf-8")
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    # 1. Parse hook input
    data = parse_stdin()
    tool_name, file_path = extract_hook_info(data)

    # 2. Guard: only process relevant file edits
    if not should_process(file_path):
        sys.exit(0)

    # 3. Debounce
    if not check_debounce():
        sys.exit(0)

    # 4. Find the project directory and name
    project_dir = find_project_dir(file_path)
    if not project_dir or not project_dir.is_dir():
        sys.exit(0)

    project_name = project_dir.name

    # 5. Collect all markdown content from the project
    content = collect_project_content(project_dir)
    if not content.strip():
        sys.exit(0)

    # 6. Extract patterns
    patterns = extract_patterns(content)

    # 7. Format the section
    section = format_section(project_name, patterns)

    # 8. Find and update all MEMORY.md files
    memory_files = find_memory_files()
    if not memory_files:
        sys.exit(0)

    any_updated = False
    for mf in memory_files:
        if update_memory_file(mf, project_name, section):
            any_updated = True

    # 9. Update debounce timestamp
    if any_updated:
        update_debounce()


if __name__ == "__main__":
    main()
