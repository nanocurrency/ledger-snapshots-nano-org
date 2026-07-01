# data.json schema

Rewritten in full by `snapshot.py`'s `publish_listing()` (snap-gni.18) each
snapshot cycle -- not hand-edited. `index.html` and `feed.xml` are both
generated from this file's contents.

```jsonc
{
  "schema_version": 1,
  "updated_utc": "2026-07-01T12:00:00Z",   // when this file was last regenerated
  "snapshots": [
    {
      "name": "Nano_64_2026_07_01_12.7z",
      "created_utc": "2026-07-01T12:00:00Z",
      "block_count": 123456789,
      "cemented_block_count": 123456700,
      "size_bytes": 61234567890,
      "sha256": "...",
      "sha3_512": "...",
      "blake2b_512": "...",
      "torrent_url": "Nano_64_2026_07_01_12.7z.torrent",   // relative to site root
      "magnet": "magnet:?xt=urn:btih:...&dn=Nano_64_2026_07_01_12.7z&tr=..."
    }
    // newest first; length matches RETENTION_COUNT in snapshot.py
  ]
}
```

`latest.json` mirrors `snapshots[0]` plus a stable filename:

```jsonc
{
  "updated_utc": "2026-07-01T12:00:00Z",
  "latest": "Nano_64_2026_07_01_12.7z",
  "torrent_url": "latest.torrent"   // always the newest .torrent, same content each cycle, stable filename
}
```

`latest.torrent` is a copy of the newest snapshot's `.torrent` file under a
stable filename, so casual downloaders and RSS auto-download rules can
always point at the same URL rather than needing to track the dated
filename.
