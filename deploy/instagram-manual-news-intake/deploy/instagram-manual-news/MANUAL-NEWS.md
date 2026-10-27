# Telegram-submitted Instagram news

This extension adds a private Telegram intake to the existing Instagram crypto/economy news publishers.

## Flow

1. An owner creates a dedicated Telegram bot and privately allowlists numeric Telegram user IDs.
2. An allowlisted admin sends one public article URL in a private chat. Optional accompanying text is treated only as a note; it does not enter the factual assessment or translation prompt.
3. The link must resolve to the existing reviewed news-publisher allowlist. The original page must contain a timezone-aware publication time within 24 hours and a usable source passage. Redirects are checked against the reviewed publisher allowlist.
4. The existing DeepSeek assessment classifies the story as relevant crypto or economy hard news. If the categories are ambiguous, the bot declines it. Existing event-history grouping blocks already-published events.
5. The existing Persian translation and readable multi-slide renderer prepare the post. The existing Meta publisher sends it directly after checking the active quota reservation, the current category/day allowance, and a maximum of one post in that category per clock hour.
6. The publisher writes the media ID into the existing crypto/economy publication database. Existing delayed Story discovery and Instagram Insights/retention collection use those same records.

## Safety limits

- Only numeric allowlisted admins in private chats can submit links.
- Exactly one URL is accepted per message. Group chats, unreviewed publishers, stale articles, unusable source text, ambiguous assessments, duplicates, and exhausted quota are declined.
- Submitted notes are never treated as source evidence or translated into the post.
- Telegram update IDs and canonical URLs are kept in a private SQLite intake ledger. An uncertain Meta publish outcome is recorded for review and is never blindly retried.
- The user-news daily cap and existing live Meta quota/Story reservations remain in force. No missed-slot catch-up is added.
- The bot does not delete posts. It records the successful Feed post in the existing news publication table; the already-active two-hour, 200-view retention worker remains the only deletion path and still requires two low observations, current owner/media/views confirmation, and an active permission proof.
- Installation adds one cron polling command and a private launcher. It does not modify existing news, rates, gold, calendar, Story, or retention schedules.

## Private setup

The Selenium installation prompts for a dedicated BotFather token using hidden input and for the numeric admin user ID(s). The token is stored with owner-only file permissions and never printed. Existing Instagram and DeepSeek credentials are read from their current private files.

If a publish attempt is interrupted or its final API result is uncertain, the bot requires an owner to inspect Instagram before that source can be submitted again.
