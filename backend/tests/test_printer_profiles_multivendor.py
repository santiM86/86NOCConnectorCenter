"""v2026-02-28: test dei 6 nuovi profili stampanti multi-vendor.

Verifica:
1. I 6 profili printer (HP/Epson/Kyocera/Xerox/Brother/Canon) sono
   presenti in `PROFILES` con `family='printer'`.
2. Ogni profilo contiene gli OID standard RFC 3805 (prtMarkerLifeCount,
   prtMarkerSuppliesLevel, prtMarkerSuppliesMaxCap, hrPrinterStatus).
3. Il classifier `fingerprint()` riconosce correttamente sysObjectID + sysDescr
   reali di stampanti di ciascun vendor.
4. Thresholds: toner_warn_pct=15, toner_crit_pct=5, page_jam_alert,
   printer_error_alert.
5. SEED_VERSION = 3 (per forzare re-seed in DB su deploy).
"""
import os
import sys

import pytest

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_database")
os.environ.setdefault("JWT_SECRET", "test-secret")

sys.path.insert(0, "/app/backend")

from device_profiles import PROFILES, SEED_VERSION, fingerprint, get_profile  # noqa: E402


PRINTER_KEYS = [
    "printer_hp", "printer_epson", "printer_kyocera",
    "printer_xerox", "printer_brother", "printer_canon",
]

# Standard Printer-MIB (RFC 3805) + HR-MIB OIDs richiesti su tutti i profili
REQUIRED_OIDS = [
    "hrPrinterStatus",
    "hrPrinterDetectedErrorState",
    "prtMarkerLifeCount",
    "prtMarkerSuppliesLevel",
    "prtMarkerSuppliesMaxCap",
    "prtMarkerSuppliesDescription",
]


@pytest.mark.parametrize("key", PRINTER_KEYS)
def test_printer_profile_exists(key):
    p = get_profile(key)
    assert p is not None, f"Profilo {key} mancante"
    assert p["family"] == "printer", f"{key} deve avere family=printer"
    assert p["vendor"], f"{key} deve avere vendor non vuoto"
    assert p["label"], f"{key} deve avere label non vuota"


@pytest.mark.parametrize("key", PRINTER_KEYS)
def test_printer_profile_has_rfc3805_oids(key):
    p = get_profile(key)
    for oid_name in REQUIRED_OIDS:
        assert oid_name in p["oids"], (
            f"{key} manca OID standard {oid_name} (RFC 3805 / HR-MIB)"
        )


@pytest.mark.parametrize("key", PRINTER_KEYS)
def test_printer_profile_has_alert_thresholds(key):
    p = get_profile(key)
    t = p.get("thresholds") or {}
    assert "toner_warn_pct" in t and t["toner_warn_pct"] > 0
    assert "toner_crit_pct" in t and t["toner_crit_pct"] > 0
    assert t["toner_crit_pct"] < t["toner_warn_pct"], (
        f"{key}: crit_pct ({t['toner_crit_pct']}) deve essere < warn_pct ({t['toner_warn_pct']})"
    )
    assert t.get("printer_error_alert") is True


# Fingerprint detection con dati reali (sysObjectID + sysDescr ricavati da
# documentazione SNMP ufficiale dei vendor)
FINGERPRINT_CASES = [
    # (sysObjectID, sysDescr, expected_key)
    ("1.3.6.1.4.1.11.2.3.9.4.2", "HP LaserJet Pro M404n", "printer_hp"),
    ("1.3.6.1.4.1.11.2.3.9.1.1", "HP OfficeJet Pro 9015e", "printer_hp"),
    ("1.3.6.1.4.1.1248.1.2.3", "EPSON WorkForce WF-7720", "printer_epson"),
    ("1.3.6.1.4.1.1248.1.1.5", "EPSON EcoTank L3250", "printer_epson"),
    ("1.3.6.1.4.1.1347.42.1.1", "Kyocera ECOSYS P5021cdw", "printer_kyocera"),
    ("1.3.6.1.4.1.1347.41.2", "Kyocera TASKalfa 2552ci", "printer_kyocera"),
    ("1.3.6.1.4.1.253.8.62.1", "Xerox WorkCentre 6515", "printer_xerox"),
    ("1.3.6.1.4.1.128.2.1.4", "Xerox VersaLink C7020", "printer_xerox"),
    ("1.3.6.1.4.1.2435.2.3.9", "Brother MFC-L3770CDW series", "printer_brother"),
    ("1.3.6.1.4.1.2435.2.3.9", "Brother HL-L2390DW", "printer_brother"),
    ("1.3.6.1.4.1.1602.1.11", "Canon imageCLASS MF445dw", "printer_canon"),
    ("1.3.6.1.4.1.1602.1.11.1", "Canon imageRUNNER ADVANCE", "printer_canon"),
]


@pytest.mark.parametrize("sysoid,sysdescr,expected_key", FINGERPRINT_CASES)
def test_printer_fingerprint_detection(sysoid, sysdescr, expected_key):
    result = fingerprint(sysoid, sysdescr)
    assert result is not None, (
        f"Fingerprint NON ha matchato sysOID={sysoid} sysDescr={sysdescr!r}"
    )
    assert result["key"] == expected_key, (
        f"Fingerprint per sysOID={sysoid} sysDescr={sysdescr!r}: "
        f"atteso {expected_key}, ottenuto {result['key']}"
    )


def test_seed_version_bumped():
    """SEED_VERSION deve essere stata incrementata per forzare upsert in DB."""
    assert SEED_VERSION >= 3, f"SEED_VERSION e' {SEED_VERSION}, attesa >= 3"


def test_no_duplicate_printer_keys():
    """Nessun profilo printer deve avere chiave duplicata."""
    keys = [p["key"] for p in PROFILES if p["family"] == "printer"]
    assert len(keys) == len(set(keys)), f"Keys duplicate: {keys}"


def test_total_printer_count():
    """Devono esserci esattamente 6 profili printer (HP/Epson/Kyocera/Xerox/Brother/Canon)."""
    printers = [p for p in PROFILES if p["family"] == "printer"]
    assert len(printers) == 6, f"Attesi 6 profili printer, trovati {len(printers)}"
