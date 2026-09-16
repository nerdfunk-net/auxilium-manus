"""Random password generation policy for the ``generate-password`` workflow step.

Deliberately step-local (not under ``services/secret_manager/``, unlike
``secret-generate``'s ``SecretGenerationPolicy``): this module's isolation from
any secret-manager or DB import is what makes it self-contained — the step has
no external Secret Manager connection dependency at all.

Uses the stdlib ``secrets`` module exclusively (cryptographically secure),
never ``random``, for both character selection and the final shuffle.
"""

from __future__ import annotations

import secrets
import string
from dataclasses import dataclass

MIN_LENGTH = 8
MAX_LENGTH = 256

# Deliberately excludes characters that commonly break shell quoting,
# CSV/YAML embedding, or CLI config-line parsing on network devices (no
# backtick, no quote characters, no `;`/`|`). Fixed — not user-configurable.
SPECIAL_CHARACTERS = "!@#$%^&*()-_=+[]{}:,.?"

DIGITS = string.digits
UPPERCASE = string.ascii_uppercase
LOWERCASE = string.ascii_lowercase

_CATEGORIES: tuple[tuple[str, str], ...] = (
    ("min_digits", DIGITS),
    ("min_uppercase", UPPERCASE),
    ("min_lowercase", LOWERCASE),
    ("min_special", SPECIAL_CHARACTERS),
)


@dataclass(frozen=True)
class PasswordPolicy:
    length: int = 16
    min_digits: int = 2
    min_uppercase: int = 2
    min_lowercase: int = 2
    min_special: int = 2

    def __post_init__(self) -> None:
        if not MIN_LENGTH <= self.length <= MAX_LENGTH:
            raise ValueError(f"password length must be between {MIN_LENGTH} and {MAX_LENGTH}")

        total = self.min_digits + self.min_uppercase + self.min_lowercase + self.min_special
        if total > self.length:
            raise ValueError(
                "min_digits + min_uppercase + min_lowercase + min_special "
                f"({total}) must not exceed length ({self.length})"
            )
        if total == 0:
            raise ValueError(
                "at least one of min_digits, min_uppercase, min_lowercase, "
                "min_special must be greater than zero"
            )


def generate_password(policy: PasswordPolicy) -> str:
    """Generate a random password satisfying *policy*.

    Each ``min_*`` count is a guaranteed minimum drawn from its own alphabet.
    A category whose minimum is ``0`` is excluded entirely — it never
    contributes to the random fill either. Remaining characters (up to
    ``policy.length``) are drawn from the union of the active categories'
    alphabets, then the whole result is cryptographically shuffled so the
    guaranteed characters aren't predictably front-loaded.
    """
    chars: list[str] = []
    fill_pool_parts: list[str] = []

    for field_name, alphabet in _CATEGORIES:
        count = getattr(policy, field_name)
        if count <= 0:
            continue
        chars.extend(secrets.choice(alphabet) for _ in range(count))
        fill_pool_parts.append(alphabet)

    fill_pool = "".join(fill_pool_parts)
    remaining = policy.length - len(chars)
    chars.extend(secrets.choice(fill_pool) for _ in range(remaining))

    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)
