from __future__ import annotations

import json
import unittest
from pathlib import Path


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]
SKILL_DIRECTORY = PROJECT_DIRECTORY / "skills" / "a-share-fundamental"


def parse_frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise AssertionError("SKILL.md缺少起始frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise AssertionError("SKILL.md缺少结束frontmatter") from exc
    values: dict[str, str] = {}
    for line in lines[1:end]:
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip()] = value.strip()
    return values


class OpenClawSkillTests(unittest.TestCase):
    def test_skill_frontmatter_and_directory_name_match(self) -> None:
        skill_path = SKILL_DIRECTORY / "SKILL.md"
        content = skill_path.read_text(encoding="utf-8")
        metadata = parse_frontmatter(content)
        self.assertEqual(metadata["name"], SKILL_DIRECTORY.name)
        self.assertLessEqual(len(metadata["description"]), 160)
        runtime = json.loads(metadata["metadata"])
        self.assertEqual(
            runtime["openclaw"]["requires"]["anyBins"],
            ["python3", "python"],
        )

    def test_skill_references_exist_and_enforce_boundaries(self) -> None:
        content = (SKILL_DIRECTORY / "SKILL.md").read_text(encoding="utf-8")
        for filename in ("scoring-rubric.md", "output-contract.md"):
            self.assertTrue(
                (SKILL_DIRECTORY / "references" / filename).is_file()
            )
            self.assertIn(f"{{baseDir}}/references/{filename}", content)
        self.assertIn("Never edit Layer1", content)
        self.assertIn("Never invent", content)
        self.assertIn("as_of_date", content)
        self.assertIn("research/inbox/<code>.json", content)
        self.assertNotIn("C:\\Users", content)
        self.assertNotIn("/home/chen", content)

    def test_launcher_is_project_relative_and_does_not_eval_arguments(self) -> None:
        launcher = (
            PROJECT_DIRECTORY / "scripts" / "openclaw_research.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("/a-share-fundamental", launcher)
        self.assertIn('--cwd "${project_directory}"', launcher)
        self.assertIn("--timeout 0", launcher)
        self.assertNotIn("eval ", launcher)
        self.assertNotIn("/home/chen", launcher)


if __name__ == "__main__":
    unittest.main()
