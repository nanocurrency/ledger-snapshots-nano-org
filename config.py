# This deployment's real settings. Gitignored -- never committed.
# See config.example.py for documentation of each value.

BASE_DIR = "/var/nanocurrency"
LIVE_LEDGER_PATH = f"{BASE_DIR}/Nano/data.ldb"
TEMP_DIR = f"{BASE_DIR}/NanoTemp/"
SEED_DIR = f"{BASE_DIR}/torrents/"

NODE_SERVICE_NAME = "nanocurrency"
NODE_BINARY_NAME = "nano_node"
VALIDATION_THREADS = "6"

ANNOUNCE_TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://tracker.openbittorrent.com:6969/announce",
]

RETENTION_COUNT = 2

ARCHIVE_NAME_TEMPLATE = "Nano_64_%Y_%m_%d_%H.7z"

FEED_TITLE = "Nano Ledger Snapshots"
FEED_LINK = "https://ledger-snapshots.nano.org/"
FEED_DESCRIPTION = ("Torrent releases of Nano ledger snapshots. Subscribe in "
                     "a torrent client with built-in RSS auto-download to "
                     "automatically fetch and seed each new snapshot.")

GIT_AUTHOR_NAME = "snapshot-seed-box"
GIT_AUTHOR_EMAIL = "noreply@nano.org"

SITE_DEPLOY_KEY = "/etc/nanocurrency/ledger_snapshots_deploy_key"
