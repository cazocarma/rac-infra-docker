import contextlib
import unittest
import urllib.error
from check_ci_access import check_access, REPOSITORIES


class AccessCheckTests(unittest.TestCase):
    def test_missing_secret_does_not_contact_github(self):
        def unexpected(*args, **kwargs):
            self.fail("empty token should not reach network")
        self.assertIn("Configure", check_access({}, unexpected))

    def test_checks_exact_read_refs_and_pr_base(self):
        seen = []
        def open_request(request, timeout):
            self.assertEqual(request.get_header("Authorization"), "Bearer fixture-token")
            self.assertEqual(timeout, 15)
            seen.append(request.full_url)
            return contextlib.nullcontext()
        result = check_access({"REPO_READ_TOKEN": "fixture-token", "GITHUB_BASE_REF": "main", "GITHUB_REF_NAME": "123/merge"}, open_request)
        self.assertIsNone(result)
        self.assertEqual(seen, [f"https://api.github.com/repos/cazocarma/{repo}/git/ref/heads/main" for repo in REPOSITORIES])

    def test_reports_denied_repository_without_response_or_token(self):
        def denied(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 404, "fixture-token", {}, None)
        result = check_access({"REPO_READ_TOKEN": "fixture-token"}, denied)
        self.assertIn("rac-auth-service", result)
        self.assertIn("404", result)
        self.assertNotIn("fixture-token", result)

    def test_reports_network_failure_without_credentials(self):
        def offline(request, timeout):
            raise urllib.error.URLError("fixture-token")
        result = check_access({"REPO_READ_TOKEN": "fixture-token"}, offline)
        self.assertIn("Retry", result)
        self.assertNotIn("fixture-token", result)


if __name__ == "__main__":
    unittest.main()
