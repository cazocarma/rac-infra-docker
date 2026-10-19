"""Fail clearly before checkout when cross-repository CI access is unavailable."""
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

REPOSITORIES = ("rac-auth-service", "rac-user-service", "rac-match-service", "rac-frontend-flutter")


def app_configuration_error(environment):
    if not environment.get("RAC_CI_APP_CLIENT_ID", "").strip():
        return "Configure the Actions variable RAC_CI_APP_CLIENT_ID with the GitHub App Client ID. See docs/ci-acceso-repositorios.md."
    if not environment.get("RAC_CI_APP_PRIVATE_KEY", "").strip():
        return "Configure the Actions secret RAC_CI_APP_PRIVATE_KEY with the private key of the dedicated CI GitHub App. Never put this key in a variable or source file."
    return None


def check_access(environment, opener=urllib.request.urlopen):
    token = environment.get("CI_REPOSITORY_TOKEN", "").strip()
    if not token:
        return "Missing temporary CI_REPOSITORY_TOKEN. Check the preceding GitHub App token-generation step and App installation on the four companion repositories."
    branch = environment.get("GITHUB_BASE_REF") or environment.get("GITHUB_REF_NAME") or "main"
    owner = environment.get("GITHUB_REPOSITORY_OWNER") or "cazocarma"
    for repository in REPOSITORIES:
        url = "https://api.github.com/repos/" + urllib.parse.quote(owner, safe="") + "/" + repository + "/git/ref/heads/" + urllib.parse.quote(branch, safe="")
        request = urllib.request.Request(url, headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "User-Agent": "RAC-CI-access-check",
        })
        try:
            with opener(request, timeout=15):
                pass
        except urllib.error.HTTPError as error:
            return f"CI GitHub App token cannot read {owner}/{repository} branch {branch} (HTTP {error.code}). Check App installation, selected repositories, Contents: read, and branch existence."
        except (OSError, urllib.error.URLError):
            return "GitHub API is unavailable while verifying companion repository access. Retry the workflow."
    return None


if __name__ == "__main__":
    error = app_configuration_error(os.environ) if sys.argv[1:] == ["--app-config"] else check_access(os.environ)
    if error:
        print("::error::" + error, file=sys.stderr)
        raise SystemExit(1)
    print("PASS: CI authentication check passed")
