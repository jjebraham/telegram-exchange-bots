# Fixed TGJU relay for Iranian reports

`ALANCHANDE_TGJU_TRANSPORT=akamai_api` sends read-only requests for the single
`tgju_current` selector through the existing Akamai market-data identity. It
does not provide an administrator shell, modify the bridge, or change any SSH
permission. The host key must match the pinned public key; the identity must
be an owner-only regular file. No alternate key or host is selected on failure.

The relay's existing URL map must first contain the reviewed TGJU public JSON
endpoint. `add_tgju_akamai_endpoint.py` defaults to a read-only check; an
administrator can use `--apply` after that check succeeds. It backs up the
bridge and changes only that fixed endpoint map.

Run `prepare_tgju_api_transport.py` to review the publishing-server changes.
Its `--apply` mode backs up the fetchers and clients, inserts opt-in hooks and
copies the relay client. It preserves local fetcher customizations and can
upgrade the exact previous client version. Unrecognized client code stops the
installation. Preparation leaves the active source setting unchanged.

Before enabling the mode in the publishing environment, run the usual Iranian
currency and gold jobs with that temporary mode and `--dry-run`, using the
normal enforced checks and production history. Both reports must pass before
activation. Subsequent scheduled jobs read the setting normally.

Relay responses must identify the requested selector and protocol and report
success. Their receipt must be at most 30 seconds old; the upstream HTTP date
must be at most 90 seconds old, with cache age at most 30 seconds. Future clock
skew is limited to five seconds. Malformed, unsuccessful, expired or oversized
responses fail closed without switching to another source.

Prices retain TGJU's rial units, with the existing currency conversion to
toman. Native last-change timestamps are preserved. A price that has not
changed is not relabelled as a new tick. Existing cross-source verification,
history acceptance and one-unavailable-noncore-currency policy are unchanged;
gold remains strict about its required quotes.

`public_api` retains direct official-host access; `html` restores the existing
HTML fetchers. Neither mode change alters presentation, schedules, bot tokens
or pricing calculations. Keep identity files and configuration backups private.
