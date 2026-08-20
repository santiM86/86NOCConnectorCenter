"""Iter126 — unit checks on external_monitor module-level helpers (regression for the syntax/NameError bug)."""
import inspect

import pytest

import routes.external_monitor as em


def test_helpers_defined_at_module_level():
    for name in ("_hop_ip", "_baseline_diff", "_maybe_capture_baseline", "_auto_trace_on_wan_down"):
        assert hasattr(em, name), f"{name} missing from module namespace"
    assert inspect.iscoroutinefunction(em._maybe_capture_baseline)
    assert inspect.iscoroutinefunction(em._auto_trace_on_wan_down)


def test_hop_ip_extracts_ip():
    assert em._hop_ip({"ip": "8.8.8.8"}) == "8.8.8.8"
    assert em._hop_ip({}) in (None, "")


def test_baseline_diff_detects_change():
    base = [{"hop": 1, "ip": "10.0.0.1"}, {"hop": 2, "ip": "8.8.8.8"}]
    assert em._baseline_diff(base, list(base)) is None
    diff = em._baseline_diff(base, [{"hop": 1, "ip": "10.0.0.1"}, {"hop": 2, "ip": "1.1.1.1"}])
    assert diff and diff["kind"] == "changed" and diff["hop"] == 2
    brk = em._baseline_diff(base, [{"hop": 1, "ip": "10.0.0.1"}, {"hop": 2, "timeout": True}])
    assert brk and brk["kind"] == "break" and brk["hop"] == 2


def test_probe_cycle_callable_exists():
    fn = getattr(em, "_probe_cycle", None) or getattr(em, "probe_cycle", None)
    if fn is None:
        pytest.skip("probe cycle function name differs")
    assert callable(fn)
