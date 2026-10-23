# Tested Kiani exchange release — 23 October 2026

## Included behavior

- Real Ehraz mobile ownership, civil identity/date-of-birth, and bank-card ownership checks are mandatory before registration. Father's name is required. Server-owned proofs bind to the complete normalized request and credential, expire after 90 seconds, and are only cached after a positive result. Missing or malformed provider responses block registration. The civil policy requires a successful exact-DOB/national-ID lookup and four complete 100-percent name comparisons; Ehraz does not return a separate DOB-match boolean.
- Five visible verification steps. User-controlled invalid-input and successful registration checks were completed. The latest fresh registration was confirmed against the authoritative proof record. Password entry and terms acceptance were completed by the user.
- Persistently increasing user IDs prevent deleted-account login tokens from matching a newly created account.
- SMS password reset uses the saved Ghasedak template text, explicit sender 30005088, and the restricted Akamai relay. Text-only delivery, single-use challenge verification and limited retry-on-confirmed-failure rules are preserved. A real handset receipt and full password reset were confirmed by the user. No further diagnostic SMS was sent for this source-preservation release.
- Restored secure administration and KYC review views, including retained-document links and stage-three document instructions.
- USDT and TRY display rates use the shared current-rate path. One fresh source may be displayed indicatively; trading needs two independent qualifying sources, agreement checks and market/liquidity checks. Prices expire after 90 seconds. Akamai is the primary collector, with the existing Google host providing limited backup.

## Deployment configuration

The live server already has the restricted SMS and Ehraz transports. Source is preserved under deploy/kiani-sms, deploy/kiani-market and deploy/ehraz. Provisioning accounts or SSH keys is a separate operator action; publishing this source creates no access.

Keep API keys, SSH keys, known-host files, signed feed snapshots, databases, logs, customer documents and backups outside Git. The existing private backend environment is required. The preservation step securely added KIANI_REGISTRATION_BOT_TOKEN and KIANI_TRANSACTION_BOT_TOKEN there using the existing effective notification credentials. WALLEX_API_KEY remains in the same private environment. runtime_credentials.py reads those values without changing market module startup order. No credential literals are required in Python source.

EHRAZ_TOKEN and GHASEDAK_API_KEY remain private environment settings. Ehraz HTTPS retains its original hostname, SNI and certificate validation through the loopback TLS transport. Akamai carries encrypted bytes and stores no Ehraz API key. Ghasedak requests run on Akamai; its key is supplied through the restricted encrypted relay connection, not stored there. SMS and Ehraz transports use different restricted SSH accounts/commands and must not be conflated.

The companion Shahidi deployment and shared channel_split rate-client files must be deployed consistently. The runtime Python files preserve the existing installation paths; adapt operator-owned paths deliberately when deploying on another host. Install market worker.py and resilient_runtime.py together, and preserve its existing private configuration and allowlisted endpoints.

## Evidence and release boundaries

Frontend builds and Python source checks passed during the deployments; the owner completed fresh registrations on both sites and a complete SMS reset. This preservation step compiles changed Python sources and verifies the Git frontend bytes match the tested live source; it does not run a new automated test suite, send provider requests, submit registrations, restart services or change customer data.

The source commit removes tracked runtime databases from its tree and adds ignore rules. It does not delete the live database or rewrite Git history. Historical credential literals require separate provider-side rotation; removing a current literal does not revoke a credential or erase old commits.

The prepared branch preserves the latest existing production-branch commits. Source rollback must preserve live databases, uploaded documents, private environment settings and user-ID sequences. Do not restore an old database over later customer activity. The shared Ehraz transport is used by both sites.