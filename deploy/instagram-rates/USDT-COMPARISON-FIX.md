# USDT exchange comparison row handling

The exchange comparison belongs inside the 11:30 rates Feed carousel. The
separate Story preview contains only the first slide of that carousel.

Recent publication records showed the comparison omitted because the assessed
Telegram export failed, and later because the Instagram row parser rejected an
exchange buy/sell pair. The parser previously rejected the whole section whenever
one provider's bid was equal to or above its ask.

The fix accepts equal displayed prices and excludes individual invalid or genuinely
crossed quotes. It never reverses a pair, replaces a quote with a historical price,
or bypasses upstream assessment. Excluded providers and reasons are logged and
recorded in the manifest. At least two valid providers are needed. Unexpected
headers, duplicate providers, unsupported table sizes and stale exports still
block the comparison.

The installer replaces only `instagram_carousel.py` after checking the installed
original or already-patched bytes. It backs up that file, validates syntax,
refuses concurrent rates publication, and confirms the existing crontab is
unchanged. Customer pricing, shared fonts/logo, the Graph publishing helper,
publication state, other publishers and delayed Stories are retained.

Run the helper from an exact reviewed revision with `--repo REPOSITORY --revision
SHA`. Installation sends no Instagram post. Run `--check-live` afterward with
the existing Instagram venv and exported private environment to read fresh assessed
exchange quotes and confirm the resulting section. This mode publishes nothing.

This change fixes Instagram row handling. It cannot make an unavailable or
unverified upstream export valid; those collection failures remain visible and
require source-health diagnosis. Successful rendered manifests alone do not prove
publication: match them to the saved successful Feed state.
