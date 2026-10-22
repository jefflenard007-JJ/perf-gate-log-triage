import json

import pytest

from perfgate import cli, history
from perfgate.gate import GateConfig, evaluate
from perfgate.results import EndpointStats, percentile, read_jtl, read_k6_summary


def write_jtl(path, rows):
    lines = ["timeStamp,elapsed,label,responseCode,success"]
    lines += [f"{ts},{el},{label},{200 if ok else 500},{'true' if ok else 'false'}" for ts, el, label, ok in rows]
    path.write_text("\n".join(lines) + "\n")


def stats(label="ALL", p95=100.0, err=0.0, tput=50.0, samples=100):
    return EndpointStats(label, samples, err, p95 / 2, p95, p95 * 1.2, tput)


def test_percentile_nearest_rank():
    values = list(range(1, 101))
    assert percentile(values, 50) == 50
    assert percentile(values, 95) == 95
    assert percentile([], 95) == 0.0


def test_read_jtl_per_label_and_all(tmp_path):
    jtl = tmp_path / "r.jtl"
    rows = [(1000 + i * 100, 10 + i, "GET /a", i != 3) for i in range(10)]
    rows += [(1000 + i * 100, 50, "GET /b", True) for i in range(10)]
    write_jtl(jtl, rows)
    result = read_jtl(jtl)
    assert set(result) == {"GET /a", "GET /b", "ALL"}
    assert result["GET /a"].samples == 10
    assert result["GET /a"].error_rate == 0.1
    assert result["ALL"].samples == 20


def test_read_jtl_rejects_missing_columns(tmp_path):
    bad = tmp_path / "bad.jtl"
    bad.write_text("foo,bar\n1,2\n")
    with pytest.raises(ValueError, match="missing columns"):
        read_jtl(bad)


def test_read_k6_summary(tmp_path):
    summary = {
        "metrics": {
            "http_req_duration": {"p(50)": 20, "p(95)": 120.5, "p(99)": 200},
            "http_reqs": {"count": 1000, "rate": 33.3},
            "http_req_failed": {"value": 0.004},
        }
    }
    path = tmp_path / "summary.json"
    path.write_text(json.dumps(summary))
    s = read_k6_summary(path)["ALL"]
    assert s.p95_ms == 120.5 and s.samples == 1000 and s.error_rate == 0.004


def test_gate_passes_within_tolerance():
    baseline = {"ALL": stats(p95=100).to_dict()}
    result = evaluate({"ALL": stats(p95=110)}, baseline, GateConfig())
    assert result.passed


def test_gate_fails_on_relative_p95_regression_even_under_absolute_limit():
    baseline = {"ALL": stats(p95=100).to_dict()}
    result = evaluate({"ALL": stats(p95=150)}, baseline, GateConfig())
    assert not result.passed
    assert [f.check for f in result.failures] == ["p95 vs baseline"]


def test_gate_fails_on_absolute_limits_without_baseline():
    result = evaluate({"ALL": stats(p95=400, err=0.05)}, None, GateConfig())
    assert {f.check for f in result.failures} == {"p95 within limit", "error rate within limit"}


def test_gate_fails_on_throughput_drop():
    baseline = {"ALL": stats(tput=100).to_dict()}
    result = evaluate({"ALL": stats(tput=70)}, baseline, GateConfig())
    assert [f.check for f in result.failures] == ["throughput vs baseline"]


def test_low_sample_endpoints_are_skipped():
    result = evaluate({"GET /rare": stats("GET /rare", p95=900, samples=3)}, None, GateConfig())
    assert result.passed and not result.findings


def test_cli_exit_codes_and_history(tmp_path):
    base_jtl, cur_jtl = tmp_path / "base.jtl", tmp_path / "cur.jtl"
    write_jtl(base_jtl, [(1000 + i * 10, 50, "GET /a", True) for i in range(100)])
    write_jtl(cur_jtl, [(1000 + i * 10, 90, "GET /a", True) for i in range(100)])
    baseline, db = tmp_path / "baseline.json", tmp_path / "hist.db"

    assert cli.main(["update-baseline", str(base_jtl), "--baseline", str(baseline)]) == 0
    assert cli.main(["check", str(base_jtl), "--baseline", str(baseline), "--db", str(db)]) == 0
    assert cli.main(["check", str(cur_jtl), "--baseline", str(baseline), "--db", str(db)]) == 1
    assert cli.main(["check", str(tmp_path / "missing.jtl")]) == 2

    with history.connect(db) as conn:
        passed = [row[0] for row in conn.execute("SELECT passed FROM runs ORDER BY id")]
        assert passed == [1, 0]
        assert len(history.trend(conn, 10)) == 4  # 2 runs x (GET /a + ALL)
