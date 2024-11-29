from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

import attrs

if TYPE_CHECKING:
    fauxfrozen = attrs.frozen
else:
    fauxfrozen = partial(attrs.define, unsafe_hash=True)
