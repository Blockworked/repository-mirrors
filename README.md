# Repository mirrors

Automatic mirrors of [Blockworked](https://github.com/Blockworked) repositories on
[Codeberg](https://codeberg.org/Blockworked) and
[GitLab](https://gitlab.com/Blockworked).

GitHub is the source of truth. An hourly workflow discovers repositories, creates
missing destinations, and syncs branches, tags, and Git LFS objects. New repositories
are picked up automatically, including forks and archived projects.

## How it works

- Preserves each repository's public or private visibility when creating a mirror.
- Syncs branch and tag updates, including force pushes and deletions.
- Uploads LFS objects before publishing references to them.
- Checks destination ownership markers before updating existing repositories.
- Retains destination repositories when a source is deleted or renamed.
- Hides private repository names and their error details in workflow logs.

Mirrors are maintained copies. Please submit changes to the original GitHub
repository; commits made directly to a mirror may be overwritten.

## Configuration

The workflow runs at minute 23 of every hour and can also be started manually from
the [Actions tab](https://github.com/Blockworked/repository-mirrors/actions/workflows/mirror.yml).
Scheduled writes are enabled only when `MIRROR_ENABLED=true`.

| Secret | Purpose |
| --- | --- |
| `SOURCE_GITHUB_TOKEN` | Read access to all source repositories |
| `CODEBERG_TOKEN` | Create and update Codeberg repositories |
| `GITLAB_TOKEN` | Create and update GitLab projects |

| Variable | Default | Purpose |
| --- | --- | --- |
| `CODEBERG_OWNER` | `Blockworked` | Destination account or organization |
| `GITLAB_NAMESPACE` | `Blockworked` | Destination group or namespace |
| `EXCLUDE_REPOS` | Empty | Comma-separated repository names to skip |
| `MIRROR_ENABLED` | Disabled | Enable scheduled writes with `true` |

See the [operations guide](docs/operations.md) for credentials, initial setup,
branch protection requirements, and recovery behavior. Secrets can be configured
at repository level or inherited from the organization.

## Scope

This project mirrors Git branches, tags, and LFS objects. Issues, pull requests,
release downloads, wikis, packages, and repository settings require separate
backups. Submodule references are preserved; external submodule repositories need
their own mirrors.

Keep versioned backups alongside live mirrors to recover history after deletions
or force pushes. A visibility mismatch stops a destination sync; if a source
becomes private, make its existing mirrors private immediately.

## Development

Requires Python 3, Git, and Git LFS. Python dependencies are limited to the standard
library. The automation does not check out or execute mirrored repository code.

```sh
python3 mirror.py          # Preview accessible source repositories
python3 mirror.py --apply  # Create and update mirrors
python3 -m unittest discover -s tests -v
```

Export the secrets listed above before running locally. Preview mode makes no
destination changes. GitHub may delay scheduled jobs, so check the latest
successful run when freshness matters.
