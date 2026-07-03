# Installing your own ledger-snapshot mirror

This document is written for an AI coding agent (e.g. Claude Code) working
alongside the node operator to set this up interactively — not a script to
run unattended. Each step below involves a judgment call or a value only
the operator knows; walk through them one at a time, asking the operator
for anything you don't already know rather than guessing.

Assumes: a Linux box already running a synced `nano_node` (systemd service
or otherwise) and `qbittorrent-nox`, with SSH access. This document does
**not** cover installing/building those — that's a separate, much more
variable setup left to the operator (or a different agent session).

## 1. Check prerequisites

`scripts/snapshot.py` runs `check_prerequisites()` as its first action
every time it's invoked, so step 6's manual run will surface any missing
tool immediately, printing the resolved path of everything it *did* find.
To check earlier, without any side effects, run the same check standalone:

```
python3 -c "
import shutil
for tool in ['nano_node', '7z', 'mktorrent', 'git', 'sudo']:
    print(tool, shutil.which(tool) or 'MISSING')
"
```

If anything's missing or resolves to a suspicious path (e.g. `/usr/local/bin`
when you expected `/usr/bin`), fix that first — a wrong-binary PATH shadow
is exactly the kind of bug this check exists to catch early instead of
mid-run.

## 2. Create config.py

```
cp config.example.py config.py
```

Ask the operator for:
- `BASE_DIR` (and whether `LIVE_LEDGER_PATH`/`TEMP_DIR`/`SEED_DIR` need
  overriding individually, if their layout doesn't match `BASE_DIR/...`)
- `NODE_SERVICE_NAME` (must match whatever they name the systemd unit in
  step 4)
- `RETENTION_COUNT` and available disk space — remind them retention is
  seed-then-purge, so peak usage briefly needs headroom for
  `RETENTION_COUNT + 1` archives, not `RETENTION_COUNT`
- `FEED_TITLE`/`FEED_LINK`/`FEED_DESCRIPTION` — `FEED_LINK` should be their
  actual domain (matching the `CNAME` file, see step 3)
- `GIT_AUTHOR_NAME`/`GIT_AUTHOR_EMAIL` for the automated publish commits

Edit `config.py` with these values. Confirm it's covered by `.gitignore`
(`git check-ignore config.py` should succeed) before going further —
credentials and deploy-key paths in here should never be committed.

## 3. Set the domain

Edit `CNAME` to the operator's own domain (e.g. `ledger-snapshots.example.org`)
and commit it. Point that domain's DNS at GitHub Pages (a `CNAME` record to
`<their-username-or-org>.github.io`) — this is the operator's own DNS
provider, outside this repo's scope. Enable GitHub Pages on this repo
(Settings → Pages → deploy from the branch this pipeline pushes to).

Committing the `CNAME` file is enough for GitHub Pages to *serve* the
domain, but it does **not** reliably trigger certificate issuance for it
-- that only fires on an explicit domain-set through the Pages API (or
the Settings UI's "Custom domain" field). Do that explicitly as its own
step, don't rely on the committed file alone:

```
gh api -X PUT repos/<owner>/<repo>/pages -f cname='<your-domain>'
```

Confirm it actually started provisioning before moving on --
`https_certificate` should appear in the response (not be missing
entirely) with `"state": "new"` or further along:

```
gh api repos/<owner>/<repo>/pages --jq .https_certificate
```

If it's still missing after the PUT above, DNS likely isn't propagated
yet -- verify with `dig +short CNAME <your-domain>` before retrying.
Confirmed in practice: a correctly-issued cert reaches `"state":
"approved"` within about 20 seconds of a successful domain-set.

## 4. Deploy key and systemd units

Generate an SSH key scoped to push access on this repo only (not a personal
credential):

```
ssh-keygen -t ed25519 -f /etc/nanocurrency/ledger_snapshots_deploy_key -N ""
```

Add the public key as a **write-enabled** deploy key on this repo (repo
Settings → Deploy keys), and set `SITE_DEPLOY_KEY` in `config.py` to the
private key's path if it differs from the example.

Copy `scripts/nanocurrency.service.example` and
`scripts/qbittorrent-nox.service.example` to
`/etc/systemd/system/<name>.service`, editing every line marked `# EDIT:`
to match `config.py`'s actual values (paths, service name). These are
meant to be hand-edited per deployment, not rendered from a template —
if the operator's `nano_node`/`qbittorrent-nox` are already running under
different existing units, skip this and just make sure `NODE_SERVICE_NAME`
in `config.py` matches whatever's already there.

```
sudo systemctl daemon-reload
sudo systemctl enable --now <name>.service   # only if newly created above
```

## 5. qBittorrent-nox WebUI: loopback-only, no password

`scripts/snapshot.py` talks to qBittorrent-nox's WebUI/REST API purely
locally (it always runs on the same box), so there's no reason for that
API to be reachable off-box at all -- the bind address is the real
security boundary here, not a login. In qBittorrent's config (usually
`~/.config/qBittorrent/qBittorrent.conf` for whatever user runs it):

```
WebUI\Address=127.0.0.1
WebUI\LocalHostAuth=false
```

Restart `qbittorrent-nox` after editing. No credentials file needed --
`QBIT_API_BASE` in `scripts/snapshot.py` already points at
`http://127.0.0.1:8080`. If the operator changed `--webui-port` in
`qbittorrent-nox.service.example`, update `QBIT_API_BASE` to match.

## 6. First manual run

Before automating anything, run it once by hand and watch it succeed:

```
sudo python3 scripts/snapshot.py
```

Confirm: `check_prerequisites()` passes, `Validation status: Ok`, a
`.torrent` gets registered with qbittorrent-nox, and the run ends with
`published <archive_name> to <your repo's URL>` — check that the commit
actually landed on GitHub and Pages picked it up.

## 7. Automate the cadence

Once a manual run succeeds, set up a systemd timer (preferred) or cron
entry to run it on the operator's chosen cadence (e.g. daily, twice a
week). Ask the operator for their preferred schedule rather than assuming
one. Example systemd timer, adjust `OnCalendar` to taste:

```
# /etc/systemd/system/ledger-snapshot.service
[Unit]
Description=Run ledger snapshot pipeline

[Service]
Type=oneshot
WorkingDirectory=<path to this repo checkout>
ExecStart=/usr/bin/python3 scripts/snapshot.py
```

```
# /etc/systemd/system/ledger-snapshot.timer
[Unit]
Description=Run ledger-snapshot.service on a cadence

[Timer]
OnCalendar=Sun,Wed 03:00
Persistent=true

[Install]
WantedBy=timers.target
```

```
sudo systemctl daemon-reload
sudo systemctl enable --now ledger-snapshot.timer
```
