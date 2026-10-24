# Readable news carousels — approved Option B

Apply the approved mint/green design to future crypto and economy news posts.
The first page shows the original source illustration, full headline and a
physical left-arrow/swipe prompt. Following pages show the complete verified
Persian summary at **64px**, with 96px line spacing, at most seven lines/page,
clear page numbers, source/date, progress and continuation prompts.

The number of pages adapts to the summary. Short stories use fewer pages;
longer ones use additional pages up to the existing ten-slide limit. Do not
shrink body text or silently truncate content. Character spans and source-text
hashes prove all normalized summary text is preserved. Very long tokens can
wrap without changing their underlying characters. A longer headline gets a
taller panel, retaining at least 72px type and the full headline.

Original image metadata/download behavior is retained. Fit the whole photo
over a blurred backdrop to preserve portrait/wide images without distortion.
When the original image is unavailable, use a branded cover as before; never
invent an image or use an unrelated picture. The caption retains the original
attribution and summary, subject to the existing caption limit.

## Deployment

`run_carousel.py` extracts twelve small files from a pinned commit. Default mode
runs the existing live selector for one unpublished qualifying story per category
and creates local/public preview slides; it sends no Meta requests. Ranking,
source passage/original 24-hour timestamp, opinion/forecast filters, translation,
deduplication, quota planning and publication helper are unchanged.

`--kind crypto` or `--kind economy` can regenerate an individual preview if needed.
`--activate` requires a successful exact-runtime/assets layout preview in both
categories within 24 hours, readable JPEGs, and complete source-text manifests.

When no unpublished story qualifies, use `--layout-preview` (optionally with
`--kind economy` or `--kind crypto`). This reads a completed single-story
publication and its original manifest from the existing database in SQLite
read-only/query-only mode. It re-renders exactly that saved text/date/attribution
and records a separate private layout audit. It performs no selection, ranking,
translation, Meta request, publication claim or database write. Preview output
explicitly identifies historical examples; their manifests carry
`layout_preview_only=true`. They are never inserted into ranking runs or reused
by scheduled publication. Activation rechecks the original completed publication
and exact manifest hash as well as all common layout/text/asset proofs. Thus
layout verification cannot be blocked just because today's news has already
been published or rejected; actual scheduled posts still need fresh eligible news.

The narrow installer verifies the confirmed PR75 deployment
`4745d848a1253b5c3ec39bf86a723b4c560ff8cd`, all nine old news source hashes,
the exact hourly launchers/cron, existing analytics fingerprint and 200/2h policy,
and the existing news Story registrations. It installs a new immutable news
runtime and changes only both news-launcher paths and news-specific activation
metadata. Worker locks, private backups, concurrent-edit checks and guarded
rollback are included. An identical revision can be reapplied.

It does not rewrite cron, publication/analytics databases, policy or enrollment,
analytics code/launcher, Story code/configuration, tokens or other publishers.
Selection/quota/publishing code in the new release must remain byte-identical.
No unit tests are added or run by preview/activation.

## Existing policies remain

- One carousel is one Feed post, not one post per page; at most one per hourly
  slot and ten per category/day.
- Istanbul crypto 10:00–19:00 on the hour; economy 10:30–19:30 on the half hour.
- One cover Story follows successful Feed publication by 30 minutes.
- The existing 2-hour/below-200-Views news rule already accepts CAROUSEL_ALBUM.
  The same parent Feed ID is registered, measured and conditionally deleted.
  Original cutoff, low-reading rechecks, protected kinds, missing-data behavior
  and uncertain-result guards remain.
- Installation publishes/deletes nothing immediately. Later scheduled slots
  rerank fresh eligible news and collect their own source evidence; previews
  are never reused as scheduled publication content.

The owner's Chamath article was a design example. This update does not create
an exception to the existing opinion/forecast eligibility filter or force that
article into the scheduled news queue.
