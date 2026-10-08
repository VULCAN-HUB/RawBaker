# RawBaker update packages

The app queries public releases in `VULCAN-HUB/RawBaker` without authentication. Checks and downloads are initiated by the user. Stable builds exclude prereleases; Preview builds include them. Versions are compared numerically with prerelease ordering. Older versions are never offered as upgrades.

An eligible release must contain `rawbaker-update-v1.json` with the following schema. Values below are placeholders for the release build, not a usable feed.

```json
{
  "schema": 1,
  "app_id": "com.vulcanhub.rawbaker",
  "version": "0.27.0-editor-preview",
  "tag": "v0.27.0-editor-preview",
  "channel": "preview",
  "commit": "<40-character source commit>",
  "packages": [{
    "os": "windows",
    "arch": "x64",
    "kind": "portable-zip",
    "name": "RawBaker-Editor-0.27-Windows-x64.zip",
    "size": 123,
    "sha256": "<64-character SHA-256>"
  }]
}
```

The filename must exactly match an asset on the same release. Size and SHA-256 must match the final ZIP. The manifest version, tag, Preview flag and source commit must match the build. Publish new versions instead of replacing existing release assets. Source builds and macOS do not currently have a compatible update package; a newer release without a matching package is displayed as unavailable.

Downloads use HTTPS, accept only GitHub release download hosts, are stored separately from documents/settings, and are checked before becoming ready. Cancelled, incomplete and mismatched files are discarded. Hash verification does not provide an OS code signature. No updater credentials are shipped.

## Applying a downloaded ZIP

**Automatic installation/restart is not supported in this release.** The app opens the verified download's folder only. It never executes release scripts, extracts archives, overwrites a running executable, cancels editing/export work or closes the application for an update.

Save documents, finish exports, close RawBaker, extract the ZIP into a new folder and launch its executable. Retain existing documents, source photos and settings. Windows may show its normal unsigned-app warning; do not disable OS security features.

Version 0.25 does not contain an in-app updater. Its first upgrade is a manual download and extraction. Actual automatic installation and macOS installation have not been validated.
