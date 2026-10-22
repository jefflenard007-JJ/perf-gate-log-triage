from datetime import datetime, timedelta

from logtriage import cli
from logtriage.analyze import analyse
from logtriage.parser import LogEvent, parse_line, signature


def test_parse_json_line():
    e = parse_line('{"ts":"2026-10-20T09:00:01+1100","level":"error","service":"api","msg":"boom"}')
    assert e.level == "ERROR" and e.service == "api" and e.is_error
    assert e.ts == datetime(2026, 10, 20, 9, 0, 1)


def test_parse_plain_line():
    e = parse_line("2026-10-20 09:15:02,123 ERROR [payments] Timeout calling bank after 3000 ms")
    assert e.service == "payments" and e.level == "ERROR"
    assert e.message == "Timeout calling bank after 3000 ms"


def test_unparseable_lines_are_skipped():
    assert parse_line("") is None
    assert parse_line("not a log line") is None
    assert parse_line("{broken json") is None


def test_signature_normalises_variable_parts():
    a = signature("Order 123 failed for 3f2a9c1e-5b7d-4e8a-9c21-7d4e5f6a8b90 from 10.0.0.5:443")
    b = signature("Order 987 failed for 11111111-2222-4333-8444-555555555555 from 192.168.1.9:80")
    assert a == b == "Order <n> failed for <uuid> from <ip>"


def _events(start, per_minute):
    events = []
    for minute, (n_errors, msg) in enumerate(per_minute):
        for i in range(n_errors):
            ts = start + timedelta(minutes=minute, seconds=i % 60)
            events.append(LogEvent(ts, "ERROR", "api", msg.format(i=i)))
        events.append(LogEvent(start + timedelta(minutes=minute), "INFO", "api", "ok"))
    return events


def test_detects_spike_and_names_new_signature():
    start = datetime(2026, 10, 20, 9, 0)
    pattern = [(1, "validation failed for item {i}")] * 20
    pattern += [(30, "DB timeout after {i} ms")] * 4
    pattern += [(1, "validation failed for item {i}")] * 5
    report = analyse(_events(start, pattern))
    assert len(report.spikes) == 1
    spike = report.spikes[0]
    assert spike.start == start + timedelta(minutes=20)
    assert spike.end == start + timedelta(minutes=24)  # whole incident, not just its first minutes
    assert spike.top_signatures[0][0] == "DB timeout after <n> ms"
    assert "DB timeout after <n> ms" in spike.new_signatures


def test_steady_errors_are_not_a_spike():
    start = datetime(2026, 10, 20, 9, 0)
    report = analyse(_events(start, [(3, "retrying {i}")] * 30))
    assert report.spikes == []
    assert report.total_errors == 90


def test_cli_fail_on_spike(tmp_path):
    start = datetime(2026, 10, 20, 9, 0)
    lines = []
    for e in _events(start, [(1, "minor {i}")] * 10 + [(40, "crash {i}")] * 2):
        lines.append(f"{e.ts:%Y-%m-%d %H:%M:%S} {e.level} [{e.service}] {e.message}")
    log = tmp_path / "app.log"
    log.write_text("\n".join(lines))
    report = tmp_path / "triage.md"
    assert cli.main([str(log), "--report", str(report)]) == 0
    assert cli.main([str(log), "--fail-on-spike"]) == 1
    assert "Likely cause" in report.read_text()
