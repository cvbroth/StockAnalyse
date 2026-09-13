"""项目配置和数据库质量检查。"""

from __future__ import annotations

import sys
import tempfile
import types
import unittest
import json
from datetime import date, timedelta
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "app"))

try:
    import pandas  # noqa: F401
except ModuleNotFoundError:
    # 本组测试只验证SQLite查询，不调用依赖pandas的数据帧函数。
    sys.modules["pandas"] = types.ModuleType("pandas")

from market_db import connect_database, database_quality_report, set_metadata
from project_config import (
    resolve_database_path,
    resolve_fundamental_database_path,
    resolve_output_path,
    save_project_config,
)


class ProjectConfigTests(unittest.TestCase):
    def test_saved_database_becomes_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            database = project / "data" / "market_tx.db"
            config_path = project / "config" / "project.json"
            save_project_config(
                database,
                "tx",
                project_dir=project,
                config_path=config_path,
            )

            selected_db, db_source = resolve_database_path(
                None, project_dir=project, config_path=config_path
            )
            selected_output, output_source = resolve_output_path(
                None, project_dir=project, config_path=config_path
            )

            self.assertEqual(selected_db, database.resolve())
            self.assertEqual(db_source, "项目配置")
            self.assertEqual(selected_output, (project / "output").resolve())
            self.assertEqual(output_source, "项目配置")
            selected_fundamental, fundamental_source = (
                resolve_fundamental_database_path(
                    None, project_dir=project, config_path=config_path
                )
            )
            self.assertEqual(
                selected_fundamental,
                (project / "data" / "fundamentals.db").resolve(),
            )
            self.assertEqual(fundamental_source, "项目配置")

    def test_command_line_database_overrides_project_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            config_path = project / "config" / "project.json"
            save_project_config(
                project / "data" / "configured.db",
                "tx",
                project_dir=project,
                config_path=config_path,
            )
            explicit = project / "data" / "explicit.db"
            selected, source = resolve_database_path(
                explicit, project_dir=project, config_path=config_path
            )
            self.assertEqual(selected, explicit.resolve())
            self.assertEqual(source, "命令行 --db")

    def test_invalid_project_config_fails_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            config_path = project / "config" / "project.json"
            config_path.parent.mkdir(parents=True)
            config_path.write_text("{not-json", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "无法读取项目配置"):
                resolve_database_path(
                    None, project_dir=project, config_path=config_path
                )

    def test_saved_paths_are_portable_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            config_path = project / "config" / "project.json"
            save_project_config(
                project / "data" / "market.db",
                "tx",
                output_directory=project / "output",
                project_dir=project,
                config_path=config_path,
            )
            payload = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["database"], "data/market.db")
            self.assertEqual(
                payload["fundamental_database"], "data/fundamentals.db"
            )
            self.assertEqual(payload["output_directory"], "output")


class DatabaseQualityTests(unittest.TestCase):
    def test_complete_database_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = connect_database(Path(directory) / "market.db")
            try:
                set_metadata(connection, "data_provider", "tx")
                connection.execute(
                    """
                    INSERT INTO securities(code, name, market, active, updated_at)
                    VALUES('600000', '测试股票', 'SH', 1, 'now')
                    """
                )
                dates = [
                    (date(2025, 1, 1) + timedelta(days=offset)).strftime("%Y%m%d")
                    for offset in range(120)
                ]
                daily_rows = [
                    (
                        "600000", trade_date, 1.0, 2.0, 0.5, 1.5,
                        100.0, 1000.0, 1.0, "akshare_tencent_qfq", "now",
                    )
                    for trade_date in dates
                ]
                connection.executemany(
                    "INSERT INTO daily_bars VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    daily_rows,
                )
                index_rows = [
                    (
                        "sh000300", trade_date, 1.0, 2.0, 0.5, 1.5,
                        100.0, "akshare_tencent", "now",
                    )
                    for trade_date in dates[-61:]
                ]
                connection.executemany(
                    "INSERT INTO index_bars VALUES(?,?,?,?,?,?,?,?,?)",
                    index_rows,
                )
                connection.commit()

                report = database_quality_report(connection, 120)
                self.assertTrue(report["passed"], report["errors"])
                self.assertEqual(report["codes_with_history"], 1)
            finally:
                connection.close()

    def test_empty_database_fails_before_screening(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            connection = connect_database(Path(directory) / "market.db")
            try:
                set_metadata(connection, "data_provider", "tx")
                connection.commit()
                report = database_quality_report(connection, 120)
                self.assertFalse(report["passed"])
                self.assertIn("股票列表为空", report["errors"])
                self.assertIn("个股日线为空", report["errors"])
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
