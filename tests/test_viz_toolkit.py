"""
tests/test_viz_toolkit.py
=========================
Unit tests for the gsa_graj_viz toolkit.

Tests are OFFLINE — no real PostgreSQL connection is needed.
All pg8000 calls are mocked via unittest.mock so the suite runs in CI
without credentials.

Run with:
    python -m pytest tests/test_viz_toolkit.py -v
or simply:
    python tests/test_viz_toolkit.py
"""

from __future__ import annotations

import importlib
import io
import json
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Bootstrap: inject a minimal pg8000 stub so db_config.py can be imported
# without the real package.
# ---------------------------------------------------------------------------

def _make_pg8000_stub():
    pg8000_mod = types.ModuleType("pg8000")
    pg8000_native = types.ModuleType("pg8000.native")

    class _Conn:
        def __init__(self, **kwargs):
            self.columns: list[dict] = []
            self._rows: list = []

        def run(self, sql, **params):
            return self._rows

        def close(self):
            pass

    pg8000_native.Connection = _Conn
    pg8000_mod.native = pg8000_native
    sys.modules["pg8000"] = pg8000_mod
    sys.modules["pg8000.native"] = pg8000_native
    return _Conn


_FakeConn = _make_pg8000_stub()

# ---------------------------------------------------------------------------
# Add the toolkit source directory to sys.path.
# ---------------------------------------------------------------------------

import os
_TOOLKIT_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "toolkits", "gsa_graj_viz")
)
sys.path.insert(0, _TOOLKIT_DIR)

# ---------------------------------------------------------------------------
# Load db_config under a unique module name to avoid collision with the
# test_operational_tbl_tools.py stub that also occupies sys.modules["db_config"].
# ---------------------------------------------------------------------------
import importlib.util as _iutil

_DB_CONFIG_PATH = os.path.join(_TOOLKIT_DIR, "db_config.py")


def _load_viz_db_config():
    spec = _iutil.spec_from_file_location("gsa_graj_viz_db_config", _DB_CONFIG_PATH)
    mod = _iutil.module_from_spec(spec)
    sys.modules["gsa_graj_viz_db_config"] = mod
    # Also register under "db_config" so server.py's `from db_config import ...` finds it.
    sys.modules["db_config"] = mod
    spec.loader.exec_module(mod)
    return mod


db_config = _load_viz_db_config()


# ---------------------------------------------------------------------------
# Reload helper: re-execute the file into the existing module object so that
# module-level constants (VIZ_ROW_LIMIT, ALLOWED_SCHEMAS) are recomputed from
# the current os.environ.  Using spec.loader.exec_module avoids the
# sys.modules["db_config"] collision caused by the operational-tools test stub.
# ---------------------------------------------------------------------------

def _reload_viz_db_config():
    spec = _iutil.spec_from_file_location("gsa_graj_viz_db_config", _DB_CONFIG_PATH)
    spec.loader.exec_module(db_config)


# ===========================================================================
# 1. SQL safety guard (_assert_safe_sql)
# ===========================================================================

class TestAssertSafeSql(unittest.TestCase):
    """_assert_safe_sql must accept SELECT/WITH/EXPLAIN and reject everything else."""

    def _ok(self, sql):
        db_config._assert_safe_sql(sql)  # must not raise

    def _bad(self, sql):
        with self.assertRaises(ValueError, msg=f"Expected ValueError for: {sql!r}"):
            db_config._assert_safe_sql(sql)

    # ── Allowed statements ──────────────────────────────────────────────────

    def test_select_simple(self):
        self._ok("SELECT 1")

    def test_select_with_whitespace(self):
        self._ok("  \n  SELECT * FROM operational_tbl LIMIT 10")

    def test_with_cte(self):
        self._ok("WITH cte AS (SELECT 1) SELECT * FROM cte")

    def test_explain(self):
        self._ok("EXPLAIN SELECT COUNT(*) FROM operational_tbl")

    def test_select_case_insensitive(self):
        self._ok("select city, count(*) from operational_tbl group by city")

    def test_select_subquery(self):
        self._ok(
            "SELECT * FROM (SELECT city, COUNT(*) AS n "
            "FROM operational_tbl GROUP BY city) sub ORDER BY n DESC"
        )

    # ── Blocked statements ──────────────────────────────────────────────────

    def test_insert(self):
        self._bad("INSERT INTO t VALUES (1)")

    def test_update(self):
        self._bad("UPDATE t SET col = 1 WHERE id = 2")

    def test_delete(self):
        self._bad("DELETE FROM t WHERE id = 1")

    def test_drop(self):
        self._bad("DROP TABLE operational_tbl")

    def test_truncate(self):
        self._bad("TRUNCATE TABLE operational_tbl")

    def test_create(self):
        self._bad("CREATE TABLE evil (id INT)")

    def test_alter(self):
        self._bad("ALTER TABLE operational_tbl ADD COLUMN x INT")

    def test_grant(self):
        self._bad("GRANT ALL ON operational_tbl TO attacker")

    def test_copy(self):
        self._bad("COPY operational_tbl TO '/tmp/out.csv'")

    # ── Semicolon injection ─────────────────────────────────────────────────

    def test_semicolon_injection_delete(self):
        self._bad("SELECT 1; DELETE FROM operational_tbl")

    def test_semicolon_injection_drop(self):
        self._bad("SELECT city FROM operational_tbl; DROP TABLE operational_tbl")

    def test_trailing_semicolon_ok(self):
        # A single trailing semicolon on its own should still be recognised as SELECT.
        self._ok("SELECT 1;")

    def test_double_semicolon_blocked(self):
        self._bad("SELECT 1;; SELECT 2")


# ===========================================================================
# 2. VIZ_ROW_LIMIT environment variable
# ===========================================================================

class TestVizRowLimit(unittest.TestCase):
    def setUp(self):
        os.environ.pop("VIZ_ROW_LIMIT", None)
        _reload_viz_db_config()

    def test_default_row_limit(self):
        # VIZ_ROW_LIMIT not set → default 2000
        self.assertEqual(db_config.VIZ_ROW_LIMIT, 2000)

    def test_custom_row_limit(self):
        os.environ["VIZ_ROW_LIMIT"] = "500"
        _reload_viz_db_config()
        self.assertEqual(db_config.VIZ_ROW_LIMIT, 500)

    def tearDown(self):
        os.environ.pop("VIZ_ROW_LIMIT", None)
        _reload_viz_db_config()


# ===========================================================================
# 3. ALLOWED_SCHEMAS environment variable
# ===========================================================================

class TestAllowedSchemas(unittest.TestCase):
    def setUp(self):
        os.environ.pop("VIZ_ALLOWED_SCHEMAS", None)
        _reload_viz_db_config()

    def test_default_public(self):
        self.assertIn("public", db_config.ALLOWED_SCHEMAS)

    def test_multiple_schemas(self):
        os.environ["VIZ_ALLOWED_SCHEMAS"] = "public,analytics,reporting"
        _reload_viz_db_config()
        self.assertSetEqual(
            db_config.ALLOWED_SCHEMAS,
            frozenset({"public", "analytics", "reporting"}),
        )

    def tearDown(self):
        os.environ.pop("VIZ_ALLOWED_SCHEMAS", None)
        _reload_viz_db_config()


# ===========================================================================
# 4. Chart HTML generation helpers (no DB needed)
# ===========================================================================

# Import the server module with dotenv and fastmcp stubbed out.

class _FakeFastMCP:
    def __init__(self, *a, **kw): pass
    def tool(self, *a, **kw):
        def _deco(fn): return fn
        return _deco
    def run(self): pass
    def http_app(self): return MagicMock()


def _load_server_module():
    stubs = {
        "fastmcp": types.ModuleType("fastmcp"),
        "dotenv": types.ModuleType("dotenv"),
        "httpx": types.ModuleType("httpx"),
    }
    stubs["fastmcp"].FastMCP = _FakeFastMCP
    stubs["dotenv"].load_dotenv = lambda: None

    # Prevent uvicorn.run from actually starting a server.
    uvicorn_stub = types.ModuleType("uvicorn")
    uvicorn_stub.run = lambda *a, **kw: None
    stubs["uvicorn"] = uvicorn_stub

    # Pydantic Field stub.
    pydantic_stub = types.ModuleType("pydantic")
    pydantic_stub.Field = lambda *a, **kw: None
    stubs["pydantic"] = pydantic_stub

    with patch.dict(sys.modules, stubs):
        # Clear any cached version of the module.
        sys.modules.pop("server", None)
        spec = importlib.util.spec_from_file_location(
            "server",
            os.path.join(_TOOLKIT_DIR, "server.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


import importlib.util  # noqa: E402

try:
    _server = _load_server_module()
    _SERVER_AVAILABLE = True
except Exception as e:
    _SERVER_AVAILABLE = False
    _SERVER_IMPORT_ERROR = str(e)


@unittest.skipUnless(_SERVER_AVAILABLE, f"server.py import skipped")
class TestChartHelpers(unittest.TestCase):
    """Test the pure-Python chart-building helpers inside server.py."""

    def setUp(self):
        self.rows = [
            {"city": "Toronto",  "n": 120},
            {"city": "Calgary",  "n": 95},
            {"city": "Vancouver","n": 80},
        ]
        self.columns = ["city", "n"]

    # ── _make_bar_line_option ───────────────────────────────────────────────

    def test_bar_option_has_xaxis(self):
        opt = _server._make_bar_line_option(self.rows, "city", "n", "bar", "Test")
        self.assertIn("xAxis", opt)
        self.assertEqual(opt["xAxis"]["data"], ["Toronto", "Calgary", "Vancouver"])

    def test_line_option_series_type(self):
        opt = _server._make_bar_line_option(self.rows, "city", "n", "line", "Test")
        self.assertEqual(opt["series"][0]["type"], "line")

    def test_bar_option_series_type(self):
        opt = _server._make_bar_line_option(self.rows, "city", "n", "bar", "Test")
        self.assertEqual(opt["series"][0]["type"], "bar")

    def test_bar_y_values(self):
        opt = _server._make_bar_line_option(self.rows, "city", "n", "bar", "Test")
        self.assertEqual(opt["series"][0]["data"], [120, 95, 80])

    # ── _make_scatter_option ────────────────────────────────────────────────

    def test_scatter_option_data(self):
        rows = [{"age": 5, "cost": 1200}, {"age": 8, "cost": 900}]
        opt = _server._make_scatter_option(rows, "age", "cost", "Cost vs Age")
        self.assertEqual(opt["series"][0]["type"], "scatter")
        self.assertEqual(opt["series"][0]["data"], [[5, 1200], [8, 900]])

    # ── _make_histogram_option ──────────────────────────────────────────────

    def test_histogram_bin_count(self):
        rows = [{"v": float(i)} for i in range(100)]
        opt = _server._make_histogram_option(rows, "v", 10, "Histogram")
        self.assertEqual(len(opt["series"][0]["data"]), 10)

    def test_histogram_total_counts_match(self):
        rows = [{"v": float(i)} for i in range(100)]
        opt = _server._make_histogram_option(rows, "v", 5, "Histogram")
        total = sum(opt["series"][0]["data"])
        self.assertEqual(total, 100)

    def test_histogram_empty_rows(self):
        # All-null values → empty option dict.
        rows = [{"v": None}]
        opt = _server._make_histogram_option(rows, "v", 10, "Histogram")
        self.assertEqual(opt, {})

    # ── _make_heatmap_option ────────────────────────────────────────────────

    def test_heatmap_data_length(self):
        rows = [
            {"ward": "ICU",   "month": "Jan", "avg_los": 5.1},
            {"ward": "ICU",   "month": "Feb", "avg_los": 4.8},
            {"ward": "Peds",  "month": "Jan", "avg_los": 3.2},
        ]
        opt = _server._make_heatmap_option(rows, "ward", "month", "avg_los", "Heat")
        self.assertEqual(len(opt["series"][0]["data"]), 3)

    # ── _make_table_option ──────────────────────────────────────────────────

    def test_table_html_has_headers(self):
        html = _server._make_table_option(self.rows, self.columns, "My Table")
        self.assertIn("<th>city</th>", html)
        self.assertIn("<th>n</th>", html)

    def test_table_html_has_rows(self):
        html = _server._make_table_option(self.rows, self.columns, "My Table")
        self.assertIn("Toronto", html)
        self.assertIn("Calgary", html)

    # ── _build_html ─────────────────────────────────────────────────────────

    def test_build_html_contains_title(self):
        html = _server._build_html("{}", "My Chart", "SELECT 1", [])
        self.assertIn("My Chart", html)

    def test_build_html_contains_sql(self):
        html = _server._build_html("{}", "Title", "SELECT city FROM t", [])
        self.assertIn("SELECT city FROM t", html)

    def test_build_html_has_echarts_script(self):
        html = _server._build_html("{}", "Title", "SELECT 1", [])
        self.assertIn("echarts", html)

    def test_build_html_table_no_echarts(self):
        html = _server._build_html(
            "{}", "Title", "SELECT 1", [],
            is_table=True, table_html="<table></table>",
        )
        # Table mode does not need the ECharts CDN script tag.
        self.assertNotIn("echarts.init", html)
        self.assertIn("<table>", html)

    def test_build_html_warnings_shown(self):
        html = _server._build_html("{}", "Title", "SELECT 1", ["Rows were truncated."])
        self.assertIn("Rows were truncated.", html)


# ===========================================================================
# 5. gsa_graj_viz_run_query — result shaping (mocked connection)
# ===========================================================================
# NOTE: run_query now returns a rendered markdown string directly (not JSON).
# Tests assert on markdown content rather than parsed payloads.

@unittest.skipUnless(_SERVER_AVAILABLE, "server.py import skipped")
class TestRunQueryResultShaping(unittest.TestCase):
    """gsa_graj_viz_run_query returns rendered markdown; tests assert on content."""

    def _fake_conn(self, rows, columns):
        conn = _FakeConn()
        conn._rows = rows
        conn.columns = [{"name": c} for c in columns]
        return conn

    def test_run_query_returns_rows(self):
        """Result must include a markdown table with the data rows."""
        import asyncio
        fake = self._fake_conn(
            [("Toronto", 120), ("Calgary", 95)],
            ["city", "n"],
        )
        with patch.object(_server, "get_ro_conn", return_value=fake):
            result = asyncio.get_event_loop().run_until_complete(
                _server.gsa_graj_viz_run_query(
                    "SELECT city, COUNT(*) AS n FROM operational_tbl GROUP BY city",
                    "City counts",
                )
            )
        self.assertIsInstance(result, str)
        # Markdown table headers present.
        self.assertIn("| city", result)
        self.assertIn("| n", result)
        # Both data rows present.
        self.assertIn("Toronto", result)
        self.assertIn("Calgary", result)
        # Row count footer present.
        self.assertIn("2 rows returned", result)
        # SQL block present.
        self.assertIn("SQL used", result)

    def test_run_query_rejects_insert(self):
        """Non-SELECT queries must return an error prefix (not JSON)."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            _server.gsa_graj_viz_run_query("INSERT INTO t VALUES (1)", None)
        )
        self.assertIsInstance(result, str)
        self.assertIn("❌", result)
        # Must contain the rejected SQL for transparency.
        self.assertIn("INSERT", result)

    def test_run_query_rejects_semicolon_injection(self):
        """Semicolon-injected SQL must be rejected with an error prefix."""
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            _server.gsa_graj_viz_run_query(
                "SELECT 1; DROP TABLE operational_tbl", None
            )
        )
        self.assertIsInstance(result, str)
        self.assertIn("❌", result)

    def test_run_query_adds_limit_if_missing(self):
        """The tool must inject LIMIT {VIZ_ROW_LIMIT} when the SQL lacks one."""
        import asyncio
        captured_sql = []
        fake = self._fake_conn([], ["x"])

        def capturing_run(sql, **kw):
            captured_sql.append(sql)
            return []

        fake.run = capturing_run
        with patch.object(_server, "get_ro_conn", return_value=fake):
            asyncio.get_event_loop().run_until_complete(
                _server.gsa_graj_viz_run_query("SELECT 1", None)
            )
        self.assertTrue(
            any("LIMIT" in s.upper() for s in captured_sql),
            f"Expected LIMIT in executed SQL, got: {captured_sql}",
        )

    def test_run_query_truncation_flag(self):
        """When exactly VIZ_ROW_LIMIT rows come back, a truncation warning appears."""
        import asyncio
        limit = db_config.VIZ_ROW_LIMIT
        fake_rows = [("x",)] * limit
        fake = self._fake_conn(fake_rows, ["x"])
        with patch.object(_server, "get_ro_conn", return_value=fake):
            result = asyncio.get_event_loop().run_until_complete(
                _server.gsa_graj_viz_run_query(
                    f"SELECT 'x' FROM t LIMIT {limit}", None
                )
            )
        self.assertIsInstance(result, str)
        self.assertIn("truncated", result.lower())

    def test_run_query_null_warning(self):
        """Columns with null values must generate a visible warning in the output."""
        import asyncio
        fake = self._fake_conn([(None, 5), ("Toronto", None)], ["city", "n"])
        with patch.object(_server, "get_ro_conn", return_value=fake):
            result = asyncio.get_event_loop().run_until_complete(
                _server.gsa_graj_viz_run_query("SELECT city, n FROM t", None)
            )
        self.assertIsInstance(result, str)
        self.assertIn("null", result.lower())


# ===========================================================================
# 6. gsa_graj_viz_build_chart — chart type selection and error handling
# ===========================================================================

@unittest.skipUnless(_SERVER_AVAILABLE, "server.py import skipped")
class TestBuildChart(unittest.TestCase):

    def _make_qr(self, rows, columns, sql="SELECT 1"):
        return json.dumps({
            "sql": sql,
            "columns": columns,
            "rows": rows,
            "warnings": [],
        })

    def _run(self, **kwargs):
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            _server.gsa_graj_viz_build_chart(**kwargs)
        )

    # ── Happy paths — build_chart now returns markdown ───────────────────────

    def test_bar_chart_markdown_returned(self):
        qr = self._make_qr(
            [{"city": "Toronto", "n": 10}], ["city", "n"]
        )
        result = self._run(query_result_json=qr, chart_type="bar")
        self.assertIsInstance(result, str)
        # Markdown table header and SQL block present.
        self.assertIn("| city", result)
        self.assertIn("SQL used", result)

    def test_line_chart_includes_text_barchart(self):
        qr = self._make_qr([{"month": "Jan", "n": 10}, {"month": "Feb", "n": 5}], ["month", "n"])
        result = self._run(query_result_json=qr, chart_type="line")
        # Text bar chart uses block chars.
        self.assertIn("█", result)

    def test_table_chart_no_echarts(self):
        qr = self._make_qr(
            [{"city": "Toronto", "n": 10}], ["city", "n"]
        )
        result = self._run(query_result_json=qr, chart_type="table")
        self.assertNotIn("echarts.init", result)
        self.assertIn("| city", result)

    def test_scatter_chart_returns_markdown(self):
        rows = [{"age": 5, "cost": 1200}, {"age": 8, "cost": 900}]
        qr = self._make_qr(rows, ["age", "cost"])
        result = self._run(query_result_json=qr, chart_type="scatter",
                           x_column="age", y_column="cost")
        self.assertIn("| age", result)

    def test_histogram_chart_returns_markdown(self):
        rows = [{"v": float(i)} for i in range(50)]
        qr = self._make_qr(rows, ["v"])
        result = self._run(query_result_json=qr, chart_type="histogram", x_column="v")
        self.assertIn("| v", result)

    def test_custom_title_propagated(self):
        qr = self._make_qr([{"city": "X", "n": 1}], ["city", "n"])
        result = self._run(query_result_json=qr, chart_title="My Custom Title")
        self.assertIn("My Custom Title", result)
        self.assertIn("| city", result)

    # ── Error paths — errors still returned as JSON strings ─────────────────

    def test_invalid_chart_type(self):
        qr = self._make_qr([{"x": 1}], ["x"])
        result = json.loads(self._run(query_result_json=qr, chart_type="pie"))
        self.assertIn("error", result)

    def test_missing_x_column(self):
        qr = self._make_qr([{"city": "X", "n": 1}], ["city", "n"])
        result = json.loads(
            self._run(query_result_json=qr, chart_type="bar", x_column="nonexistent")
        )
        self.assertIn("error", result)

    def test_empty_rows_error(self):
        qr = self._make_qr([], ["city", "n"])
        result = json.loads(self._run(query_result_json=qr))
        self.assertIn("error", result)

    def test_invalid_json_input(self):
        result = json.loads(self._run(query_result_json="NOT_JSON"))
        self.assertIn("error", result)


# ===========================================================================
# 7. gsa_graj_viz_export_csv
# ===========================================================================

@unittest.skipUnless(_SERVER_AVAILABLE, "server.py import skipped")
class TestExportCsv(unittest.TestCase):

    def _run(self, payload_dict):
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            _server.gsa_graj_viz_export_csv(json.dumps(payload_dict))
        )

    # export_csv now returns plain text (markdown code block) directly.

    def test_csv_has_header_row(self):
        result = self._run({
            "columns": ["city", "n"],
            "rows": [{"city": "Toronto", "n": 10}],
        })
        self.assertIn("city,n", result)

    def test_csv_row_count(self):
        result = self._run({
            "columns": ["city", "n"],
            "rows": [{"city": "Toronto", "n": 10}, {"city": "Calgary", "n": 5}],
        })
        self.assertIn("2 rows", result)

    def test_csv_values_present(self):
        result = self._run({
            "columns": ["city", "n"],
            "rows": [{"city": "Vancouver", "n": 7}],
        })
        self.assertIn("Vancouver", result)

    def test_no_columns_returns_error(self):
        result = json.loads(self._run({"columns": [], "rows": []}))
        self.assertIn("error", result)

    def test_invalid_json_input(self):
        import asyncio
        result = json.loads(
            asyncio.get_event_loop().run_until_complete(
                _server.gsa_graj_viz_export_csv("BADJSON")
            )
        )
        self.assertIn("error", result)


# ===========================================================================
# 8. gsa_graj_viz_preview_query — validation logic (mocked connection)
# ===========================================================================

@unittest.skipUnless(_SERVER_AVAILABLE, "server.py import skipped")
class TestPreviewQuery(unittest.TestCase):

    def _fake_conn_explain(self, plan_lines):
        conn = _FakeConn()
        conn._rows = [(line,) for line in plan_lines]
        return conn

    def _run(self, sql):
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            _server.gsa_graj_viz_preview_query(sql)
        )

    def test_valid_select_returns_valid_true(self):
        fake = self._fake_conn_explain(
            ["Seq Scan on operational_tbl  (cost=0.00..10.05 rows=5 width=8)"]
        )
        with patch.object(_server, "get_ro_conn", return_value=fake):
            result = json.loads(self._run("SELECT city, COUNT(*) FROM operational_tbl GROUP BY city"))
        self.assertTrue(result["valid"])

    def test_missing_limit_adds_warning(self):
        fake = self._fake_conn_explain(["Seq Scan on t  (cost=0.00..1.00 rows=1)"])
        with patch.object(_server, "get_ro_conn", return_value=fake):
            result = json.loads(self._run("SELECT * FROM operational_tbl"))
        self.assertTrue(result["valid"])
        self.assertTrue(len(result.get("warnings", [])) > 0)

    def test_insert_rejected_before_db(self):
        result = json.loads(self._run("INSERT INTO t VALUES (1)"))
        self.assertFalse(result["valid"])
        self.assertIn("error", result)

    def test_db_error_returns_valid_false(self):
        fake = _FakeConn()
        fake.run = MagicMock(side_effect=Exception("relation does not exist"))
        with patch.object(_server, "get_ro_conn", return_value=fake):
            result = json.loads(self._run("SELECT * FROM nonexistent_table"))
        self.assertFalse(result["valid"])
        self.assertIn("error", result)


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
