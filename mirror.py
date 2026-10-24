#!/usr/bin/env python3
"""Discover GitHub organization repositories and push branches, tags and LFS."""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request


def quoted(value):
    return urllib.parse.quote(str(value), safe="")


def repo_label(repo):
    # Workflow logs are public when the automation repository is public.
    return "[private repository]" if repo["private"] else repo["full_name"]


def failure_message(repo, error):
    if isinstance(error, GitError):
        return str(error)
    return "Sync failed; check destination access, visibility, protections and quotas" if repo["private"] else str(error)


class GitError(RuntimeError):
    """Diagnostics from a fixed vocabulary, safe for public logs."""


def git_failure_reason(stderr):
    text = stderr.lower()
    for needles, reason in [
        (("protected branch", "protected tag"), "destination branch or tag protection rejected the update"),
        (("429", "too many requests", "rate limit"), "host rate limit reached"),
        (("authentication failed", "could not read username", "could not read password", "401"), "Git authentication failed"),
        (("403", "access denied", "not allowed to push"), "destination denied write access"),
        (("repository not found", "does not exist", "404"), "repository unavailable to this credential"),
        (("shallow update",), "destination rejected shallow history"),
        (("remote hung up", "rpc failed", "early eof", "http/2", "502", "503"), "Git transport or host failure"),
        (("pre-receive hook declined",), "destination policy rejected the update"),
        (("couldn't find remote ref", "src refspec"), "requested Git reference is missing"),
    ]:
        if any(needle in text for needle in needles):
            return reason
    return "check permissions, quotas and branch protections"


class API:
    def __init__(self, root, token, scheme="Bearer"):
        self.root = root
        self.token = token
        self.scheme = scheme

    def call(self, path, method="GET", data=None, missing_ok=False):
        request = urllib.request.Request(
            self.root + path,
            data=None if data is None else json.dumps(data).encode(),
            method=method,
            headers={"Authorization": f"{self.scheme} {self.token}",
                     "Content-Type": "application/json", "User-Agent": "Blockworked-mirrors"},
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                body = response.read()
                return json.loads(body) if body else None
        except urllib.error.HTTPError as error:
            if missing_ok and error.code == 404:
                return None
            raise RuntimeError(f"{method} {self.root}{path}: HTTP {error.code}") from None

    def pages(self, path):
        page = 1
        while True:
            rows = self.call(f"{path}{'&' if '?' in path else '?'}per_page=100&page={page}")
            yield from rows
            if len(rows) < 100:
                break
            page += 1


def git_env(host, username, token):
    env = os.environ.copy()
    basic = base64.b64encode(f"{username}:{token}".encode()).decode()
    settings = {
        f"http.https://{host}/.extraHeader": f"Authorization: Basic {basic}",
        "credential.helper": "",
        "core.hooksPath": "/dev/null",
        "protocol.file.allow": "never",
    }
    env["GIT_CONFIG_COUNT"] = str(len(settings))
    for i, (key, value) in enumerate(settings.items()):
        env[f"GIT_CONFIG_KEY_{i}"] = key
        env[f"GIT_CONFIG_VALUE_{i}"] = value
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_LFS_SKIP_SMUDGE"] = "1"
    return env


def run_git(args, env, cwd=None):
    result = subprocess.run(["git", *args], env=env, cwd=cwd,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3600)
    if result.returncode:
        # Git/LFS diagnostics can contain credentials or remote-controlled text.
        reason = git_failure_reason(result.stderr.decode(errors="replace"))
        raise GitError(f"git {args[0]} failed (exit {result.returncode}): {reason}")
    return result.stdout.decode()


def check_destination(repo, marker, private, host):
    if repo.get("description") != marker:
        raise RuntimeError(f"{host}: existing repository is not managed by this automation; refusing overwrite")
    actual_private = repo.get("private") if host == "Codeberg" else repo.get("visibility") == "private"
    if actual_private != private:
        raise RuntimeError(f"{host}: visibility mismatch; fix destination visibility before syncing")
    if repo.get("archived"):
        raise RuntimeError(f"{host}: destination is archived; unarchive it before syncing")


class Destinations:
    def __init__(self):
        self.owner = os.environ.get("CODEBERG_OWNER") or "Blockworked"
        self.namespace = os.environ.get("GITLAB_NAMESPACE") or "Blockworked"
        self.cb = API("https://codeberg.org/api/v1", os.environ["CODEBERG_TOKEN"], "token")
        self.gl = API("https://gitlab.com/api/v4", os.environ["GITLAB_TOKEN"])
        self.cb_user = self.cb.call("/user")["login"]
        self.ns = self.gl.call("/namespaces/" + quoted(self.namespace))
        if self.ns["full_path"].lower() != self.namespace.lower():
            raise RuntimeError("GitLab namespace does not match configuration")

    def ensure(self, host, source, marker):
        name, private = source["name"], source["private"]
        if host == "Codeberg":
            path = f"/repos/{quoted(self.owner)}/{quoted(name)}"
            repo = self.cb.call(path, missing_ok=True)
            if repo is None:
                create = "/user/repos" if self.owner.lower() == self.cb_user.lower() else f"/orgs/{quoted(self.owner)}/repos"
                repo = self.cb.call(create, "POST", {
                    "name": name, "description": marker, "private": private,
                    "auto_init": False,
                })
            check_destination(repo, marker, private, host)
            url = f"https://codeberg.org/{self.owner}/{name}.git"
            env = git_env("codeberg.org", self.cb_user, os.environ["CODEBERG_TOKEN"])
        else:
            path = "/projects/" + quoted(f"{self.namespace}/{name}")
            repo = self.gl.call(path, missing_ok=True)
            if repo is None:
                repo = self.gl.call("/projects", "POST", {
                    "name": name, "path": name, "namespace_id": self.ns["id"],
                    "description": marker, "visibility": "private" if private else "public",
                    "initialize_with_readme": False, "builds_access_level": "disabled",
                })
            check_destination(repo, marker, private, host)
            url = f"https://gitlab.com/{self.namespace}/{name}.git"
            env = git_env("gitlab.com", "oauth2", os.environ["GITLAB_TOKEN"])
        return url, env, repo

    def default_branch(self, host, repo, branch):
        if not branch or repo.get("default_branch") == branch:
            return
        if host == "Codeberg":
            self.cb.call(f"/repos/{quoted(self.owner)}/{quoted(repo['name'])}", "PATCH", {"default_branch": branch})
        else:
            self.gl.call(f"/projects/{repo['id']}", "PUT", {"default_branch": branch})

    def allow_default_force_push(self, repo, branch):
        if not branch:
            return
        path = f"/projects/{repo['id']}/protected_branches/{quoted(branch)}"
        protection = self.gl.call(path, missing_ok=True)
        if protection and not protection.get("allow_force_push"):
            if protection.get("inherited"):
                raise RuntimeError("Inherited branch protection requires group administrator configuration")
            self.gl.call(path, "PATCH", {"allow_force_push": True})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Create destinations and push; otherwise list only")
    parser.add_argument("--repo", help="Limit this run to one exact source repository name")
    parser.add_argument("--allow-default-force-push", action="store_true", help="Allow force pushes on the selected managed GitLab mirror's default branch")
    args = parser.parse_args()
    if args.allow_default_force_push and not args.repo:
        raise RuntimeError("Force-push configuration requires selecting one repository")
    org = os.environ.get("SOURCE_ORG", "Blockworked")
    token = os.environ.get("SOURCE_GITHUB_TOKEN")
    if not token:
        raise RuntimeError("Set SOURCE_GITHUB_TOKEN (GitHub organization read access)")
    gh = API("https://api.github.com", token)
    repos = list(gh.pages(f"/orgs/{quoted(org)}/repos?type=all"))
    # Fetch the full list successfully before making any destination mutations.
    repos = sorted(repos, key=lambda r: r["name"].lower())
    excluded = set(filter(None, os.environ.get("EXCLUDE_REPOS", "").split(",")))
    repos = [r for r in repos if r["name"] not in excluded]
    if args.repo:
        repos = [r for r in repos if r["name"] == args.repo]
        if not repos:
            raise RuntimeError("Requested repository is excluded or not accessible")
    print(f"Discovered {len(repos)} accessible repositories in {org}", flush=True)
    if not args.apply:
        for repo in repos:
            print(f"PLAN {repo_label(repo)} ({'private' if repo['private'] else 'public'}) -> Codeberg + GitLab")
        print("No destination changes. This plan does not validate destination access.")
        return 0
    if subprocess.run(["git", "lfs", "version"], capture_output=True).returncode:
        raise RuntimeError("Install Git LFS before applying")
    targets = Destinations()
    source_env = git_env("github.com", "x-access-token", token)
    failures = []
    for repo in repos:
        print(f"Syncing {repo_label(repo)}", flush=True)
        try:
            with tempfile.TemporaryDirectory(prefix="blockworked-mirror-") as temp:
                bare = str(Path(temp) / "repo.git")
                source_url = f"https://github.com/{org}/{repo['name']}.git"
                run_git(["init", "--bare", bare], source_env)
                run_git(["remote", "add", "origin", source_url], source_env, bare)
                run_git(["fetch", "--prune", "origin", "+refs/heads/*:refs/heads/*", "+refs/tags/*:refs/tags/*"], source_env, bare)
                has_refs = run_git(["for-each-ref", "--format=%(refname)", "refs/heads", "refs/tags"], source_env, bare).strip()
                if has_refs:
                    run_git(["lfs", "fetch", "--all", "origin"], source_env, bare)
                marker = f"Managed GitHub mirror: repository ID {repo['id']}"
                for host in ("Codeberg", "GitLab"):
                    try:
                        url, env, destination = targets.ensure(host, repo, marker)
                        if host == "GitLab" and args.allow_default_force_push:
                            targets.allow_default_force_push(destination, repo["default_branch"])
                        if not run_git(["for-each-ref", "--format=%(refname)", "refs/heads", "refs/tags"], source_env, bare).strip():
                            print(f"  OK {host}: empty source, destination provisioned; no refs pushed", flush=True)
                            continue
                        # Upload large files first, so refs do not point to missing LFS objects.
                        run_git(["lfs", "push", "--all", url], env, bare)
                        # Mirror portable refs only; GitHub PR refs are host-specific.
                        # First populate branches, set the default, then prune old branches.
                        run_git(["push", url, "+refs/heads/*:refs/heads/*", "+refs/tags/*:refs/tags/*"], env, bare)
                        has_branch = run_git(["for-each-ref", "--format=%(refname)", "refs/heads"], source_env, bare).strip()
                        if has_branch:
                            targets.default_branch(host, destination, repo["default_branch"])
                        run_git(["push", "--prune", url, "+refs/heads/*:refs/heads/*", "+refs/tags/*:refs/tags/*"], env, bare)
                        print(f"  OK {host}", flush=True)
                    except Exception as error:
                        failures.append(f"{repo_label(repo)} -> {host}: {failure_message(repo, error)}")
                        print("FAILED " + failures[-1], file=sys.stderr, flush=True)
        except Exception as error:
            failures.append(f"{repo_label(repo)}: {failure_message(repo, error)}")
            print("FAILED " + failures[-1], file=sys.stderr, flush=True)
    for failure in failures:
        print("FAILED " + failure, file=sys.stderr)
    print(f"Finished: {len(failures)} failed operations", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
