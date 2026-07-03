#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import subprocess
import shutil
import hashlib
import fcntl
import datetime
import json
import urllib.parse
import xml.sax.saxutils as saxutils
from pathlib import Path
import requests

# This script lives inside the repo it publishes to (scripts/snapshot.py),
# so REPO_ROOT is simply its own checkout -- no separate site-repo clone/
# sync-from-scratch step needed, unlike a script that lived elsewhere.
# config.py lives at the repo root (alongside config.example.py), one
# level up from this script, so it has to be added to sys.path explicitly
# -- Python only searches the script's own directory by default.
REPO_ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, REPO_ROOT)
import config

print(datetime.datetime.utcnow().strftime("\n%Y-%m-%d %H:%M:%S"))

archive_name = datetime.datetime.utcnow().strftime(config.ARCHIVE_NAME_TEMPLATE)
archive_path = f"{config.TEMP_DIR}{archive_name}"

live_path = config.LIVE_LEDGER_PATH
data_path = f"{config.TEMP_DIR}data.ldb"
backup_vacuum_path = f"{config.TEMP_DIR}backup.vacuum.ldb"
temp_folder_path = config.TEMP_DIR
node_path = config.NODE_BINARY_NAME
threads = config.VALIDATION_THREADS
service_name = config.NODE_SERVICE_NAME

announce_trackers = config.ANNOUNCE_TRACKERS

# qbittorrent-nox WebUI/API. Bound to loopback only (WebUI\Address=127.0.0.1
# in qBittorrent.conf) -- this script always runs locally on the same box,
# so there's no reason for the WebUI to be reachable over the tailnet at
# all. With WebUI\LocalHostAuth=false, loopback connections skip the
# login/password step entirely: the bind address is the actual security
# boundary (nothing off-box can reach it), not an app-layer credential on
# top of an unnecessarily wide bind.
QBIT_API_BASE = "http://127.0.0.1:8080"

SEED_DIR = config.SEED_DIR
RETENTION_COUNT = config.RETENTION_COUNT

SITE_DEPLOY_KEY = config.SITE_DEPLOY_KEY
GIT_SSH_COMMAND = f"ssh -i {SITE_DEPLOY_KEY} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"


def check_prerequisites():
    # Fail fast, before touching the live node, if a required tool is
    # missing -- and print each one's *resolved* path, not just pass/fail.
    # This is exactly what would have caught two real PATH-shadowing bugs
    # (nano_node and sha3sum both silently resolving to the wrong binary)
    # immediately instead of via a crash or wrong output partway through a
    # run.
    required_tools = [node_path, "7z", "mktorrent", "git", "sudo"]
    missing = []
    for tool in required_tools:
        resolved = shutil.which(tool)
        if resolved:
            print(f"found {tool}: {resolved}")
        else:
            missing.append(tool)
    if missing:
        print(f"ERROR: missing required tools: {', '.join(missing)}")
        exit(1)


def node_service(action='stop'):
    subprocess.run(["sudo", "/usr/sbin/service", service_name, action],
                    check=True, capture_output=True, text=True)
    print(f"service {action}")


def reflink_copy(src, dst):
    # Whole-file CoW clone via a single FICLONE ioctl -- the same syscall
    # `cp --reflink` uses -- rather than shutil.copy2's chunked
    # copy_file_range loop, which achieves the same extent-sharing but
    # ~2.7x slower (measured: 20.6s vs 7.8s for a 1.48GB live data.ldb on
    # this XFS reflink=1 volume). This is the biggest, most time-sensitive
    # copy in the pipeline, so the gap is worth avoiding. Falls back to a
    # regular copy if the filesystem/pair of paths doesn't support reflink
    # (e.g. cross-device), matching `cp --reflink=auto`'s behavior.
    if os.path.isdir(dst):
        dst = os.path.join(dst, os.path.basename(src))
    with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
        try:
            fcntl.ioctl(fdst.fileno(), fcntl.FICLONE, fsrc.fileno())
            return
        except OSError as e:
            # Loud, not silent: a reflink failure here means either the
            # filesystem doesn't support it (wrong fs type, reflink=0) or
            # src/dst ended up on different filesystems/devices -- either
            # way it's a real regression (this copy step is why XFS
            # reflink=1 was chosen for /var/nanocurrency in the first
            # place) and falls through to a full, much slower byte-for-byte
            # copy rather than a near-free CoW clone. An operator should
            # know immediately, not discover it later from a slow run.
            print(f"WARNING: reflink copy of {src} to {dst} failed "
                  f"({e}) -- falling back to a full copy")
    shutil.copy2(src, dst)


def copy_live_to_temp():
    print(f"begin copy to {temp_folder_path}")
    reflink_copy(live_path, temp_folder_path)
    print(f"copied to {temp_folder_path}")


def temp_path_actions():
    # Retrieve block count
    block_count = subprocess.run(
        [node_path, "--debug_block_count", f"--data_path={temp_folder_path}"],
        check=True, capture_output=True, text=True).stdout.rstrip()
    print(block_count)
    # Retrieve cemented block count
    cemented_block_count = subprocess.run(
        [node_path, "--debug_cemented_block_count", f"--data_path={temp_folder_path}"],
        check=True, capture_output=True, text=True
    ).stdout.rstrip().replace("Total cemented", "Cemented")
    print(cemented_block_count)
    # Vacuum
    subprocess.run(
        [node_path, "--vacuum", "--unchecked_clear", "--peer_clear",
         "--online_weight_clear", f"--data_path={temp_folder_path}"],
        check=True, capture_output=True, text=True)
    print(f"vacuumed")
    return block_count, cemented_block_count


def validate_blocks():
    validation_result = subprocess.run(
        [node_path, "--validate_blocks", "--silent", f"--threads={threads}",
         f"--data_path={temp_folder_path}"],
        check=True, capture_output=True, text=True).stdout
    print(validation_result)
    if "Validation status: Ok" in validation_result and os.path.isfile(f"{temp_folder_path}data.ldb"):
        create_archive()
        return True
    return False


def create_archive():
    zip_result = subprocess.run(
        ["7z", "a", "-t7z", "-mmt4", archive_path, data_path],
        check=True, capture_output=True, text=True).stdout
    print(zip_result)


def generate_size_info():
    size_b = os.path.getsize(archive_path)
    size_data_b = os.path.getsize(data_path)
    # Apparent/logical byte size divided by 1MiB -- not the allocated-disk-
    # block-rounded figure `ls -s --block-size=MiB` used to report. Purely
    # cosmetic text either way; size_bytes (the value actually used
    # downstream) has always been an exact byte count.
    size_mb = f"{size_b / 1024**2:.2f}MiB"
    size_data_mb = f"{size_data_b / 1024**2:.2f}MiB"
    sizes_string = f"Archive size: {size_b} bytes ({size_mb})\ndata.ldb unpacked size: {size_data_b} bytes ({size_data_mb})"
    return sizes_string, size_b


def cleanup_temp_ldb():
    # data_path (the vacuumed/compacted data.ldb) and backup_vacuum_path
    # (the pre-compaction original, left behind by nano_node --vacuum's
    # internal rename dance) are both roughly ledger-sized and no longer
    # needed by anything downstream once generate_size_info() has read
    # them -- generate_hashes() only touches archive_path. Removing these
    # here rather than waiting for the final cleanup() meaningfully cuts
    # the peak disk usage window during torrent creation/seeding, on top
    # of whatever headroom the seed-then-purge retention spike (see
    # RETENTION_COUNT) already needs.
    Path(data_path).unlink(missing_ok=True)
    Path(backup_vacuum_path).unlink(missing_ok=True)


def generate_hashes():
    # Single streaming pass computing all three digests at once, rather than
    # three separate full-file reads (one per external hashing tool).
    h_sha256 = hashlib.sha256()
    h_sha3 = hashlib.sha3_512()
    h_blake2 = hashlib.blake2b(digest_size=64)
    with open(archive_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h_sha256.update(chunk)
            h_sha3.update(chunk)
            h_blake2.update(chunk)
    sha256 = h_sha256.hexdigest().upper()
    sha3 = h_sha3.hexdigest().upper()
    blake2 = h_blake2.hexdigest().upper()
    hashes_string = f"Archive checksums:\n\tSHA256: {sha256}\n\tSHA3-512: {sha3}\n\tBLAKE2b-512: {blake2}"
    return hashes_string, sha256, sha3, blake2


def generate_final_string(block_count, cemented_block_count, sizes_string, hashes_string):

    push_text = f"{archive_name} \n{block_count}\n{cemented_block_count}\n{sizes_string}\n{hashes_string}"
    print(push_text)
    return push_text


def create_torrent():
    torrent_path = f"{archive_path}.torrent"
    trackers = ",".join(announce_trackers)
    subprocess.run(
        ["mktorrent", "-a", trackers, "-c", f"Nano ledger snapshot: {archive_name}",
         "-l", "24", "-o", torrent_path, archive_path],
        check=True, capture_output=True, text=True)
    print(f"created torrent {torrent_path}")
    return torrent_path


def seed_torrent(torrent_path):
    os.makedirs(SEED_DIR, exist_ok=True)
    seeded_archive_path = os.path.join(SEED_DIR, archive_name)
    seeded_torrent_path = os.path.join(SEED_DIR, os.path.basename(torrent_path))
    # Same filesystem (both under /var/nanocurrency) -- shutil.move() tries
    # os.rename() first, so this is a rename, not a copy, near-instant
    # regardless of archive size.
    shutil.move(archive_path, seeded_archive_path)
    shutil.move(torrent_path, seeded_torrent_path)

    # No login step -- WebUI\LocalHostAuth=false means loopback connections
    # (this script always runs on the same box) skip auth entirely.
    session = requests.Session()

    with open(seeded_torrent_path, "rb") as f:
        add = session.post(
            f"{QBIT_API_BASE}/api/v2/torrents/add",
            files={"torrents": (os.path.basename(seeded_torrent_path), f)},
            data={
                "savepath": SEED_DIR,
                # The archive was just hashed by us moments ago
                # (generate_hashes()) and the .torrent's piece hashes were
                # computed directly from this exact, untouched file --
                # skip libtorrent's own hash-check pass rather than
                # re-reading the whole archive a second time.
                "skip_checking": "true",
                "category": "nano-ledger-snapshot",
            })
    if add.status_code != 200:
        raise RuntimeError(f"qbittorrent-nox add torrent failed: {add.status_code} {add.text}")
    print(f"registered {seeded_torrent_path} with qbittorrent-nox")

    infohash = get_torrent_hash(session, archive_name)
    enforce_retention(session)
    return seeded_torrent_path, infohash


def get_torrent_hash(session, name):
    resp = session.get(f"{QBIT_API_BASE}/api/v2/torrents/info",
                        params={"category": "nano-ledger-snapshot"})
    for t in resp.json():
        if t["name"] == name:
            return t["hash"]
    raise RuntimeError(f"could not find torrent info for {name} after adding")


def enforce_retention(session):
    resp = session.get(f"{QBIT_API_BASE}/api/v2/torrents/info",
                        params={"category": "nano-ledger-snapshot"})
    torrents = sorted(resp.json(), key=lambda t: t["added_on"], reverse=True)
    for t in torrents[RETENTION_COUNT:]:
        print(f"retiring {t['name']} (added {t['added_on']})")
        session.post(f"{QBIT_API_BASE}/api/v2/torrents/delete",
                     data={"hashes": t["hash"], "deleteFiles": "true"})
        # deleteFiles=true only removes the content qBittorrent itself
        # manages (the .7z) -- it doesn't know about or clean up the
        # source .torrent file we uploaded from, so that's a manual
        # leftover to remove ourselves (verified via live smoke test).
        leftover_torrent = os.path.join(SEED_DIR, f"{t['name']}.torrent")
        if os.path.exists(leftover_torrent):
            os.remove(leftover_torrent)


def _git(*args):
    env = dict(os.environ, GIT_SSH_COMMAND=GIT_SSH_COMMAND)
    return subprocess.run(["git", "-C", REPO_ROOT, *args], env=env,
                           capture_output=True, text=True)


def sync_repo():
    # This script runs from inside its own checkout, so there's no
    # clone-if-missing case (that checkout is how the script got here in
    # the first place). Just make sure it's exactly up to date with origin
    # before publishing -- if the operator made local uncommitted changes
    # to their own copy of this repo and didn't commit them, this discards
    # those, same as sync_site_repo()'s previous hard-reset behavior.
    _git("fetch", "origin").check_returncode()
    _git("reset", "--hard", "origin/main").check_returncode()


def generate_feed(snapshots):
    items = []
    for s in snapshots:
        pub_date = datetime.datetime.strptime(
            s["created_utc"], "%Y-%m-%dT%H:%M:%SZ"
        ).strftime("%a, %d %b %Y %H:%M:%S GMT")
        url = f"{config.FEED_LINK.rstrip('/')}/{saxutils.escape(s['torrent_url'])}"
        items.append(f"""    <item>
      <title>{saxutils.escape(s['name'])}</title>
      <link>{url}</link>
      <guid isPermaLink="false">{saxutils.escape(s['name'])}</guid>
      <pubDate>{pub_date}</pubDate>
      <enclosure url="{url}" length="{s['size_bytes']}" type="application/x-bittorrent" />
    </item>""")
    feed = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>{saxutils.escape(config.FEED_TITLE)}</title>
    <link>{config.FEED_LINK}</link>
    <description>{saxutils.escape(config.FEED_DESCRIPTION)}</description>
    <language>en-us</language>
{chr(10).join(items)}
  </channel>
</rss>
"""
    with open(os.path.join(REPO_ROOT, "feed.xml"), "w") as f:
        f.write(feed)


def publish_listing(torrent_path, infohash, block_count, cemented_block_count,
                     size_bytes, sha256, sha3, blake2):
    sync_repo()

    torrent_filename = os.path.basename(torrent_path)
    shutil.copy2(torrent_path, os.path.join(REPO_ROOT, torrent_filename))
    shutil.copy2(torrent_path, os.path.join(REPO_ROOT, "latest.torrent"))

    trackers_qs = "&".join(f"tr={urllib.parse.quote(t)}" for t in announce_trackers)
    magnet = (f"magnet:?xt=urn:btih:{infohash}"
              f"&dn={urllib.parse.quote(archive_name)}&{trackers_qs}")

    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = {
        "name": archive_name,
        "created_utc": now,
        "block_count": block_count,
        "cemented_block_count": cemented_block_count,
        "size_bytes": size_bytes,
        "sha256": sha256,
        "sha3_512": sha3,
        "blake2b_512": blake2,
        "torrent_url": torrent_filename,
        "magnet": magnet,
    }

    data_json_path = os.path.join(REPO_ROOT, "data.json")
    with open(data_json_path) as f:
        data = json.load(f)
    data["snapshots"].insert(0, entry)
    # Mirrors qbittorrent-nox's own retention (enforce_retention) so the
    # site listing never advertises a torrent that's no longer seeded.
    kept, retired = data["snapshots"][:RETENTION_COUNT], data["snapshots"][RETENTION_COUNT:]
    data["snapshots"] = kept
    data["schema_version"] = 1
    data["updated_utc"] = now
    with open(data_json_path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

    for r in retired:
        old_torrent = os.path.join(REPO_ROOT, r["torrent_url"])
        if os.path.exists(old_torrent):
            os.remove(old_torrent)

    latest_json_path = os.path.join(REPO_ROOT, "latest.json")
    with open(latest_json_path, "w") as f:
        json.dump({"updated_utc": now, "latest": archive_name,
                    "torrent_url": "latest.torrent"}, f, indent=2)
        f.write("\n")

    generate_feed(kept)

    _git("add", "-A").check_returncode()
    commit = _git("-c", f"user.name={config.GIT_AUTHOR_NAME}", "-c",
                   f"user.email={config.GIT_AUTHOR_EMAIL}", "commit", "-m",
                   f"Publish snapshot {archive_name}")
    if commit.returncode != 0:
        print(f"nothing to commit: {commit.stdout} {commit.stderr}")
        return
    _git("push").check_returncode()
    remote_url = _git("remote", "get-url", "origin").stdout.strip()
    print(f"published {archive_name} to {remote_url}")


def cleanup():
    # archive_path and the .torrent no longer live under temp_folder_path
    # by this point -- seed_torrent() already moved them into SEED_DIR.
    # This just clears the working directory (vacuum backup, data.ldb
    # copy, etc.) for the next run -- mirrors the old shell glob (`rm -rf
    # temp_folder_path*`): clears immediate contents (recursively for
    # subdirs), skips dotfiles, leaves temp_folder_path itself in place.
    with os.scandir(temp_folder_path) as entries:
        for entry in entries:
            if entry.name.startswith('.'):
                continue
            if entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path)
            else:
                os.remove(entry.path)


check_prerequisites()
node_service()
copy_live_to_temp()
print(datetime.datetime.utcnow().strftime("\n%Y-%m-%d %H:%M:%S"))
node_service('start')
bc, cemented = temp_path_actions()
print(datetime.datetime.utcnow().strftime("\n%Y-%m-%d %H:%M:%S"))
valid = validate_blocks()
print(datetime.datetime.utcnow().strftime("\n%Y-%m-%d %H:%M:%S"))
if not valid:
    print("something went wrong")
    exit(1)

size, size_bytes = generate_size_info()
cleanup_temp_ldb()
hash, sha256, sha3, blake2 = generate_hashes()
out = generate_final_string(bc, cemented, size, hash)
torrent_path = create_torrent()
seeded_path, infohash = seed_torrent(torrent_path)
publish_listing(seeded_path, infohash, bc, cemented, size_bytes, sha256, sha3, blake2)
cleanup()
exit(0)
