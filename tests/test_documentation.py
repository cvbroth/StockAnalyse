from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

from app.cli.daily import build_parser as daily_parser
from app.cli.evaluate import build_parser as evaluate_parser
from app.cli.fundamentals import build_parser as fundamentals_parser
from app.cli.pipeline import build_parser as pipeline_parser
from app.cli.report import build_parser as report_parser
from app.cli.report_weekly import build_parser as weekly_report_parser
from app.cli.research import build_parser as research_parser
from app.services.market_update import build_parser as update_parser
from app.services.screening import build_parser as screen_parser


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]
DOCS_DIRECTORY = PROJECT_DIRECTORY / "docs"


class DocumentationTests(unittest.TestCase):
    def test_reference_documents_exist_and_are_linked_from_readme(self) -> None:
        filenames = (
            "DEPLOYMENT.md",
            "PARAMETERS.md",
            "TECHNICAL_FORMULAS.md",
            "FUNDAMENTAL_FORMULAS.md",
            "REPORTING.md",
        )
        readme = (PROJECT_DIRECTORY / "README.md").read_text(encoding="utf-8")
        for filename in filenames:
            with self.subTest(filename=filename):
                self.assertTrue((DOCS_DIRECTORY / filename).is_file())
                self.assertIn(f"docs/{filename}", readme)

    def test_parameter_manual_covers_every_toml_key(self) -> None:
        manual = (DOCS_DIRECTORY / "PARAMETERS.md").read_text(encoding="utf-8")
        for filename in ("layer1.toml", "layer2.toml", "fundamental.toml"):
            path = PROJECT_DIRECTORY / "config" / "analysis" / filename
            with path.open("rb") as handle:
                payload = tomllib.load(handle)
            keys = set(payload)
            for value in payload.values():
                if isinstance(value, dict):
                    keys.update(value)
            for key in sorted(keys):
                with self.subTest(filename=filename, key=key):
                    self.assertIn(f"`{key}`", manual)

    def test_parameter_manual_covers_every_long_cli_option(self) -> None:
        manual = (DOCS_DIRECTORY / "PARAMETERS.md").read_text(encoding="utf-8")
        parsers = (
            update_parser(),
            screen_parser(),
            daily_parser(),
            fundamentals_parser(),
            research_parser(),
            report_parser(),
            weekly_report_parser(),
            pipeline_parser(),
            evaluate_parser(),
        )
        for parser in parsers:
            for action in parser._actions:
                for option in action.option_strings:
                    if option.startswith("--") and option != "--help":
                        with self.subTest(command=parser.prog, option=option):
                            self.assertIn(f"`{option}", manual)

    def test_formula_manuals_name_the_implementation_boundaries(self) -> None:
        technical = (DOCS_DIRECTORY / "TECHNICAL_FORMULAS.md").read_text(
            encoding="utf-8"
        )
        fundamental = (DOCS_DIRECTORY / "FUNDAMENTAL_FORMULAS.md").read_text(
            encoding="utf-8"
        )
        for condition in (
            "price_structure",
            "ma_trend",
            "volume_price",
            "breakout_retest",
            "relative_strength",
        ):
            self.assertIn(f"`{condition}`", technical)
        for score in (
            "earnings_momentum",
            "business_quality",
            "industry_cycle",
            "expectation_delta",
            "risk_penalty",
            "final_score",
        ):
            self.assertIn(score, fundamental)


if __name__ == "__main__":
    unittest.main()
