# Removing a ledger-snapshot mirror

Written for an AI coding agent working alongside the operator, same as
`INSTALL.md`. Confirm with the operator which of these they actually want
before running anything — some steps are destructive.

This intentionally only undoes what `INSTALL.md` set up. It does **not**
touch the underlying `nano_node`/`qbittorrent-nox` installation or their
systemd units — those were either pre-existing or set up separately, and
removing them is out of scope here (same reasoning as `INSTALL.md` not
covering their installation).

## 1. Stop the cadence

```
sudo systemctl disable --now ledger-snapshot.timer
sudo rm /etc/systemd/system/ledger-snapshot.timer /etc/systemd/system/ledger-snapshot.service
sudo systemctl daemon-reload
```

(Or remove the equivalent cron entry, if that was used instead.)

## 2. Confirm before removing local state

Ask the operator explicitly before each of these — they're irreversible
and only relevant if this box is being fully decommissioned, not just
paused:

- Seeded torrents / working directory (`config.py`'s `SEED_DIR`/`TEMP_DIR`)
- The deploy key (`config.py`'s `SITE_DEPLOY_KEY`) — also remove it from
  the repo's Settings → Deploy keys on GitHub
- The qBittorrent-nox credentials file (`/etc/nanocurrency/qbittorrent.env`)
- `config.py` itself (never committed, so deleting the checkout also
  removes it — flag this explicitly since it can't be recovered from git)

## 3. Leave alone unless asked

- The live `nano_node` and `qbittorrent-nox` services/data — these likely
  serve purposes beyond this pipeline (e.g. `nano_node` may still be
  peering/voting) and shouldn't be stopped as a side effect of removing
  the snapshot pipeline.
- The GitHub repo itself and its published Pages site — removing those is
  a separate, larger decision than uninstalling the pipeline that fed them.
