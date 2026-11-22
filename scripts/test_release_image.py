import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from release_image import promote, release_tag

SHA = "a" * 40
PACKAGE = "projects/project/locations/us/repositories/repo/packages/gateway"
DIGEST = "sha256:" + "b" * 64
UPSTREAM = "FROM ghcr.io/berriai/litellm-non_root:v1.84.4@sha256:abc\n"
RC = "litellm-1.84.4-gateway-1.0.0-rc.1"


class ReleaseTests(unittest.TestCase):
    @patch("release_image.subprocess.check_output", return_value=UPSTREAM)
    @patch("release_image.subprocess.run")
    def test_rc_uses_source_commit_upstream(self, run, output):
        self.assertEqual(release_tag(SHA, "1.0.0-rc.1"), RC)
        run.assert_called_once_with(
            ["git", "merge-base", "--is-ancestor", SHA, "origin/main"], check=True
        )
        output.assert_called_once_with(["git", "show", f"{SHA}:Dockerfile"], text=True)

    def test_stable_promotes_matching_rc(self):
        self.assertEqual(release_tag(RC, "1.0.0"), "litellm-1.84.4-gateway-1.0.0")

    def test_invalid_sources_and_versions(self):
        for source, version in [
            ("latest", "1.0.0-rc.1"),
            (SHA, "1.0.0"),
            (RC, "1.0.1"),
            (RC, "1.0.0-rc.2"),
            (SHA, "01.0.0-rc.1"),
            (SHA, "1.0.0-rc.0"),
            (SHA, "1.0.0;echo bad"),
        ]:
            with self.subTest(source=source, version=version):
                with self.assertRaises(ValueError):
                    release_tag(source, version)

    @patch("release_image.registry_request")
    def test_promote_creates_same_digest(self, request):
        request.side_effect = [
            {"version": f"{PACKAGE}/versions/{DIGEST}"},
            HTTPError("", 404, "missing", {}, None),
            {},
        ]
        self.assertEqual(promote(PACKAGE, SHA, RC, "token"), DIGEST)
        request.assert_called_with(
            f"{PACKAGE}/tags?tagId={RC}",
            "token",
            {"version": f"{PACKAGE}/versions/{DIGEST}"},
        )

    @patch("release_image.registry_request")
    def test_existing_tag_is_never_overwritten(self, request):
        request.side_effect = [{"version": f"{PACKAGE}/versions/{DIGEST}"}, {}]
        with self.assertRaisesRegex(ValueError, "already exists"):
            promote(PACKAGE, SHA, RC, "token")
        self.assertEqual(request.call_count, 2)

    @patch("release_image.registry_request")
    def test_dry_run_only_reads(self, request):
        request.side_effect = [
            {"version": f"{PACKAGE}/versions/{DIGEST}"},
            HTTPError("", 404, "missing", {}, None),
        ]
        self.assertEqual(promote(PACKAGE, SHA, RC, "token", dry_run=True), DIGEST)
        self.assertEqual(request.call_count, 2)

    @patch("release_image.registry_request")
    def test_permission_failure_does_not_create_tag(self, request):
        request.side_effect = [
            {"version": f"{PACKAGE}/versions/{DIGEST}"},
            HTTPError("", 403, "forbidden", {}, None),
        ]
        with self.assertRaises(HTTPError):
            promote(PACKAGE, SHA, RC, "token")
        self.assertEqual(request.call_count, 2)

    @patch("release_image.registry_request")
    def test_concurrent_creation_fails_without_update(self, request):
        request.side_effect = [
            {"version": f"{PACKAGE}/versions/{DIGEST}"},
            HTTPError("", 404, "missing", {}, None),
            HTTPError("", 409, "already exists", {}, None),
        ]
        with self.assertRaises(HTTPError):
            promote(PACKAGE, SHA, RC, "token")
        self.assertEqual(request.call_count, 3)

    @patch("release_image.registry_request")
    def test_missing_source_fails_without_writes(self, request):
        request.side_effect = HTTPError("", 404, "missing", {}, None)
        with self.assertRaises(HTTPError):
            promote(PACKAGE, SHA, RC, "token")
        self.assertEqual(request.call_count, 1)

    @patch("release_image.registry_request")
    def test_unexpected_source_digest_is_rejected(self, request):
        request.return_value = {"version": "another-package/versions/sha256:bad"}
        with self.assertRaises(ValueError):
            promote(PACKAGE, SHA, RC, "token")
        self.assertEqual(request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
