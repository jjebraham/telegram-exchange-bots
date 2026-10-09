# Delayed Instagram Story previews

One branded Story preview follows each successful rates, economy, top 50 and
crypto-news Feed publication. Carousels use their first slide. The original JPEG
is fitted into a 1080×1920 Story without refreshing its prices or rewriting news.
The existing Vazirmatn fonts and Kiani logo surround the complete slide.

The API creates a normal image Story. It cannot create Instagram's native
tappable Feed-post sharing card or link sticker. The Persian prompt directs
viewers to the profile to see the full post.

## Delivery

- Read existing rates JSON and news/economy/top 50 SQLite publication records.
- Only confirmed Feed publications are eligible. The source databases are opened
  read-only, and source publishers are left intact.
- Resolve the final Feed media ID's timestamp through Meta, then set the deadline
  to that timestamp plus 1,800 seconds.
- Prepare the Story container up to five minutes beforehand. A worker runs every
  minute and publishes only when the deadline is reached and processing finishes.
  Normal delivery is within about a minute of the deadline; API delays can add time.
- Track each Feed ID once in a separate SQLite queue, across restarts and cron runs.
- Check the account's live publishing quota before the final request.
- Retry bounded preparation errors. A failed or interrupted final publish request
  becomes `needs_review`, since it may already have succeeded. Never blindly resend.
- Expire pending Stories six hours after their deadline instead of replaying a
  backlog after prolonged downtime. No Story is sent for a failed Feed post.

Usual Istanbul times are rates **12:00**, economy **13:30**, top 50 **16:30** and
crypto news **18:30**. These follow actual Feed publication, rather than a fixed
clock time that would send a Story even when the Feed job failed.

## Activation

Run `activate_story_cron.py --repo REPOSITORY --revision EXACT_REVIEWED_SHA` as the
existing publisher user on the UTC cron host. Use the helper from that same pinned
revision. It confirms all four daily Feed schedules and existing shared assets,
backs up the launcher/configuration/crontab, installs the independent worker, and
replaces only the rates launcher's `feed story` loop with `feed`. All Feed times and
other cron entries are preserved. The queue baselines existing posts on its first
activation, so deployment sends no old Stories. Reinstallation preserves the queue.

The launcher loads the existing private Instagram environment. Credentials are
never copied into this repository or logged. The public Story JPEG directory is
readable by Meta; the queue and configuration remain private.

The worker supports `--status` and `--scan-only` without contacting Instagram.
`--run` enables delivery. Logs report the content category, numeric media IDs and
exception types without printing API error bodies or credential values.

## Review and recovery

Inspect `--status` for `needs_review` and check the account's live Stories before
deciding whether an ambiguous request needs intervention. There is intentionally
no automatic reset of these jobs. Keep the queue database when rolling back or
upgrading, to retain duplicate protection. The activation backup contains the
previous crontab and copies of replaced files; restore only this feature's block
if other schedules have since changed.

Official API references: [Story publishing](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media/),
[media timestamps](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-media/),
and [account publishing quota](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit/).
