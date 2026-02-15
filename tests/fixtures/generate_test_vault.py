"""Generate a synthetic Obsidian vault for performance testing.

Usage:
    python -m tests.fixtures.generate_test_vault [--notes 100] [--output /tmp/perf_vault]
"""

import argparse
import os
import random

_TOPICS = [
    "architecture",
    "deployment",
    "database",
    "monitoring",
    "testing",
    "security",
    "performance",
    "networking",
    "containers",
    "ci-cd",
    "observability",
    "microservices",
    "api-design",
    "authentication",
    "caching",
]

_TAGS = [
    "project",
    "concept",
    "decision",
    "meeting",
    "review",
    "planning",
    "devops",
    "backend",
    "frontend",
    "infrastructure",
]

_FOLDERS = ["projects", "concepts", "meetings", "decisions", "daily"]

_LOREM = (
    "Lorem ipsum dolor sit amet consectetur adipiscing elit. "
    "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. "
    "Ut enim ad minim veniam quis nostrud exercitation ullamco laboris. "
    "Duis aute irure dolor in reprehenderit in voluptate velit esse cillum. "
    "Excepteur sint occaecat cupidatat non proident sunt in culpa qui officia. "
)


def generate_note(note_id: int, all_stems: list[str]) -> str:
    """Generate a single markdown note with frontmatter, headings, and links."""
    topic = random.choice(_TOPICS)
    tags = random.sample(_TAGS, k=min(3, len(_TAGS)))
    title = f"{topic.title()} Note {note_id}"

    # Build frontmatter
    tags_yaml = "\n".join(f"  - {t}" for t in tags)
    frontmatter = f"---\ntitle: {title}\ntags:\n{tags_yaml}\n---\n\n"

    # Build body with headings
    sections = []
    sections.append(f"# {title}\n\n{_LOREM}\n")

    for i in range(random.randint(2, 5)):
        heading = f"## Section {i + 1}: {random.choice(_TOPICS).title()}\n\n"
        body = _LOREM * random.randint(1, 4) + "\n"

        # Add some wikilinks
        link_targets = random.sample(all_stems, k=min(2, len(all_stems)))
        links = " ".join(f"[[{t}]]" for t in link_targets)
        body += f"\nRelated: {links}\n"

        # Occasionally add sub-headings
        if random.random() > 0.5:
            body += f"\n### Detail {i + 1}.1\n\n{_LOREM}\n"

        sections.append(heading + body)

    return frontmatter + "\n".join(sections)


def generate_vault(output_dir: str, num_notes: int) -> None:
    """Generate a vault with the specified number of notes."""
    os.makedirs(output_dir, exist_ok=True)
    for folder in _FOLDERS:
        os.makedirs(os.path.join(output_dir, folder), exist_ok=True)

    # Pre-generate all stems so notes can link to each other
    stems: list[str] = []
    paths: list[str] = []
    for i in range(num_notes):
        folder = random.choice(_FOLDERS)
        topic = random.choice(_TOPICS)
        stem = f"{topic}-{i}"
        filename = f"{stem}.md"
        rel_path = os.path.join(folder, filename)
        stems.append(stem)
        paths.append(rel_path)

    # Generate and write each note
    for i, rel_path in enumerate(paths):
        abs_path = os.path.join(output_dir, rel_path)
        content = generate_note(i, stems)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(content)

    print(f"Generated {num_notes} notes in {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a synthetic test vault")
    parser.add_argument("--notes", type=int, default=100, help="Number of notes")
    parser.add_argument("--output", type=str, default="/tmp/perf_vault", help="Output dir")
    args = parser.parse_args()
    generate_vault(args.output, args.notes)


if __name__ == "__main__":
    main()
