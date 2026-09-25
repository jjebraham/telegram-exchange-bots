# Phase 4 — verified rates dashboard

This branch replaces the sample homepage with the live API view: searchable
rate groups, selected rates, observation charts, mobile RTL layout, and clear
stale/empty/error states. It extends the read-only importer to the verified
daily digest and, optionally, the fresh hawala snapshot exported after a
successful Kiani Telegram post. The site does not call upstream collectors or
write to publisher databases.

The server checkout was last reported on `codex/alanchande-website` with
Phase 3 files staged after a failed tracking switch. Inspect the current
state before acting. Never use `git reset --hard` on that checkout.

## 1. Finish Phase 3 first

From `/home/kianirad2020/alanchande-site`, inspect:

```bash
git status --short --branch
git branch --show-current
```

If it is still on `codex/alanchande-website` with the Phase 3 files staged,
run this guarded recovery. It stops if those files differ from the fetched
Phase 3 commit or if there are unstaged edits:

```bash
set -e
cd /home/kianirad2020/alanchande-site
git fetch origin codex/alanchande-phase3-live-data:refs/remotes/origin/codex/alanchande-phase3-live-data
target=origin/codex/alanchande-phase3-live-data
branch=codex/alanchande-phase3-live-data
git diff --cached --quiet "$target" || { echo 'Staged content differs; stopped'; exit 1; }
git diff --quiet || { echo 'Unstaged changes exist; stopped'; exit 1; }
if git show-ref --verify --quiet "refs/heads/$branch"; then
  test "$(git rev-parse "refs/heads/$branch")" = "$(git rev-parse "$target")"
  git switch "$branch"
else
  git switch --no-track -c "$branch" "$target"
fi
git status --short --branch
```

If the checkout is already on the Phase 3 branch, leave it there. Complete
the separate API setup in [Phase 3 deployment](PHASE_3_DEPLOYMENT.md).
Confirm the real publisher database path and use the environment file for
the importer dry run:

```bash
cd /home/kianirad2020/alanchande-site/website
test -f /home/kianirad2020/.config/alanchande-api.env
set -a
. /home/kianirad2020/.config/alanchande-api.env
set +a
.venv/bin/python -m api.import_verified_history
```

Before proceeding, the API service and importer should be active, Nginx
should proxy `/api/` to `127.0.0.1:8012`, and these should work:

```bash
sudo systemctl status --no-pager alanchande-api.service alanchande-import.timer
curl -fsS http://127.0.0.1:8012/healthz
curl -fsS -H 'Host: alanchande.com' http://127.0.0.1/api/v1/quotes
```

The quote response must contain verified rates before the Phase 4 homepage
goes live. If the importer reports zero quotes, inspect its log and publisher
database path first.

## 2. Take a backup and fetch Phase 4

Do this only with a clean website checkout. The backup contains the currently
served static files and the site's own Nginx configuration, if present.

```bash
set -e
cd /home/kianirad2020/alanchande-site
test -z "$(git status --porcelain)"
backup_dir="$(mktemp -d /home/kianirad2020/alanchande-phase4-backup.XXXXXX)"
tar -czf "$backup_dir/site-dist.tgz" -C website dist
if test -f /etc/nginx/sites-available/alanchande.com; then
  sudo cp -p /etc/nginx/sites-available/alanchande.com "$backup_dir/alanchande.com.nginx"
fi
git fetch origin codex/alanchande-phase4-live-ui:refs/remotes/origin/codex/alanchande-phase4-live-ui
target=origin/codex/alanchande-phase4-live-ui
branch=codex/alanchande-phase4-live-ui
if git show-ref --verify --quiet "refs/heads/$branch"; then
  git switch "$branch"
  git merge --ff-only "$target"
else
  git switch --no-track -c "$branch" "$target"
fi
git status --short --branch
printf 'Backup: %s\n' "$backup_dir"
```

The existing Python environment from Phase 3 is sufficient. Run the tests
and a dry run before updating the imported website data:

```bash
cd /home/kianirad2020/alanchande-site/website
python3 -m unittest discover -s tests -v
node --test tests/model.test.mjs
set -a
. /home/kianirad2020/.config/alanchande-api.env
set +a
.venv/bin/python -m api.import_verified_history
```

If the optional hawala export exists and the existing Telegram bridge is
writing it, add this line to the API environment file, then rerun the dry run:

```text
ALANCHANDE_HAWALA_SNAPSHOT=/home/kianirad2020/.local/state/kiani-x/hawala.json
```

Only configure that path when the file exists and is updated by the successful
Telegram hawala post. The importer skips exports older than 15 minutes without
blocking other markets; the website marks the latest imported hawala rates old
after 15 minutes.

## 3. Activate and verify

The API and importer service files are unchanged from Phase 3. Restart the API
to enable no-cache headers, then run one import and check the public route:

```bash
sudo systemctl restart alanchande-api.service
sudo systemctl start alanchande-import.service
sudo systemctl status --no-pager alanchande-api.service alanchande-import.service
curl -fsS http://127.0.0.1:8012/healthz
curl -fsS -H 'Host: alanchande.com' http://127.0.0.1/api/v1/markets
curl -fsS -H 'Host: alanchande.com' http://127.0.0.1/api/v1/quotes
curl -I https://alanchande.com
```

Open the domain in a browser and check that the rates, market groups, and
chart load, and that no sample figures or placeholder chart remain. If the
browser shows a connection warning while the local API works, inspect the
active HTTPS Nginx server block for the `/api/` proxy from Phase 3.

Kiani TRY customer buy/sell and calculator outputs still need a trusted
publication snapshot. The dashboard omits that calculator until those
values can be imported with their exact customer-rate direction.
