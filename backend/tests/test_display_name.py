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
    """v2026-06-02: estrae la parte piu' informativa dalla categoria Fingerbank
    invece di mostrare la stringa tassonomica intera."""
    md = {"fingerbank_device_name": "Printer/HP LaserJet"}
    assert best_display_name(md, None, "10.0.0.11") == "HP LaserJet · 10.0.0.11"


def test_fingerbank_long_category_shortened():
    """'Switch and Wireless Controller/HP Switches' -> 'HP Switches · IP'."""
    md = {"fingerbank_device_name": "Switch and Wireless Controller/HP Switches"}
    assert best_display_name(md, None, "10.10.41.221") == "HP Switches · 10.10.41.221"


def test_fingerbank_hardware_manufacturer_shortened():
    """'Hardware Manufacturer/Hewlett Packard' -> 'Hewlett Packard · IP'."""
    md = {"fingerbank_device_name": "Hardware Manufacturer/Hewlett Packard"}
    assert best_display_name(md, None, "10.10.41.222") == "Hewlett Packard · 10.10.41.222"


def test_fingerbank_no_slash_kept_as_is():
    """Se la fingerbank non contiene '/', viene mostrata identica."""
    md = {"fingerbank_device_name": "Apple iPad"}
    assert best_display_name(md, None, "10.0.0.50") == "Apple iPad"


def test_pd_only():
    pd = {"sys_name": "core-router-01"}
    assert best_display_name(None, pd, "10.0.0.1") == "core-router-01"


def test_vendor_ip_beats_fingerbank_category():
    """v2026-02-14: vendor+IP e' piu' leggibile di una categoria Fingerbank."""
    md = {
        "name": "Switch and Wireless Controller/HP Switches",
        "fingerbank_device_name": "Switch and Wireless Controller/HP Switches",
        "vendor": "HPE",
    }
    assert best_display_name(md, None, "10.100.61.220") == "HPE 10.100.61.220"


def test_vendor_slash_takes_first_part():
    """Se vendor e' 'HPE/H3C', prende solo 'HPE' per pulizia."""
    md = {
        "name": "Switch and Wireless Controller/HP Switches",
        "fingerbank_device_name": "Switch and Wireless Controller/HP Switches",
        "vendor": "HPE/H3C",
    }
    assert best_display_name(md, None, "10.100.61.221") == "HPE 10.100.61.221"


def test_sys_name_still_beats_vendor_ip():
    """sys_name SNMP fresco e' SEMPRE preferito a vendor+IP."""
    md = {"vendor": "HPE", "name": "auto-named"}
    pd = {"sys_name": "Switch02 HP 5130 52G"}
    assert best_display_name(md, pd, "10.100.61.221") == "Switch02 HP 5130 52G"
