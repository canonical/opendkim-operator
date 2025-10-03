# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""OpenDKIM charm utils."""

import os
import re
from pathlib import Path


def update_logrotate_conf(
    path: Path, frequency: str | None = None, retention: int = 0, dateext: bool = True
) -> str:
    """Update existing logrotate config with log retention settings.

    Args:
        path: TODO
        frequency: TODO
        retention: TODO
        dateext: TODO

    Returns:
        TODO
    """
    if not os.path.exists(path):
        return ""

    with open(path, "r", encoding="utf-8") as f:
        config = f.read().split("\n")

    new = []
    regex = re.compile("^(\\s+)(daily|weekly|monthly|rotate|dateext)")
    for line in config:
        m = regex.match(line)
        if not m:
            new.append(line)
            continue

        conf = m.group(2)
        indent = m.group(1)

        # Rotation frequency.
        if frequency and conf in ("daily", "weekly", "monthly"):
            new.append(f"{indent}{frequency}")
        elif retention and conf == "dateext":
            # Ignore 'dateext', we'll put it back on updating 'rotate'.
            continue
        elif retention and conf == "rotate":
            if dateext:
                new.append(f"{indent}dateext")
            new.append(f"{indent}rotate {retention}")
        else:
            new.append(line)

    return "\n".join(new)
