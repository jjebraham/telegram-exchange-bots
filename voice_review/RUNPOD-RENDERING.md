# On-demand Reel rendering

The renderer creates one disposable GPU worker for a job, copies a verified
input bundle, retrieves the video, checks its checksum and decodes its audio
and video on Selenium. It stops and removes the worker before returning a
successful render to the existing Instagram publisher. Publishing credentials,
narration requests, selection history and duplicate-publication checks stay on
Selenium. Only public code, fonts, images, music and saved narration are copied.

The private narration settings support `REEL_RUNPOD_ENABLED=true` and
`REEL_LOCAL_RENDER_FALLBACK=true`. The GPU feature defaults to disabled. Local
fallback is allowed for capacity or budget failures and after a failed GPU job
has confirmed shutdown. An uncertain resource outcome retains recovery and
budget reservations instead of creating another paid worker.

The shared UTC calendar-month compute limit is $10. Each new session reserves
$0.50 before launch, and replaces that reservation with a conservative elapsed
compute estimate after cleanup. All pages using this manager share the ledger.
New GPU jobs stop when the remaining budget cannot cover a reservation; the
publisher can continue locally. The hardware ceiling is $1/hour, one GPU session
at a time. Estimates include startup, dependency preparation, transfer and
cleanup time; they are not invoices and exclude taxes and storage fees.

The supervised worker has a 420-second execution limit. A persistent systemd
watchdog runs independently on Selenium and recovers failed workers, including
after a restart with user lingering enabled. A second detached deadline runs
inside the Pod and requests shutdown eight minutes after the provider start
time. It uses only the runtime credential already supplied by Runpod to that
Pod; the account API key is never copied from Selenium. Both identity checks
and the Pod-local helper refuse to target another Pod. Provider API/network
outages can delay a stop, so shutdown remains subject to confirmed provider
state rather than a promise based only on a local timeout.

Workers use a pinned official lightweight base image, 20 GB of container disk,
and no persistent volume. They can be placed on any eligible available reviewed
GPU. A short NVENC check runs before the full render. This avoids depending on
reclaiming a GPU from one stopped Pod's original host. Existing user Pods are
never adopted or deleted by this manager.

Run `voice_review/runpod_ephemeral.py --report` with the publisher Python to see
the monthly estimate, outstanding reservations and daily Istanbul totals. Run
`--install` from the pinned staged release to install or upgrade the watchdog;
it refuses to upgrade while a managed render is active.

For rollback, first disable GPU rendering and allow any current session to
close. Keep both cleanup mechanisms available while a resource is unresolved.
Restore the prior private narration settings snapshot before activating an
older release that does not recognize the new feature flags. The prior local
renderer and pinned production release remain available.

Private validation covered a full narrated multi-image video, full decode and
duration checks, visual comparison, a killed supervised worker, and a Pod-local
API stop while Selenium cleanup was held under the per-job lock. No Instagram
publication is needed for these checks, and saved narration avoids additional
ElevenLabs requests.
