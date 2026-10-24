# Operations

One dedicated GitHub Actions repository discovers accessible repositories in the
Blockworked GitHub organization every hour and mirrors their branches, tags and
Git LFS objects to Codeberg and GitLab. Newly created repositories are discovered
on the next run. Forks and archived source repositories are included.

## Setup

1. Create the `Blockworked` organization on Codeberg and the `Blockworked` group
   on GitLab, or obtain permission to create repositories inside them. The script
   creates repositories, not organizations or groups. Check Codeberg's hosting
   policies for the repositories you intend to mirror.
2. Use a dedicated GitHub repository, such as
   `Blockworked/repository-mirrors`. Copy this project's contents into its default
   branch, including the hidden `.github` folder. Protect that branch and restrict
   who can edit the workflow: it has access to organization source code and
   destination write credentials.
3. Under **Settings → Secrets and variables → Actions**, add repository secrets:

   | Secret | Access needed |
   | --- | --- |
   | `SOURCE_GITHUB_TOKEN` | A fine-grained GitHub token owned/approved by Blockworked, repository access **All repositories**, **Contents: Read-only** and Metadata read. Authorize organization access as required. This includes new repositories later. The workflow's built-in `GITHUB_TOKEN` cannot read every private organization repository. |
   | `CODEBERG_TOKEN` | A token for a Codeberg user allowed to create and push repositories in Blockworked. Repository read/write scope (`write:repository`) and user read scope (`read:user`), or the equivalents offered by Codeberg, and access to public and private repositories if needed. |
   | `GITLAB_TOKEN` | A GitLab personal or suitable group access token with `api` and `write_repository` scope, and a role allowed to create projects and push branches in the Blockworked group. |

   Keep tokens in Secrets, never in source files or chat. Set token expiry reminders.
4. Optional Actions variables: `CODEBERG_OWNER` and `GITLAB_NAMESPACE` both default
   to `Blockworked`. `EXCLUDE_REPOS` accepts exact, comma-separated source names
   without spaces, for example `large-assets,temporary-experiment`.
5. Open **Actions → Mirror Blockworked repositories → Run workflow**. Leave
   **Create and update destination repositories** unchecked to preview the source
   inventory. Private repository names are hidden in logs; verify token access in
   GitHub's token settings. A token with
   incomplete access can silently omit repositories; the script cannot detect
   repositories GitHub does not reveal to it.
6. Run again with that option checked. This creates destinations and pushes data.
   Review the successful run and open sample repositories on both destinations.
7. Set Actions variable **`MIRROR_ENABLED`** to **`true`** to enable hourly writes.
   Scheduled runs use minute 23 of each hour (UTC); GitHub can delay or drop
   scheduled jobs. The workflow must be on the default branch. Keep GitHub Actions
   failure notifications enabled and periodically check the latest success.

You can exclude `repository-mirrors` itself if you do not want it mirrored.
No credentials are committed to it; secrets are not part of Git history.

## Behavior and recovery

- New destination repositories inherit source public/private visibility. Existing
  visibility mismatches stop syncing that destination rather than changing its
  visibility automatically. **If a public source becomes private, make its mirrors
  private immediately yourself**; an hourly job cannot undo prior public exposure.
- Every managed destination has description `Managed GitHub mirror: repository ID N`.
  An existing repository with a different description is rejected. This avoids
  accidentally overwriting unrelated projects. To adopt an existing mirror, first
  verify its contents are disposable and set its description to that exact marker
  using the source repository's numeric GitHub ID. Keep the marker unchanged.
- Pushes replace diverged branches/tags and remove deleted branches/tags. Do not
  develop in destination repositories. Pull request refs and other host-specific
  refs are excluded intentionally.
- GitLab may automatically protect the default branch. Enable force pushes for
  the mirror identity in the dedicated destination's branch rules if you require
  force-push replication. Other branch/tag protections and group rules may also
  reject updates or deletion. The job reports failures; it does not remove those
  protections automatically. GitLab CI is disabled on projects this script creates.
  For a selected managed mirror, the manual workflow's `allow_default_force_push`
  option can enable force pushes on its exact default branch. It preserves push
  access levels and refuses inherited protection rules. This option requires a
  repository selection and is off during ordinary scheduled runs.
- Git LFS objects are fetched and uploaded before branch/tag refs. Destination
  LFS quotas or unsupported storage cause a failed run rather than silently
  claiming a successful mirror. Each run downloads fresh repositories and LFS
  data; account for bandwidth and runner storage for large collections.
- Empty repositories get empty destinations. Source deletions do not delete
  destination repositories. Renames create a new destination name and retain the
  old copy. Archived source repositories are copied into writable destinations.
  Archived destinations cause a failure until unarchived.
- A repository or destination failure does not stop attempts for other repositories
  and destinations; the job ultimately fails so the problem is visible. The next
  hourly run retries the complete sync. Initial credential/namespace failures stop
  the run before repository syncing.

## Scope

This is live Git mirroring, not a complete or historical GitHub backup. It does
not copy issues, PR conversations, releases/assets, wiki repositories, discussions,
packages, Actions data, settings or secrets. Submodule references are copied, but
external submodule repositories need their own mirrors. Keep separate versioned
backups because mirrored deletion and force pushes can remove older reachable history.

## Run outside Actions

Install Python 3, Git and Git LFS; export the three token variables above, then:

```sh
python3 mirror.py          # Source inventory only; no destination API calls
python3 mirror.py --apply  # Provision and sync
python3 -m unittest discover -s tests -v
```

Schedule only one instance at a time. The included Actions workflow serializes runs.
The automation never checks out or executes source repository code.

References:

- [Codeberg mirroring guidance](https://docs.codeberg.org/getting-started/faq/)
- [GitLab projects API](https://docs.gitlab.com/api/projects/)
- [GitLab namespaces API](https://docs.gitlab.com/api/namespaces/)
- [GitHub repository duplication](https://docs.github.com/en/repositories/creating-and-managing-repositories/duplicating-a-repository)
- [GitHub Actions schedules](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
