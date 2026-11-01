"""The errors a query raises on purpose.

Their messages are written for the calling LLM (closest and available names, how to retry), so a
caller turns them into a tool error. Anything else is a bug and must not reach the model.
"""

from __future__ import annotations

from nautobot_read.client import NautobotError
from nautobot_read.networks import InvalidInputError
from nautobot_read.vocabularies import AmbiguousNameError
from nautobot_read.vocabulary import UnknownNameError

EXPECTED_ERRORS: tuple[type[Exception], ...] = (
    UnknownNameError,
    AmbiguousNameError,
    InvalidInputError,
    NautobotError,
)
