# Phase 5 first release — trust fixes and UI refresh

This release corrects the first high-value website issues identified in the
coverage review and applies the supplied AlanChande UI refresh.

## Included

- Daily digest filtering uses explicit category metadata, so crypto rows from
  the verified daily digest appear with daily FX and gold rows.
- Quote tables describe reference, two-sided, exchange ask-only, and customer
  prices in Persian instead of treating every value as a generic buy/sell.
- Customer prices show their validity time and become expired after
  `valid_until`; daily digest rows use a day-sized display freshness window.
- Headline rates, source times, stale/expired labels, mobile-friendly tables,
  search normalization, and self-hosted Vazirmatn font assets are included.
- Historical charts use real verified observations and split the line when a
  long publication gap exists. No values are interpolated.

## Local checks

```bash
python3 -m unittest discover -s tests -v
node --test tests/model.test.mjs
```

## Safe server rollout

Run from a clean website checkout. Keep the existing bot checkout and its
services untouched.

```bash
cd /home/kianirad2020/alanchande-site
git status --short --branch
git fetch origin codex/alanchande-phase5-first-release:refs/remotes/origin/codex/alanchande-phase5-first-release
git switch codex/alanchande-phase5-first-release
git merge --ff-only origin/codex/alanchande-phase5-first-release

cd website
python3 -m unittest discover -s tests -v
node --test tests/model.test.mjs
```

Back up `website/dist` and the AlanChande Nginx site block before replacing
the served files. After the backup, install only the contents of `website/dist`
to the existing document root, reload Nginx after `nginx -t`, and verify the
public page, `/api/v1/quotes`, and one `/api/v1/history` series. Restart only
`alanchande-api.service` if the service code changed. The importer and source
database stay under the Phase 3/4 service configuration.

