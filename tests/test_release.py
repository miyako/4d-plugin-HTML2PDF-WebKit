import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release", ROOT / "scripts/release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
SHA = "a" * 40


class VersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "HTML2PDF").mkdir()
        for path in ("VERSION", "HTML2PDF/CMakeLists.txt", "HTML2PDF/Info.plist.in"):
            shutil.copyfile(ROOT / path, self.root / path)
        self.expected = (ROOT / "VERSION").read_text().strip()

    def test_live_coordinated_version(self):
        self.assertEqual(release.version(self.root), self.expected)

    def test_invalid_versions(self):
        for value in ("", "1.2", "v1.2.3", "01.2.3", "1.2.03", "1.2.3.4",
                      "1.2.3-beta", "1.2.3+build", " 1.2.3\n", "1.2.3\n\n",
                      "1.2.3\n4.5.6", "-1.2.3"):
            with self.subTest(value=value):
                (self.root / "VERSION").write_text(value)
                with self.assertRaises(ValueError):
                    release.version(self.root)

    def test_bump_modes_change_only_version(self):
        original = {p: p.read_bytes() for p in (self.root / "HTML2PDF").iterdir()}
        for mode, index in (("major", 0), ("minor", 1), ("patch", 2)):
            with self.subTest(mode=mode):
                (self.root / "VERSION").write_text(self.expected + "\n")
                parts = list(map(int, self.expected.split(".")))
                parts[index] += 1
                parts[index + 1:] = [0] * (2 - index)
                expected = ".".join(map(str, parts))
                self.assertEqual(release.bump(mode, self.root), expected)
                self.assertEqual(release.version(self.root), expected)
                for path, content in original.items():
                    self.assertEqual(path.read_bytes(), content)

    def test_cmake_drift(self):
        path = self.root / "HTML2PDF/CMakeLists.txt"
        original = path.read_text()
        for old in (
            'file(READ "${CMAKE_CURRENT_SOURCE_DIR}/../VERSION" PROJECT_VERSION_STRING)',
            'project(HTML2PDF VERSION ${PROJECT_VERSION_STRING} LANGUAGES C CXX)',
            'MACOSX_BUNDLE_BUNDLE_VERSION "${PROJECT_VERSION}"',
            'MACOSX_BUNDLE_SHORT_VERSION_STRING "${PROJECT_VERSION}"',
        ):
            with self.subTest(binding=old):
                path.write_text(original.replace(old, old.replace("VERSION", "DRIFT")))
                with self.assertRaises(ValueError):
                    release.version(self.root)
        path.write_text(original + '\nset(PROJECT_VERSION "9.9.9")\n')
        with self.assertRaises(ValueError):
            release.version(self.root)

    def test_plist_drift(self):
        path = self.root / "HTML2PDF/Info.plist.in"
        original = path.read_text()
        for placeholder in ("${MACOSX_BUNDLE_SHORT_VERSION_STRING}",
                            "${MACOSX_BUNDLE_BUNDLE_VERSION}"):
            path.write_text(original.replace(placeholder, "9.9.9"))
            with self.assertRaises(ValueError):
                release.version(self.root)

    def test_invalid_bump_does_not_write(self):
        original = (self.root / "VERSION").read_bytes()
        with self.assertRaises(ValueError):
            release.bump("invalid", self.root)
        self.assertEqual((self.root / "VERSION").read_bytes(), original)


class AvailabilityTests(unittest.TestCase):
    def test_unused_version(self):
        with patch.object(release, "git", return_value=""), \
                patch.object(release, "api", side_effect=[{}, None]) as api:
            release.available("v1.2.3")
            self.assertEqual(api.call_args_list[-1].args, ("/releases/tags/v1.2.3",))

    def test_existing_tag_including_annotated(self):
        for refs in (f"{SHA}\trefs/tags/v1.2.3", f"{SHA}\trefs/tags/v1.2.3^{{}}"):
            with patch.object(release, "git", return_value=refs), \
                    patch.object(release, "api") as api:
                with self.assertRaisesRegex(ValueError, "Tag .* already exists"):
                    release.available("v1.2.3")
                api.assert_not_called()

    def test_existing_release(self):
        with patch.object(release, "git", return_value=""), \
                patch.object(release, "api", side_effect=[{}, {"id": 42}]):
            with self.assertRaisesRegex(ValueError, "Release .* already exists"):
                release.available("v1.2.3")

    def test_git_failure_is_not_absence(self):
        with patch.object(release, "git", side_effect=subprocess.CalledProcessError(128, "git")):
            with self.assertRaises(subprocess.CalledProcessError):
                release.available("v1.2.3")

    def test_api_only_release_404_means_absent(self):
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo", "GH_TOKEN": "fixture"}):
            for status in (401, 403, 404, 429, 500):
                for missing_ok in (False, True):
                    with self.subTest(status=status, missing_ok=missing_ok):
                        error = urllib.error.HTTPError("url", status, "fixture", {}, None)
                        with patch.object(release.urllib.request, "urlopen", side_effect=error):
                            if status == 404 and missing_ok:
                                self.assertIsNone(release.api("/releases/tags/v1.2.3", True))
                            else:
                                with self.assertRaises(urllib.error.HTTPError):
                                    release.api("", missing_ok)

    def test_api_network_and_malformed_response_fail(self):
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo", "GH_TOKEN": "fixture"}):
            for error in (urllib.error.URLError("offline"), TimeoutError("timeout")):
                with patch.object(release.urllib.request, "urlopen", side_effect=error):
                    with self.assertRaises(type(error)):
                        release.api("/releases/tags/v1.2.3", True)
            with patch.object(release.urllib.request, "urlopen") as opener:
                opener.return_value.__enter__.return_value = io.BytesIO(b"invalid")
                with self.assertRaises(json.JSONDecodeError):
                    release.api("")
            with patch.object(release.urllib.request, "urlopen") as opener:
                opener.return_value.__enter__.return_value = io.BytesIO(b"null")
                with self.assertRaises(ValueError):
                    release.api("")

    def test_repository_failure_blocks_absence(self):
        with patch.object(release, "git", return_value=""), \
                patch.object(release, "api", side_effect=urllib.error.URLError("offline")):
            with self.assertRaises(urllib.error.URLError):
                release.available("v1.2.3")

    def test_selected_sha(self):
        with patch.object(release, "git", return_value=SHA):
            release.selected(SHA)
            for sha in ("main", "v1.2.3", "a" * 39, "b" * 40):
                with self.assertRaises(ValueError):
                    release.selected(sha)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.value = release.version()
        self.tag = f"v{self.value}"
        for extension in ("zip", "dmg"):
            (self.root / f"HTML2PDF-{self.value}.{extension}").write_bytes(b"fixture")
        for name, value in (("ROOT", self.root), ("version", lambda: self.value)):
            mock = patch.object(release, name, value)
            mock.start()
            self.addCleanup(mock.stop)

    def test_create_only_exact_sha_and_assets(self):
        with patch.object(release, "selected") as selected, \
                patch.object(release, "available") as available, \
                patch.object(release, "no_release") as no_release, \
                patch.object(release, "git", side_effect=["", f"{SHA}\trefs/tags/{self.tag}"]) as git, \
                patch.object(release.subprocess, "run") as run:
            release.publish(SHA)
            selected.assert_called_once_with(SHA)
            available.assert_called_once_with(self.tag)
            no_release.assert_called_once_with(self.tag)
            self.assertEqual(git.call_args_list[0].args, (
                "-c", "push.followTags=false", "push", "--no-follow-tags",
                "origin", f"{SHA}:refs/tags/{self.tag}"))
            command = run.call_args.args[0]
            self.assertEqual(command[:8], ["gh", "release", "create", self.tag,
                                          "--verify-tag", "--title", self.tag, "--generate-notes"])
            self.assertEqual(command[8:], [str(self.root / f"HTML2PDF-{self.value}.{ext}")
                                          for ext in ("zip", "dmg")])
            self.assertTrue(run.call_args.kwargs["check"])

    def test_recheck_blocks_tag_push(self):
        with patch.object(release, "selected"), \
                patch.object(release, "available", side_effect=ValueError("already exists")), \
                patch.object(release, "git") as git:
            with self.assertRaises(ValueError):
                release.publish(SHA)
            git.assert_not_called()

    def test_no_release_after_tag_race(self):
        with patch.object(release, "selected"), patch.object(release, "available"), \
                patch.object(release, "git", side_effect=subprocess.CalledProcessError(1, "push")), \
                patch("sys.stderr", new_callable=io.StringIO), \
                patch.object(release.subprocess, "run") as run:
            with self.assertRaises(subprocess.CalledProcessError):
                release.publish(SHA)
            run.assert_not_called()

    def test_partial_publication_is_explicit(self):
        with patch.object(release, "selected"), patch.object(release, "available"), \
                patch.object(release, "git", return_value=""), \
                patch.object(release, "no_release", side_effect=ValueError("API failed")), \
                patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(ValueError):
                release.publish(SHA)
            self.assertIn("PARTIAL PUBLICATION", stderr.getvalue())

    def test_missing_asset_blocks_publication(self):
        (self.root / f"HTML2PDF-{self.value}.dmg").unlink()
        with patch.object(release, "selected"), patch.object(release, "available") as available:
            with self.assertRaisesRegex(ValueError, "Missing or empty"):
                release.publish(SHA)
            available.assert_not_called()


class GitRaceTests(unittest.TestCase):
    def test_nonforced_branch_push_and_create_only_tag(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "remote.git"
            work = root / "work"

            def git(*args):
                return subprocess.check_output(
                    ["git", *args], cwd=work, text=True, stderr=subprocess.PIPE).strip()

            subprocess.run(["git", "init", "--bare", str(remote)], check=True,
                           capture_output=True)
            subprocess.run(["git", "clone", str(remote), str(work)], check=True,
                           capture_output=True)
            git("config", "user.name", "Fixture")
            git("config", "user.email", "fixture@example.invalid")
            git("config", "push.followTags", "true")
            git("checkout", "-b", "selected")
            (work / "VERSION").write_text("1.2.3\n")
            git("add", "VERSION")
            git("commit", "-m", "selected")
            selected = git("rev-parse", "HEAD")
            git("push", "origin", "HEAD:refs/heads/selected")
            git("tag", "-a", "known-build", "-m", "preserve")
            git("commit", "--allow-empty", "-m", "concurrent update")
            newer = git("rev-parse", "HEAD")
            git("push", "--no-follow-tags", "origin", "HEAD:refs/heads/selected")
            with self.assertRaises(subprocess.CalledProcessError):
                git("-c", "push.followTags=false", "push", "--no-follow-tags",
                    "origin", f"{selected}:refs/heads/selected")
            self.assertEqual(git("ls-remote", "origin", "refs/heads/selected"),
                             f"{newer}\trefs/heads/selected")
            git("-c", "push.followTags=false", "push", "--no-follow-tags",
                "origin", f"{selected}:refs/tags/v1.2.3")
            with self.assertRaises(subprocess.CalledProcessError):
                git("-c", "push.followTags=false", "push", "--no-follow-tags",
                    "origin", f"{newer}:refs/tags/v1.2.3")
            self.assertEqual(git("ls-remote", "--tags", "origin"),
                             f"{selected}\trefs/tags/v1.2.3")
            self.assertEqual(git("rev-parse", "known-build^{}"), selected)


class WorkflowTests(unittest.TestCase):
    def test_zero_input_manual_immutable_build(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text()
        self.assertTrue(workflow.startswith("name: Build\n"))
        trigger = workflow.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertEqual(trigger.strip(), "workflow_dispatch:")
        self.assertNotIn("inputs.", workflow)
        self.assertNotIn("needs.version.outputs.tag", workflow)
        self.assertEqual(workflow.count("uses: actions/checkout@v4"), 3)
        self.assertEqual(workflow.count("ref: ${{ github.sha }}"), 3)
        self.assertIn("group: release-publication\n", workflow)
        self.assertIn("cancel-in-progress: false", workflow)

    def test_publication_requires_all_build_and_verification_steps(self):
        workflow = (ROOT / ".github/workflows/release.yml").read_text()
        self.assertIn("needs: [version, build-windows]", workflow)
        self.assertIn("python3 -m unittest discover -s tests -v", workflow)
        self.assertIn('scripts/release.py check --sha "$GITHUB_SHA"', workflow)
        positions = [workflow.index(step) for step in (
            "name: build macOS plugin", "name: verify universal binary",
            "name: merge Windows binaries", "name: codesign",
            "codesign --verify", "name: package, notarize & staple",
            'result.get("status") != "Accepted"', 'xcrun stapler validate "$DMG_PATH"',
            "name: tag selected commit and create new release")]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("continue-on-error:", workflow)
        self.assertNotIn("always()", workflow)
        self.assertEqual(workflow.count("scripts/release.py publish"), 1)

    def test_bump_only_pushes_selected_branch_without_tags(self):
        workflow = (ROOT / ".github/workflows/bump-version.yml").read_text()
        for mode in ("patch", "minor", "major"):
            self.assertIn(f"          - {mode}\n", workflow)
        self.assertIn("ref: ${{ github.sha }}", workflow)
        self.assertIn('scripts/release.py bump --mode "$MODE"', workflow)
        self.assertIn('git add VERSION\n', workflow)
        self.assertIn('git -c push.followTags=false push --no-follow-tags origin '
                      '"HEAD:refs/heads/${GITHUB_REF_NAME}"', workflow)
        for forbidden in ("git tag", "--force", "gh release", "workflow run"):
            self.assertNotIn(forbidden, workflow)

    @unittest.skipIf(os.environ.get("RELEASE_BUMP_FIXTURE") == "1", "inside bumped fixture")
    def test_entire_suite_survives_temporary_copy_bump(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ("scripts", "tests", ".github"):
                shutil.copytree(ROOT / folder, root / folder, ignore=shutil.ignore_patterns("__pycache__"))
            (root / "HTML2PDF").mkdir()
            for path in ("VERSION", "HTML2PDF/CMakeLists.txt", "HTML2PDF/Info.plist.in"):
                shutil.copyfile(ROOT / path, root / path)
            before = (root / "VERSION").read_text().strip()
            after = release.bump("patch", root)
            self.assertNotEqual(before, after)
            result = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                cwd=root, env={**os.environ, "RELEASE_BUMP_FIXTURE": "1"},
                text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
