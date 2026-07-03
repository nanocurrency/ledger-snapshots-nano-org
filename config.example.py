# Operator-specific settings for scripts/snapshot.py.
#
# Copy this file to config.py (gitignored -- never committed) and fill in
# your own values. scripts/snapshot.py imports config.py directly; nothing
# in this repo's tracked files should need editing for a normal deployment.

# Base directory the node's live ledger, working files, and seeded torrents
# live under. LIVE_LEDGER_PATH, TEMP_DIR, SEED_DIR all default off this --
# override them individually below if your layout doesn't match.
BASE_DIR = "/var/nanocurrency"
LIVE_LEDGER_PATH = f"{BASE_DIR}/Nano/data.ldb"
TEMP_DIR = f"{BASE_DIR}/NanoTemp/"
SEED_DIR = f"{BASE_DIR}/torrents/"

# systemd unit name for the live nano_node daemon (node_service() stops/
# starts this around the copy step) and the node binary's name on $PATH.
NODE_SERVICE_NAME = "nanocurrency"
NODE_BINARY_NAME = "nano_node"
VALIDATION_THREADS = "6"

# Public UDP trackers used purely as a fast-bootstrap fallback for a
# brand-new infohash -- DHT+PEX (see qbittorrent-nox.service.example) means
# no tracker is strictly required for long-term swarm health.
ANNOUNCE_TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
]

# How many snapshot archives stay seeded/listed at once. Retention is
# enforced seed-then-purge (the new archive is fully seeded before the
# oldest is retired), so peak disk usage briefly needs headroom for
# RETENTION_COUNT+1 archives, not RETENTION_COUNT.
RETENTION_COUNT = 2

# strftime template for each archive's filename.
ARCHIVE_NAME_TEMPLATE = "Nano_64_%Y_%m_%d_%H.7z"

# RSS feed metadata (feed.xml) and per-item link base -- update these for
# your own domain/branding.
FEED_TITLE = "Nano Ledger Snapshots"
FEED_LINK = "https://ledger-snapshots.nano.org/"
FEED_DESCRIPTION = ("Torrent releases of Nano ledger snapshots. Subscribe in "
                     "a torrent client with built-in RSS auto-download to "
                     "automatically fetch and seed each new snapshot.")

# Identity used for the automated data.json/latest.json/feed.xml publish
# commits this script makes to its own repo.
GIT_AUTHOR_NAME = "snapshot-seed-box"
GIT_AUTHOR_EMAIL = "noreply@example.org"

# SSH deploy key scoped to push access on this repo only (see INSTALL.md).
SITE_DEPLOY_KEY = "/etc/nanocurrency/ledger_snapshots_deploy_key"
