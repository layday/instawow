from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    import datetime as dt

    datetime_fromisoformat = dt.datetime.fromisoformat
else:
    import iso8601

    datetime_fromisoformat = iso8601.parse_date
