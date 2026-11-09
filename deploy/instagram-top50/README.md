# Four-slide Kiani crypto highlights

The daily carousel contains, in order:

1. Market breadth for the same 50 eligible coins, with BTC and ETH changes.
2. Up to five gainers beyond the existing displayed 2% threshold.
3. Up to five decliners beyond the same threshold.
4. Comment, save, share and Telegram prompts.

The cover has green, red, mixed, unchanged and unavailable-data states. Missing changes are hollow dots and never counted as flat. Kiani's actual logo and company name stay solid white across themes. English ticker labels are prominent, with smaller Persian names below.

CoinPaprika selection, classifications, volume filters and quote-freshness policies remain unchanged. The market-rate collector is retained without modifying its evidence or approval policy. Sample snapshots cannot be published. Bounded expiry recovery recollects the entire snapshot; uncertain final publication blocks retries. Existing scheduling, publication history and first-image Story registration are preserved.

The renderer uses the existing Vazirmatn fonts, Kiani SVG and calendar library. Calendar dependency source files are included in the shared-assets fingerprint.

## Verification and activation

`run_gainers.py --repo <repository> --revision <commit>` extracts the pinned source and prepares a fresh preview without publication. `check_highlights.py --runtime <source> --revision <commit>` verifies public images and creates four image containers plus an unpublished ready carousel; it never calls `media_publish`.

`run_gainers.py --repo <repository> --revision <commit> --activate` requires matching source bytes, the known predecessor, recent preview and account-bound four-image receipt. Activation takes the existing job lock, backs up the launcher and activation record, preserves schedule and Story configuration bytes, and leaves the prior release intact. It does not publish or backfill a post.

Rollback must take the same job lock and compare current launcher/activation bytes with the installed release before restoring the backed-up launcher and activation record. Do not overwrite unrelated later changes or alter publication history.

Offline tests cover market breadth, missing data, mover thresholds, rendering, four-child order, old-layout rejection, duplicate and uncertain-publication guards. Meta clients are mocked in unit tests.
