"""Create a gateway release tag for an existing image, without rebuilding it."""

import json
import os
import re
import subprocess
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

VERSION = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
RC = rf"litellm-({VERSION})-gateway-({VERSION})-rc\.[1-9][0-9]*"


def release_tag(source, version):
    if not re.fullmatch(rf"{VERSION}(?:-rc\.[1-9][0-9]*)?", version):
        raise ValueError("Use a gateway version like 1.0.0 or 1.0.0-rc.1")
    if "-rc." in version:
        if not re.fullmatch(r"[0-9a-f]{40}", source):
            raise ValueError("An RC must come from a published full commit SHA")
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", source, "origin/main"], check=True
        )
        dockerfile = subprocess.check_output(
            ["git", "show", f"{source}:Dockerfile"], text=True
        )
        match = re.search(
            rf"^FROM ghcr\.io/berriai/litellm-non_root:v({VERSION})@sha256:",
            dockerfile,
            re.MULTILINE,
        )
        if not match:
            raise ValueError(
                "Source Dockerfile must pin a stable upstream LiteLLM version"
            )
        upstream = match[1]
    else:
        match = re.fullmatch(RC, source)
        if not match or match[2] != version:
            raise ValueError("A stable release must promote an RC of the same version")
        upstream = match[1]
    tag = f"litellm-{upstream}-gateway-{version}"
    if len(tag) > 128:
        raise ValueError("Release tag exceeds the Docker tag length limit")
    return tag


def registry_request(path, token, body=None):
    request = Request(
        f"https://artifactregistry.googleapis.com/v1/{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def promote(package, source, target, token, dry_run=False):
    # Resolve once, then create the new tag against that exact image version.
    version = registry_request(f"{package}/tags/{source}", token)["version"]
    if not re.fullmatch(re.escape(package) + r"/versions/sha256:[0-9a-f]{64}", version):
        raise ValueError("Source tag returned an unexpected image version")
    try:
        registry_request(f"{package}/tags/{target}", token)
    except HTTPError as error:
        if error.code != 404:
            raise
    else:
        raise ValueError(f"Release tag already exists: {target}")
    if not dry_run:
        # Use create, not update: a concurrent creator also causes a failure.
        registry_request(f"{package}/tags?tagId={target}", token, {"version": version})
    return version.rsplit("/", 1)[1]


def main():
    source, version = os.environ["SOURCE_TAG"], os.environ["GATEWAY_VERSION"]
    target = release_tag(source, version)
    package = (
        f"projects/{os.environ['GCP_PROJECT_ID']}/locations/{os.environ['GAR_LOCATION']}"
        f"/repositories/{os.environ['GAR_REPOSITORY']}/packages/{os.environ['GAR_NAME']}"
    )
    dry_run = os.environ.get("DRY_RUN") == "true"
    digest = promote(package, source, target, os.environ["ACCESS_TOKEN"], dry_run)
    summary = (
        f"{'Dry run' if dry_run else 'Published'}: `{target}`\n\n"
        f"Source: `{source}`\n\nDigest: `{digest}`\n"
    )
    print(summary)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as output:
            output.write(summary)


if __name__ == "__main__":
    main()
