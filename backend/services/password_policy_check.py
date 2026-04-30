"""
Password Strength + Have I Been Pwned (HIBP) check.

Usa l'API HIBP "Pwned Passwords" con k-anonymity: invia solo i primi 5 char
dello SHA-1 della password, riceve la lista degli hash che cominciano con
quel prefisso. Mai la password (o l'hash completo) lascia il client.

API: https://api.pwnedpasswords.com/range/<5-char-prefix>
Doc: https://haveibeenpwned.com/API/v3
Rate limit: nessuno per Pwned Passwords (gratis, illimitato).
"""
from __future__ import annotations

import hashlib
import logging
from typing import NamedTuple

import httpx

logger = logging.getLogger(__name__)

HIBP_API = "https://api.pwnedpasswords.com/range/"
HIBP_TIMEOUT = 5.0
HIBP_USER_AGENT = "ARGUS-NOC-Center-PasswordCheck/1.0"


class PasswordCheckResult(NamedTuple):
    ok: bool                   # True se accettabile
    score: int                 # 0..100
    issues: list[str]          # lista problemi trovati
    pwned_count: int = 0       # quante volte trovata in breach (0 = mai)


async def check_password_pwned(password: str) -> int:
    """Ritorna quante volte la password e` stata trovata in breach.

    0 = mai vista. Se HIBP irraggiungibile, ritorna 0 (fail-open per non
    bloccare login se HIBP e` down — la password policy locale fa comunque
    da rete di sicurezza).
    """
    if not password:
        return 0
    sha1 = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix, suffix = sha1[:5], sha1[5:]
    try:
        async with httpx.AsyncClient(timeout=HIBP_TIMEOUT) as c:
            r = await c.get(
                HIBP_API + prefix,
                headers={"User-Agent": HIBP_USER_AGENT, "Add-Padding": "true"},
            )
            if r.status_code != 200:
                logger.warning(f"[hibp] HTTP {r.status_code} fetching prefix {prefix}")
                return 0
            for line in r.text.splitlines():
                parts = line.strip().split(":")
                if len(parts) == 2 and parts[0].upper() == suffix:
                    try:
                        return int(parts[1])
                    except ValueError:
                        return 1
            return 0
    except Exception as e:
        logger.warning(f"[hibp] check failed: {e}")
        return 0


def validate_strength(password: str, min_length: int = 12) -> tuple[int, list[str]]:
    """Validazione policy locale. Ritorna (score 0..100, issues)."""
    issues: list[str] = []
    score = 0

    if not password:
        return 0, ["password vuota"]

    if len(password) < min_length:
        issues.append(f"lunghezza minima {min_length} caratteri (attuale: {len(password)})")
    else:
        score += min(40, (len(password) - min_length) * 3 + 30)

    has_lower = any(c.islower() for c in password)
    has_upper = any(c.isupper() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(not c.isalnum() for c in password)

    if not has_lower:
        issues.append("manca almeno una minuscola")
    else:
        score += 10
    if not has_upper:
        issues.append("manca almeno una maiuscola")
    else:
        score += 10
    if not has_digit:
        issues.append("manca almeno un numero")
    else:
        score += 10
    if not has_special:
        issues.append("manca almeno un simbolo (!@#$...)")
    else:
        score += 15

    # Pattern banali
    pwd_lower = password.lower()
    bad_patterns = ["password", "admin", "qwerty", "123456", "letmein",
                    "welcome", "iloveyou", "abc123", "argus", "noc"]
    for bp in bad_patterns:
        if bp in pwd_lower:
            issues.append(f"contiene pattern comune: '{bp}'")
            score = max(0, score - 25)
            break

    # Cap score
    score = max(0, min(100, score))
    return score, issues


async def check_password(password: str, min_length: int = 12) -> PasswordCheckResult:
    """Validazione completa: strength locale + HIBP.

    Una password viene rifiutata se:
      - score locale < 60, OPPURE
      - trovata in HIBP (qualsiasi count > 0)
    """
    score, issues = validate_strength(password, min_length=min_length)
    pwned_count = await check_password_pwned(password)
    if pwned_count > 0:
        issues.append(
            f"trovata in {pwned_count:,} breach pubblici (Have I Been Pwned) — "
            f"non utilizzabile"
        )
    ok = score >= 60 and pwned_count == 0 and not any(
        "lunghezza minima" in i for i in issues
    )
    return PasswordCheckResult(ok=ok, score=score, issues=issues, pwned_count=pwned_count)
