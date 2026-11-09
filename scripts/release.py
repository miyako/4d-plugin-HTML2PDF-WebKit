#!/usr/bin/env python3
"""Version coordination and create-only publication for the manual workflows."""

import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
SEMVER = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"


def version(root=ROOT):
    value = (root / "VERSION").read_text()
    if not re.fullmatch(SEMVER + r"\n?", value):
        raise ValueError("VERSION must contain exactly a canonical X.Y.Z")
    value = value.rstrip("\n")
    cmake = (root / "HTML2PDF/CMakeLists.txt").read_text()
    bindings = (
        'file(READ "${CMAKE_CURRENT_SOURCE_DIR}/../VERSION" PROJECT_VERSION_STRING)',
        'string(STRIP "${PROJECT_VERSION_STRING}" PROJECT_VERSION_STRING)',
        'project(HTML2PDF VERSION ${PROJECT_VERSION_STRING} LANGUAGES C CXX)',
        'MACOSX_BUNDLE_INFO_PLIST "${CMAKE_CURRENT_SOURCE_DIR}/Info.plist.in"',
        'MACOSX_BUNDLE_BUNDLE_VERSION "${PROJECT_VERSION}"',
        'MACOSX_BUNDLE_SHORT_VERSION_STRING "${PROJECT_VERSION}"',
    )
    for binding in bindings:
        if cmake.count(binding) != 1:
            raise ValueError(f"Version source drift in CMake: {binding}")
    # Reject extra assignments that could override the coordinated source.
    for key in ("PROJECT_VERSION_STRING", "PROJECT_VERSION",
                "MACOSX_BUNDLE_BUNDLE_VERSION", "MACOSX_BUNDLE_SHORT_VERSION_STRING"):
        assignments = re.findall(r"(?:set|string|file)\s*\([^)]*\b" + key + r"\b[^)]*\)",
                                 cmake, re.IGNORECASE)
        expected = 2 if key == "PROJECT_VERSION_STRING" else 0
        if len(assignments) != expected:
            raise ValueError(f"Unexpected version assignment: {key}")
    with (root / "HTML2PDF/Info.plist.in").open("rb") as stream:
        info = plistlib.load(stream)
    for key, expected in (
        ("CFBundleVersion", "${MACOSX_BUNDLE_BUNDLE_VERSION}"),
        ("CFBundleShortVersionString", "${MACOSX_BUNDLE_SHORT_VERSION_STRING}"),
    ):
        if info.get(key) != expected:
            raise ValueError(f"Version source drift in Info.plist.in: {key}")
    return value


def bump(mode, root=ROOT):
    current = version(root)
    parts = [int(part) for part in current.split(".")]
    index = ("major", "minor", "patch").index(mode)
    parts[index] += 1
    parts[index + 1:] = [0] * (2 - index)
    updated = ".".join(map(str, parts))
    (root / "VERSION").write_text(updated + "\n")
    return version(root)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def api(path, missing_ok=False):
    request = urllib.request.Request(
        f"https://api.github.com/repos/{os.environ['GITHUB_REPOSITORY']}{path}",
        headers={"Authorization": f"Bearer {os.environ['GH_TOKEN']}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
            if not isinstance(result, dict):
                raise ValueError(f"Unexpected GitHub API response for {path or 'repository'}")
            return result
    except urllib.error.HTTPError as error:
        if error.code == 404 and missing_ok:
            return None
        raise


def no_release(tag):
    # A missing/inaccessible repository must not masquerade as an unused version.
    api("")
    if api(f"/releases/tags/{tag}", missing_ok=True) is not None:
        raise ValueError(f"Release {tag} already exists; refusing to overwrite")


def available(tag):
    refs = git("ls-remote", "--tags", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}")
    if refs:
        raise ValueError(f"Tag {tag} already exists; refusing to overwrite")
    no_release(tag)


def selected(sha):
    if not re.fullmatch(r"[0-9a-f]{40}", sha) or git("rev-parse", "HEAD") != sha:
        raise ValueError("Checkout must match the immutable selected github.sha")


def publish(sha):
    selected(sha)
    value = version()
    tag = f"v{value}"
    assets = [ROOT / f"HTML2PDF-{value}.{extension}" for extension in ("zip", "dmg")]
    for asset in assets:
        if not asset.is_file() or asset.stat().st_size == 0:
            raise ValueError(f"Missing or empty release asset: {asset.name}")
    available(tag)
    try:
        git("-c", "push.followTags=false", "push", "--no-follow-tags",
            "origin", f"{sha}:refs/tags/{tag}")
        no_release(tag)
        if git("ls-remote", "--tags", "origin", f"refs/tags/{tag}") != f"{sha}\trefs/tags/{tag}":
            raise ValueError("Published tag no longer points at the selected SHA")
        subprocess.run(["gh", "release", "create", tag, "--verify-tag", "--title", tag,
                        "--generate-notes", *map(str, assets)], cwd=ROOT, check=True)
    except (OSError, ValueError, subprocess.SubprocessError):
        print(f"PARTIAL PUBLICATION: {tag} may have been pushed at {sha}. Inspect the tag, release "
              "and assets manually; do not delete, overwrite or retry Build. "
              "See README recovery instructions.", file=sys.stderr)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("version", "bump", "check", "publish"))
    parser.add_argument("--mode", choices=("patch", "minor", "major"))
    parser.add_argument("--sha")
    args = parser.parse_args()
    if args.command == "bump":
        if not args.mode:
            parser.error("bump requires --mode")
        print(bump(args.mode))
    elif args.command in ("check", "publish"):
        if not args.sha:
            parser.error(f"{args.command} requires --sha")
        if args.command == "publish":
            publish(args.sha)
        else:
            selected(args.sha)
            value = version()
            available(f"v{value}")
            print(value)
    else:
        print(version())


if __name__ == "__main__":
    main()
