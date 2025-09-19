"""Environment-aware settings loader."""
from __future__ import annotations

import os

ENV = os.environ.get("DJANGO_ENV", "dev").strip().lower()

if ENV in {"production", "prod"}:
    from .prod import *  # noqa: F401,F403
elif ENV in {"test", "testing"}:
    from .dev import *  # noqa: F401,F403
elif ENV in {"development", "dev", ""}:
    from .dev import *  # noqa: F401,F403
else:
    raise RuntimeError(
        "Unsupported DJANGO_ENV value: {env}. Expected 'dev', 'test' or 'prod'.".format(
            env=ENV or "<empty>"
        )
    )
