"""Tests for the centralized display name helper."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from display_name import best_display_name, _looks_categorical


def test_sys_name_wins_over_fingerbank_category():
    md = {
        "name": "Switch and Wireless Controller/HP Switches",
        "hostname": "Switch02 HP 5130 52G",
        "fingerbank_device_name": "Switch and Wireless Controller/HP Switches",
    }
    pd = {"sys_name": "Switch02 HP 5130 52G", "device_name": "Switch02 HP 5130 52G"}
    assert best_display_name(md, pd, "10.100.61.221") == "Switch02 HP 5130 52G"


def test_hostname_wins_when_no_poll():
    md = {
        "name": "Operating System/Linux",
        "hostname": "nas-backup-01",
    }
    assert best_display_name(md, None, "10.0.0.5") == "nas-backup-01"


def test_locked_name_always_wins():
    md = {
        "name": "Switch SALA 5° PIANO",
        "name_locked": True,
        "hostname": "sw02",
    }
    pd = {"sys_name": "switch02-real-sysname"}
    assert best_display_name(md, pd, "10.0.0.1") == "Switch SALA 5° PIANO"


def test_falls_back_to_ip():
    assert best_display_name({}, {}, "10.0.0.99") == "10.0.0.99"


def test_skips_name_equal_to_ip():
    md = {"name": "10.0.0.7", "hostname": "10.0.0.7"}
    assert best_display_name(md, None, "10.0.0.7") == "10.0.0.7"


def test_user_name_wins_over_fingerbank():
    md = {
        "name": "Stampante Magazzino",
        "fingerbank_device_name": "Printer/HP LaserJet",
    }
    assert best_display_name(md, None, "10.0.0.8") == "Stampante Magazzino"


def test_categorical_detection():
    assert _looks_categorical("Switch and Wireless Controller/HP Switches") is True
    assert _looks_categorical("Operating System/Linux") is True
    assert _looks_categorical("switch02.local") is False
    assert _looks_categorical("nas-backup-01") is False
    assert _looks_categorical("My Switch") is False


def test_mdns_used_when_no_better():
    md = {"mdns_name": "office-printer.local"}
    assert best_display_name(md, None, "10.0.0.10") == "office-printer.local"


def test_fingerbank_fallback_when_only_category_available():
    md = {"fingerbank_device_name": "Printer/HP LaserJet"}
    assert best_display_name(md, None, "10.0.0.11") == "Printer/HP LaserJet"


def test_pd_only():
    pd = {"sys_name": "core-router-01"}
    assert best_display_name(None, pd, "10.0.0.1") == "core-router-01"
