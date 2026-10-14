# Persian and Gregorian dates on the rates cover

The approved cover replaces its `نرخ امروز` label with two lines:

```
چهارشنبه · ۲۲ مهر ۱۴۰۵
Wed · 14 Oct 2026
```

`instagram_calendar.calendar_labels` requires an aware timestamp, converts it
once to `Europe/Istanbul`, and derives both calendar dates, weekday names and
clock labels from that same local instant. The Persian line uses Persian
digits, and the Gregorian line uses Latin digits. Explicit weekday/month names
avoid dependence on the server locale. Jalali conversion uses pinned
`jdatetime==5.2.0` and `jalali-core==1.0.0`.

The cover's Istanbul clock comes from the same timestamp. A `calendar` object
in the carousel manifest records the timezone, local ISO timestamp, Gregorian
and Jalali dates, the two displayed lines and clock values. The date is derived
at rendering time for each new post; it is never hardcoded from this example.

## Verification

Eight regression tests cover the approved date and glyphs, all weekdays,
Istanbul midnight, timestamps supplied in Tehran time, Gregorian New Year,
Nowruz and a Persian leap-year boundary. A daily roundtrip check covers 2020
through 2069, over 18,000 dates. The actual Feed and Story designs were rendered
locally using sample data and inspected for legibility and spacing.

## Activation

Run `activate_calendar_template.py` from an exact reviewed revision. It expects
the installed Hawala source version, checks file ownership and the Feed lock,
prepares pinned calendar packages in a separate directory, runs the calendar
checks before changing files, backs up the original files, installs the helper
and carousel integration, and repeats verification through the installed helper.
It restores changed files if activation fails. The shared venv's existing
packages are not upgraded.

The rates launcher, crontab, publication state, fresh Hawala source and USDT
comparison are preserved. The existing 11:30 Istanbul carousel will render the
new date block; the delayed Story uses that Feed image with the same date.
The Story header and caption remain category labels. Other post types and
their schedules are outside this template change. Installation publishes no
test post, and it does not alter existing Instagram posts.

Conversion API: https://pypi.org/project/jdatetime/5.2.0/
