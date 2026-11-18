"""
tests/test_operational_tbl_tools.py
=====================================
Offline unit tests for:
  • toolkits/gsa_graj_tools/server.py  — gsa_graj_query_operational_tbl and
                                         its helper functions
  • tools/gsa_graj_aggregate_operational_tbl.py — extended standalone tool

All pg8000 calls are mocked — no live database required.

Run with:
    python tests/test_operational_tbl_tools.py
or:
    python -m pytest tests/test_operational_tbl_tools.py -v
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# ── pg8000 stub (must be first) ────────────────────────────────────────────────

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
    sys.modules.setdefault("pg8000", pg8000_mod)
    sys.modules.setdefault("pg8000.native", pg8000_native)
    return _Conn


_FakeConn = _make_pg8000_stub()

# ── Path setup ────────────────────────────────────────────────────────────────

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_TOOLKIT_DIR = os.path.join(_REPO, "toolkits", "gsa_graj_tools")
_TOOLS_DIR   = os.path.join(_REPO, "tools")

for _p in (_TOOLKIT_DIR, _TOOLS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ── Load server.py from the toolkit ───────────────────────────────────────────

class _FakeFastMCP:
    def __init__(self, *a, **kw): pass
    def tool(self, *a, **kw):
        def _deco(fn): return fn
        return _deco
    def run(self, *a, **kw): pass
    def http_app(self): return MagicMock()


def _load_server():
    stubs = {
        "fastmcp":  types.ModuleType("fastmcp"),
        "dotenv":   types.ModuleType("dotenv"),
        "httpx":    types.ModuleType("httpx"),
        "pydantic": types.ModuleType("pydantic"),
        "uvicorn":  types.ModuleType("uvicorn"),
    }
    stubs["fastmcp"].FastMCP = _FakeFastMCP
    stubs["dotenv"].load_dotenv = lambda: None
    stubs["pydantic"].Field = lambda *a, **kw: None
    stubs["uvicorn"].run = lambda *a, **kw: None

    with patch.dict(sys.modules, stubs):
        sys.modules.pop("server", None)
        spec = importlib.util.spec_from_file_location(
            "server", os.path.join(_TOOLKIT_DIR, "server.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


try:
    _server = _load_server()
    _SERVER_OK = True
except Exception as _e:
    _SERVER_OK = False
    _SERVER_ERR = str(_e)


# ── Load the standalone tool ───────────────────────────────────────────────────

def _load_standalone_tool():
    stubs = {
        "ibm_watsonx_orchestrate":                              types.ModuleType("ibm_watsonx_orchestrate"),
        "ibm_watsonx_orchestrate.agent_builder":               types.ModuleType("ibm_watsonx_orchestrate.agent_builder"),
        "ibm_watsonx_orchestrate.agent_builder.tools":         types.ModuleType("ibm_watsonx_orchestrate.agent_builder.tools"),
    }
    stubs["ibm_watsonx_orchestrate.agent_builder.tools"].tool = lambda *a, **kw: (lambda fn: fn)

    # db_config in tools/ uses same env-var logic; stub get_conn only.
    tools_db_stub = types.ModuleType("db_config")
    tools_db_stub.get_conn = MagicMock()

    with patch.dict(sys.modules, {**stubs, "db_config": tools_db_stub}):
        sys.modules.pop("gsa_graj_aggregate_operational_tbl", None)
        spec = importlib.util.spec_from_file_location(
            "gsa_graj_aggregate_operational_tbl",
            os.path.join(_TOOLS_DIR, "gsa_graj_aggregate_operational_tbl.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


try:
    _standalone = _load_standalone_tool()
    _STANDALONE_OK = True
except Exception as _e:
    _STANDALONE_OK = False
    _STANDALONE_ERR = str(_e)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION A — Helper / allowlist tests (server module)
# ═══════════════════════════════════════════════════════════════════════════════

@unittest.skipUnless(_SERVER_OK, "server.py import failed")
class TestOtValidateColumn(unittest.TestCase):

    def test_valid_column_accepted(self):
        for col in ("city", "ward", "treatment_cost_usd", "patient_id"):
            self.assertEqual(_server._ot_validate_column(col), col)

    def test_unknown_column_raises(self):
        with self.assertRaises(ValueError):
            _server._ot_validate_column("secret_column")

    def test_star_injection_blocked(self):
        with self.assertRaises(ValueError):
            _server._ot_validate_column("*")

    def test_drop_injection_blocked(self):
        with self.assertRaises(ValueError):
            _server._ot_validate_column("drop table")

    def test_semicolon_injection_blocked(self):
        with self.assertRaises(ValueError):
            _server._ot_validate_column("city; DROP TABLE operational_tbl --")


@unittest.skipUnless(_SERVER_OK, "server.py import failed")
class TestOtBuildAggExpr(unittest.TestCase):

    def test_count_star(self):
        expr, label = _server._ot_build_agg_expr("COUNT", None)
        self.assertEqual(expr, "COUNT(*)")
        self.assertEqual(label, "COUNT(*)")

    def test_sum_numeric(self):
        expr, label = _server._ot_build_agg_expr("SUM", "treatment_cost_usd")
        self.assertIn("SUM", expr)
        self.assertIn("treatment_cost_usd", expr)

    def test_avg_numeric(self):
        expr, _ = _server._ot_build_agg_expr("AVG", "age_at_admission")
        self.assertIn("AVG", expr)

    def test_count_distinct(self):
        expr, label = _server._ot_build_agg_expr("COUNT_DISTINCT", "patient_id")
        self.assertIn("COUNT(DISTINCT", expr)
        self.assertIn("patient_id", expr)

    def test_min_on_text_column_allowed(self):
        # MIN and MAX are allowed on any column (text or date)
        expr, _ = _server._ot_build_agg_expr("MIN", "city")
        self.assertIn("MIN", expr)

    def test_sum_on_text_column_blocked(self):
        with self.assertRaises(ValueError):
            _server._ot_build_agg_expr("SUM", "city")

    def test_avg_on_text_column_blocked(self):
        with self.assertRaises(ValueError):
            _server._ot_build_agg_expr("AVG", "discharge_status")

    def test_sum_requires_aggregate_column(self):
        with self.assertRaises(ValueError):
            _server._ot_build_agg_expr("SUM", None)

    def test_unknown_column_raises(self):
        with self.assertRaises(ValueError):
            _server._ot_build_agg_expr("SUM", "nonexistent")


@unittest.skipUnless(_SERVER_OK, "server.py import failed")
class TestOtDateGroupExpr(unittest.TestCase):

    def test_month_granularity(self):
        expr, alias = _server._ot_date_group_expr("date_admitted", "month")
        self.assertIn("YYYY-MM", expr)
        self.assertEqual(alias, "month_date_admitted")

    def test_quarter_granularity(self):
        expr, alias = _server._ot_date_group_expr("date_admitted", "quarter")
        self.assertIn("Q", expr)
        self.assertEqual(alias, "quarter_date_admitted")

    def test_year_granularity(self):
        expr, alias = _server._ot_date_group_expr("date_admitted", "year")
        self.assertIn("EXTRACT(YEAR", expr)
        self.assertEqual(alias, "year_date_admitted")

    def test_week_granularity(self):
        expr, alias = _server._ot_date_group_expr("date_admitted", "week")
        self.assertIn("DATE_TRUNC", expr)
        self.assertEqual(alias, "week_date_admitted")

    def test_day_granularity(self):
        expr, alias = _server._ot_date_group_expr("date_admitted", "day")
        self.assertIn("CAST", expr)
        self.assertEqual(alias, "day_date_admitted")

    def test_invalid_granularity(self):
        with self.assertRaises(ValueError):
            _server._ot_date_group_expr("date_admitted", "decade")

    def test_non_date_column_blocked(self):
        with self.assertRaises(ValueError):
            _server._ot_date_group_expr("city", "month")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION B — gsa_graj_query_operational_tbl integration tests
# ═══════════════════════════════════════════════════════════════════════════════

@unittest.skipUnless(_SERVER_OK, "server.py import failed")
class TestQueryOpTblSqlGeneration(unittest.TestCase):
    """Verify that the correct SQL fragments appear in the returned JSON."""

    def _run(self, **kwargs):
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            _server.gsa_graj_query_operational_tbl(**kwargs)
        )

    def _fake_conn(self, rows, columns):
        conn = _FakeConn()
        conn._rows = rows
        conn.columns = [{"name": c} for c in columns]
        return conn

    # ── COUNT(*) scalar ────────────────────────────────────────────────────────

    def test_count_all_records(self):
        fake = self._fake_conn([(605,)], ["result"])
        with patch.object(_server, "_get_conn", return_value=fake):
            out = json.loads(self._run(aggregate_function="COUNT"))
        self.assertEqual(out["result"], 605)
        self.assertIn("COUNT(*)", out["sql"])

    # ── COUNT_DISTINCT patient_id ──────────────────────────────────────────────

    def test_count_distinct_patients(self):
        fake = self._fake_conn([(500,)], ["result"])
        with patch.object(_server, "_get_conn", return_value=fake):
            out = json.loads(self._run(
                aggregate_function="COUNT_DISTINCT",
                aggregate_column="patient_id",
            ))
        self.assertIn("COUNT(DISTINCT", out["sql"])
        self.assertIn("patient_id", out["sql"])

    # ── Multi-column GROUP BY ──────────────────────────────────────────────────

    def test_group_by_gender_and_blood_group(self):
        fake = self._fake_conn(
            [("Male", "A+", 100), ("Female", "O-", 80)],
            ["gender", "blood_group", "result"],
        )
        with patch.object(_server, "_get_conn", return_value=fake):
            out = json.loads(self._run(
                aggregate_function="COUNT",
                group_by_columns="gender,blood_group",
            ))
        self.assertIn("GROUP BY", out["sql"])
        self.assertIn('"gender"', out["sql"])
        self.assertIn('"blood_group"', out["sql"])
        self.assertEqual(out["row_count"], 2)
        self.assertIn("gender", out["columns"])
        self.assertIn("blood_group", out["columns"])

    # ── HAVING clause ──────────────────────────────────────────────────────────

    def test_having_count_gt_100(self):
        fake = self._fake_conn([("ICU", 150)], ["ward", "result"])
        with patch.object(_server, "_get_conn", return_value=fake):
            out = json.loads(self._run(
                aggregate_function="COUNT",
                group_by_columns="ward",
                having_clause="COUNT(*) > 100",
            ))
        self.assertIn("HAVING", out["sql"])
        self.assertIn("COUNT(*) > 100", out["sql"])

    def test_having_without_group_by_is_error(self):
        out = json.loads(self._run(having_clause="COUNT(*) > 100"))
        self.assertIn("error", out)

    # ── Date granularity ──────────────────────────────────────────────────────

    def test_monthly_grouping(self):
        fake = self._fake_conn(
            [("2024-01", 55), ("2024-02", 42)],
            ["month_date_admitted", "result"],
        )
        with patch.object(_server, "_get_conn", return_value=fake):
            out = json.loads(self._run(
                aggregate_function="COUNT",
                group_by_columns="date_admitted",
                date_granularity="month",
            ))
        self.assertIn("YYYY-MM", out["sql"])
        self.assertIn("GROUP BY", out["sql"])

    def test_quarterly_grouping(self):
        fake = self._fake_conn([("2024-Q1", 120)], ["quarter_date_admitted", "result"])
        with patch.object(_server, "_get_conn", return_value=fake):
            out = json.loads(self._run(
                aggregate_function="SUM",
                aggregate_column="treatment_cost_usd",
                group_by_columns="date_admitted",
                date_granularity="quarter",
            ))
        self.assertIn("Q", out["sql"])

    # ── WHERE clause (data slice) ──────────────────────────────────────────────

    def test_data_slice_with_where(self):
        fake = self._fake_conn(
            [("P001", "Boston", 72)],
            ["patient_id", "city", "age_at_admission"],
        )
        with patch.object(_server, "_get_conn", return_value=fake):
            out = json.loads(self._run(
                select_columns="patient_id,city,age_at_admission",
                where_clause="age_at_admission > 60 AND city = 'Boston'",
            ))
        self.assertIn("age_at_admission > 60", out["sql"])
        self.assertIn("city = 'Boston'", out["sql"])
        self.assertEqual(out["columns"], ["patient_id", "city", "age_at_admission"])

    # ── NULL check filter ──────────────────────────────────────────────────────

    def test_null_discharge_date_filter(self):
        fake = self._fake_conn(
            [("P002", None, "Ward A")],
            ["patient_id", "discharge_date", "ward"],
        )
        with patch.object(_server, "_get_conn", return_value=fake):
            out = json.loads(self._run(
                select_columns="patient_id,discharge_date,ward",
                where_clause="discharge_date IS NULL",
            ))
        self.assertIn("IS NULL", out["sql"])
        # Null disclosure warning should be present.
        self.assertTrue(any("null" in w.lower() for w in out["warnings"]))

    # ── Top-N ranking ──────────────────────────────────────────────────────────

    def test_top_5_cities_by_cost(self):
        rows = [("Boston", 50000.0 - i * 1000.0) for i in range(5)]
        fake = self._fake_conn(rows, ["city", "result"])
        with patch.object(_server, "_get_conn", return_value=fake):
            out = json.loads(self._run(
                aggregate_function="SUM",
                aggregate_column="treatment_cost_usd",
                group_by_columns="city",
                order_by="result DESC",
                limit=5,
            ))
        self.assertIn("LIMIT 5", out["sql"])
        self.assertEqual(out["row_count"], 5)

    # ── Pagination (offset) ───────────────────────────────────────────────────

    def test_offset_added_to_sql(self):
        fake = self._fake_conn([("P010",)], ["patient_id"])
        with patch.object(_server, "_get_conn", return_value=fake):
            out = json.loads(self._run(
                select_columns="patient_id",
                limit=10,
                offset=50,
            ))
        self.assertIn("OFFSET 50", out["sql"])

    def test_offset_zero_not_added(self):
        fake = self._fake_conn([("P010",)], ["patient_id"])
        with patch.object(_server, "_get_conn", return_value=fake):
            out = json.loads(self._run(
                select_columns="patient_id",
                limit=10,
                offset=0,
            ))
        self.assertNotIn("OFFSET", out["sql"])

    # ── Error: unknown column ──────────────────────────────────────────────────

    def test_unknown_select_column(self):
        out = json.loads(self._run(select_columns="secret_field"))
        self.assertIn("error", out)
        self.assertIn("secret_field", out["error"])

    def test_unknown_group_by_column(self):
        out = json.loads(self._run(
            aggregate_function="COUNT",
            group_by_columns="nonexistent_col",
        ))
        self.assertIn("error", out)

    # ── Error: SUM on text column ──────────────────────────────────────────────

    def test_sum_on_city_blocked(self):
        out = json.loads(self._run(
            aggregate_function="SUM",
            aggregate_column="city",
        ))
        self.assertIn("error", out)
        self.assertIn("non-numeric", out["error"])

    def test_avg_on_discharge_status_blocked(self):
        out = json.loads(self._run(
            aggregate_function="AVG",
            aggregate_column="discharge_status",
        ))
        self.assertIn("error", out)

    # ── Error: mutual exclusion ───────────────────────────────────────────────

    def test_select_columns_and_aggregate_function_mutually_exclusive(self):
        out = json.loads(self._run(
            select_columns="city",
            aggregate_function="COUNT",
        ))
        self.assertIn("error", out)

    # ── Truncation warning ────────────────────────────────────────────────────

    def test_truncation_warning_on_full_limit(self):
        limit = 10
        fake = self._fake_conn([(f"P{i:03}",) for i in range(limit)], ["patient_id"])
        with patch.object(_server, "_get_conn", return_value=fake):
            out = json.loads(self._run(select_columns="patient_id", limit=limit))
        self.assertTrue(any("capped" in w.lower() for w in out["warnings"]))

    # ── SQL injection via column name ─────────────────────────────────────────

    def test_injection_via_select_columns(self):
        out = json.loads(self._run(select_columns="city; DROP TABLE operational_tbl"))
        self.assertIn("error", out)

    def test_injection_via_group_by(self):
        out = json.loads(self._run(
            aggregate_function="COUNT",
            group_by_columns="ward; DROP TABLE operational_tbl --",
        ))
        self.assertIn("error", out)

    def test_injection_via_aggregate_column(self):
        out = json.loads(self._run(
            aggregate_function="SUM",
            aggregate_column="treatment_cost_usd; DROP TABLE foo --",
        ))
        self.assertIn("error", out)

    # ── Database execution error returned safely ──────────────────────────────

    def test_db_error_returned_as_json(self):
        fake = _FakeConn()
        fake.run = MagicMock(side_effect=Exception("relation does not exist"))
        with patch.object(_server, "_get_conn", return_value=fake):
            out = json.loads(self._run(
                aggregate_function="COUNT",
            ))
        self.assertIn("error", out)
        self.assertIn("relation does not exist", out["error"])

    # ── Notes always present ──────────────────────────────────────────────────

    def test_count_note_mentions_nulls(self):
        fake = self._fake_conn([(100,)], ["result"])
        with patch.object(_server, "_get_conn", return_value=fake):
            out = json.loads(self._run(aggregate_function="COUNT"))
        self.assertTrue(any("null" in n.lower() or "NULL" in n for n in out.get("notes", [])))

    def test_count_distinct_note_present(self):
        fake = self._fake_conn([(50,)], ["result"])
        with patch.object(_server, "_get_conn", return_value=fake):
            out = json.loads(self._run(
                aggregate_function="COUNT_DISTINCT",
                aggregate_column="patient_id",
            ))
        self.assertTrue(any("distinct" in n.lower() for n in out.get("notes", [])))


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION C — Standalone tool backward compatibility
# ═══════════════════════════════════════════════════════════════════════════════

@unittest.skipUnless(_STANDALONE_OK, "standalone tool import failed")
class TestStandaloneToolBackwardCompat(unittest.TestCase):
    """gsa_graj_aggregate_operational_tbl — legacy (month+year only) must work."""

    def _fake_conn(self, table_exists=True, col_rows=None, count_result=None, agg_result=None):
        fake = _FakeConn()
        call_seq = iter([
            # 1. table existence check
            [(1,)] if table_exists else [],
            # 2. column names
            col_rows or [
                ("patient_id", "character varying"),
                ("age_at_admission", "integer"),
                ("length_of_stay_days", "integer"),
                ("treatment_cost_usd", "numeric"),
                ("date_admitted", "date"),
            ],
            # 3. row count
            count_result or [(10,)],
            # 4. aggregation per numeric col (age_at_admission)
            agg_result or [(None, None, None, None, 0)],
            # 5. aggregation per numeric col (length_of_stay_days)
            [(None, None, None, None, 0)],
            # 6. aggregation per numeric col (treatment_cost_usd)
            [(None, None, None, None, 0)],
        ])
        fake.run = lambda sql, **kw: next(call_seq, [])
        return fake

    def test_legacy_returns_period_key(self):
        fake = self._fake_conn()
        _standalone.get_conn = MagicMock(return_value=fake)
        result = _standalone.gsa_graj_aggregate_operational_tbl(month=1, year=2024)
        self.assertIn("January 2024", result)

    def test_legacy_returns_aggregations_key(self):
        fake = self._fake_conn(
            col_rows=[
                ("patient_id", "character varying"),
                ("age_at_admission", "integer"),
                ("date_admitted", "date"),
            ],
            count_result=[(5,)],
            agg_result=[(100.0, 20.0, 5.0, 40.0, 5)],
        )
        _standalone.get_conn = MagicMock(return_value=fake)
        result = _standalone.gsa_graj_aggregate_operational_tbl(month=3, year=2023)
        self.assertIn("aggregations", result)

    def test_legacy_no_rows_message(self):
        fake = self._fake_conn(count_result=[(0,)])
        _standalone.get_conn = MagicMock(return_value=fake)
        result = _standalone.gsa_graj_aggregate_operational_tbl(month=6, year=2020)
        self.assertIn("No rows found", result)

    def test_invalid_month_raises(self):
        with self.assertRaises(ValueError):
            _standalone.gsa_graj_aggregate_operational_tbl(month=13, year=2024)

    def test_invalid_year_raises(self):
        with self.assertRaises(ValueError):
            _standalone.gsa_graj_aggregate_operational_tbl(month=1, year=1800)

    def test_legacy_table_not_found(self):
        fake = self._fake_conn(table_exists=False)
        _standalone.get_conn = MagicMock(return_value=fake)
        with self.assertRaises(ValueError):
            _standalone.gsa_graj_aggregate_operational_tbl(month=1, year=2024)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION D — Standalone tool extended mode
# ═══════════════════════════════════════════════════════════════════════════════

@unittest.skipUnless(_STANDALONE_OK, "standalone tool import failed")
class TestStandaloneToolExtendedMode(unittest.TestCase):
    """Extended parameters on gsa_graj_aggregate_operational_tbl."""

    def _mock_conn(self, rows, columns):
        fake = _FakeConn()
        fake._rows = rows
        fake.columns = [{"name": c} for c in columns]
        fake.run = MagicMock(return_value=rows)
        return fake

    def test_aggregate_function_count(self):
        fake = self._mock_conn([(605,)], ["result"])
        _standalone.get_conn = MagicMock(return_value=fake)
        result = json.loads(
            _standalone.gsa_graj_aggregate_operational_tbl(
                month=1, year=2024, aggregate_function="COUNT"
            )
        )
        self.assertIn("result", result)
        self.assertEqual(result["result"], 605)

    def test_sum_treatment_cost_by_ward(self):
        rows = [("ICU", 95000.0), ("Peds", 70000.0)]
        fake = self._mock_conn(rows, ["ward", "result"])
        _standalone.get_conn = MagicMock(return_value=fake)
        result = json.loads(
            _standalone.gsa_graj_aggregate_operational_tbl(
                month=1, year=2024,
                aggregate_function="SUM",
                aggregate_column="treatment_cost_usd",
                group_by_columns="ward",
            )
        )
        self.assertIn("rows", result)
        self.assertEqual(result["row_count"], 2)

    def test_multi_column_group_by(self):
        rows = [("Male", "A+", 50), ("Female", "O-", 30)]
        fake = self._mock_conn(rows, ["gender", "blood_group", "result"])
        _standalone.get_conn = MagicMock(return_value=fake)
        result = json.loads(
            _standalone.gsa_graj_aggregate_operational_tbl(
                month=1, year=2024,
                aggregate_function="COUNT",
                group_by_columns="gender,blood_group",
            )
        )
        self.assertIn("GROUP BY", result["sql"])
        self.assertIn("gender", result["columns"])
        self.assertIn("blood_group", result["columns"])

    def test_having_clause_in_sql(self):
        fake = self._mock_conn([("ICU", 150)], ["ward", "result"])
        _standalone.get_conn = MagicMock(return_value=fake)
        result = json.loads(
            _standalone.gsa_graj_aggregate_operational_tbl(
                month=1, year=2024,
                aggregate_function="COUNT",
                group_by_columns="ward",
                having_clause="COUNT(*) > 100",
            )
        )
        self.assertIn("HAVING", result["sql"])

    def test_having_without_group_by_error(self):
        result = json.loads(
            _standalone.gsa_graj_aggregate_operational_tbl(
                month=1, year=2024,
                aggregate_function="COUNT",
                having_clause="COUNT(*) > 100",
            )
        )
        self.assertIn("error", result)

    def test_date_granularity_month(self):
        fake = self._mock_conn([("2024-01", 55)], ["month_date_admitted", "result"])
        _standalone.get_conn = MagicMock(return_value=fake)
        result = json.loads(
            _standalone.gsa_graj_aggregate_operational_tbl(
                month=1, year=2024,
                aggregate_function="COUNT",
                group_by_columns="date_admitted",
                date_granularity="month",
                where_clause="date_admitted >= '2024-01-01'",
            )
        )
        self.assertIn("YYYY-MM", result["sql"])

    def test_explicit_where_clause_overrides_month_year(self):
        fake = self._mock_conn([(300,)], ["result"])
        _standalone.get_conn = MagicMock(return_value=fake)
        result = json.loads(
            _standalone.gsa_graj_aggregate_operational_tbl(
                month=1, year=2024,
                aggregate_function="COUNT",
                where_clause="city = 'Boston'",
            )
        )
        # The custom where_clause should appear, month+year should NOT.
        self.assertIn("city = 'Boston'", result["sql"])
        self.assertNotIn("EXTRACT(MONTH", result["sql"])

    def test_sum_on_text_column_blocked(self):
        result = json.loads(
            _standalone.gsa_graj_aggregate_operational_tbl(
                month=1, year=2024,
                aggregate_function="SUM",
                aggregate_column="city",
            )
        )
        self.assertIn("error", result)
        self.assertIn("non-numeric", result["error"])

    def test_unknown_column_in_select_columns(self):
        result = json.loads(
            _standalone.gsa_graj_aggregate_operational_tbl(
                month=1, year=2024,
                select_columns="evil_column",
            )
        )
        self.assertIn("error", result)

    def test_select_and_aggregate_mutually_exclusive(self):
        result = json.loads(
            _standalone.gsa_graj_aggregate_operational_tbl(
                month=1, year=2024,
                select_columns="city",
                aggregate_function="COUNT",
            )
        )
        self.assertIn("error", result)

    def test_limit_capped_at_max_rows(self):
        # limit > _MAX_ROWS should be silently capped, not cause an error.
        fake = self._mock_conn([], ["patient_id"])
        _standalone.get_conn = MagicMock(return_value=fake)
        result = json.loads(
            _standalone.gsa_graj_aggregate_operational_tbl(
                month=1, year=2024,
                select_columns="patient_id",
                limit=9999,  # over _MAX_ROWS
            )
        )
        # Must contain LIMIT 500 (the cap), not LIMIT 9999.
        self.assertIn(f"LIMIT {_standalone._MAX_ROWS}", result["sql"])

    def test_offset_pagination(self):
        fake = self._mock_conn([("P011",)], ["patient_id"])
        _standalone.get_conn = MagicMock(return_value=fake)
        result = json.loads(
            _standalone.gsa_graj_aggregate_operational_tbl(
                month=1, year=2024,
                select_columns="patient_id",
                offset=100,
            )
        )
        self.assertIn("OFFSET 100", result["sql"])

    def test_injection_via_aggregate_column_blocked(self):
        result = json.loads(
            _standalone.gsa_graj_aggregate_operational_tbl(
                month=1, year=2024,
                aggregate_function="SUM",
                aggregate_column="treatment_cost_usd; DROP TABLE operational_tbl --",
            )
        )
        self.assertIn("error", result)

    def test_injection_via_group_by_column_blocked(self):
        result = json.loads(
            _standalone.gsa_graj_aggregate_operational_tbl(
                month=1, year=2024,
                aggregate_function="COUNT",
                group_by_columns="ward; DELETE FROM operational_tbl --",
            )
        )
        self.assertIn("error", result)

    def test_count_distinct_patients_by_city(self):
        rows = [("Boston", 42), ("NYC", 38)]
        fake = self._mock_conn(rows, ["city", "result"])
        _standalone.get_conn = MagicMock(return_value=fake)
        result = json.loads(
            _standalone.gsa_graj_aggregate_operational_tbl(
                month=1, year=2024,
                aggregate_function="COUNT_DISTINCT",
                aggregate_column="patient_id",
                group_by_columns="city",
            )
        )
        self.assertIn("COUNT(DISTINCT", result["sql"])

    def test_notes_includes_month_year_filter(self):
        fake = self._mock_conn([(100,)], ["result"])
        _standalone.get_conn = MagicMock(return_value=fake)
        result = json.loads(
            _standalone.gsa_graj_aggregate_operational_tbl(
                month=3, year=2024,
                aggregate_function="COUNT",
            )
        )
        self.assertTrue(
            any("march" in n.lower() or "2024" in n for n in result.get("notes", []))
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION E — Allowlist constants consistency check
# ═══════════════════════════════════════════════════════════════════════════════

@unittest.skipUnless(_SERVER_OK and _STANDALONE_OK, "one or both modules failed to load")
class TestAllowlistConsistency(unittest.TestCase):
    """Server and standalone tool must agree on the same column allowlists."""

    def test_allowed_columns_match(self):
        self.assertEqual(
            _server._OT_ALLOWED_COLUMNS,
            _standalone._ALLOWED_COLUMNS,
            "Column allowlists diverged between server.py and standalone tool.",
        )

    def test_numeric_columns_match(self):
        self.assertEqual(
            _server._OT_NUMERIC_COLUMNS,
            _standalone._NUMERIC_COLUMNS,
        )

    def test_date_columns_match(self):
        self.assertEqual(
            _server._OT_DATE_COLUMNS,
            _standalone._DATE_COLUMNS,
        )

    def test_allowed_aggregates_match(self):
        self.assertEqual(
            _server._OT_ALLOWED_AGGREGATES,
            _standalone._ALLOWED_AGGREGATES,
        )

    def test_expected_schema_columns_present(self):
        """Every column in the documented schema must be in the allowlist."""
        expected = {
            "patient_id", "name", "gender", "dob", "age_at_admission", "city",
            "blood_group", "date_admitted", "health_issue", "ward",
            "attending_doctor", "discharge_date", "length_of_stay_days",
            "discharge_status", "treatment_cost_usd",
        }
        self.assertEqual(expected, _server._OT_ALLOWED_COLUMNS)

    def test_numeric_columns_subset_of_allowed(self):
        self.assertTrue(
            _server._OT_NUMERIC_COLUMNS.issubset(_server._OT_ALLOWED_COLUMNS)
        )

    def test_date_columns_subset_of_allowed(self):
        self.assertTrue(
            _server._OT_DATE_COLUMNS.issubset(_server._OT_ALLOWED_COLUMNS)
        )


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
