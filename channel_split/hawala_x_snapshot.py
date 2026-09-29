"""Export the exact rates from a successful hawala Telegram delivery for X."""
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import tempfile

CODES = ('USD', 'EUR', 'GBP', 'CAD', 'AUD', 'SEK', 'TRY')


def write_snapshot(rates, generated_at, path):
    if generated_at.tzinfo is None:
        raise ValueError('Hawala calculation timestamp needs a timezone')
    values = {}
    for code in CODES:
        value = Decimal(str(rates[code]))
        if not value.is_finite() or value <= 0 or value != value.to_integral_value():
            raise ValueError('Invalid whole-toman hawala rate: ' + code)
        values[code] = int(value)
    target = Path(path)
    payload = {'source': 'kiani-hawala',
               'generated_at': generated_at.astimezone(timezone.utc).isoformat(),
               'rates': values}
    # The configured directory must already exist. Never expose partial JSON.
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                dir=target.parent, prefix='.hawala-x-', delete=False) as file:
            name = file.name
            json.dump(payload, file, ensure_ascii=False)
            file.write('\n')
            file.flush()
            os.fsync(file.fileno())
        os.replace(name, target)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)
