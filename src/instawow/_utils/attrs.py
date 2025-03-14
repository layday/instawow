from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

import attrs

fauxfrozen = attrs.frozen if TYPE_CHECKING else partial(attrs.define, unsafe_hash=True)
