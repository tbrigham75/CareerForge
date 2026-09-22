# Markdown and Git export

Markdown exports use stable UUID-bearing filenames and YAML front matter. An export includes only records that are approved, GitHub-export eligible, not soft-deleted, and `public_safe`, `private_personal`, or `internal`; `do_not_sync` and confidential records are excluded.

The current UI provides a dry-run manifest. The backend Git service supports safe status, diff, commit, and push primitives using no shell interpolation; commit and push reject calls without explicit confirmation. Before implementing a live sync profile, review destination path, changed files, diff, remote, branch, and sensitivity warnings.
