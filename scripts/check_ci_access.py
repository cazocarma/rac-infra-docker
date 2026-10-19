"""Fail clearly before checkout when cross-repository CI access is unavailable."""
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

REPOSITORIES = ("rac-auth-service", "rac-user-service", "rac-match-service", "rac-frontend-flutter")


def check_access(environment, opener=urllib.request.urlopen):
    token = environment.get("REPO_READ_TOKEN", "").strip()
    if not token:
        return "Configure the Actions repository secret REPO_READ_TOKEN in rac-infra-docker: fine-grained token with Contents: read for the four companion repositories. The default GITHUB_TOKEN cannot read another private repository."
    branch = environment.get("GITHUB_BASE_REF") or environment.get("GITHUB_REF_NAME") or "main"
    for repository in REPOSITORIES:
        url = "https://api.github.com/repos/cazocarma/" + repository + "/git/ref/heads/" + urllib.parse.quote(branch, safe="")
        request = urllib.request.Request(url, headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "User-Agent": "RAC-CI-access-check",
        })
        try:
            with opener(request, timeout=15):
                pass
        except urllib.error.HTTPError as error:
            return f"REPO_READ_TOKEN cannot read cazocarma/{repository} branch {branch} (HTTP {error.code}). Check token expiration, selected repositories, Contents: read, and branch existence."
        except (OSError, urllib.error.URLError):
            return "GitHub API is unavailable while verifying companion repository access. Retry the workflow."
    return None


if __name__ == "__main__":
    error = check_access(os.environ)
    if error:
        print("::error::" + error, file=sys.stderr)
        raise SystemExit(1)
    print("PASS: token can read all companion repository branches")
