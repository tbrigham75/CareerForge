# Backup and restore

Run `./scripts/backup.ps1` to create a timestamped ZIP in the local data directory's `backups` folder. Copy that ZIP and the encryption key in `.env` to secure storage; without the same key, stored provider secrets cannot be decrypted.

Restore is intentionally guarded: inspect the archive, stop CareerForge, then run `./scripts/restore.ps1 -Archive <path> -ConfirmRestore`. Restore extracts over the current data directory, so take a fresh backup first. Test restoration against an alternate `CAREERFORGE_DATA_DIR` before relying on it.
