"""Reconcile an FC2 post receipt after only the ledger push failed."""

import base64
import json
import os
import re
import subprocess
from pathlib import PurePath

REPO = "MuscleLove-777/fc2-auto-uploader"
PUBLISHER = ".github/workflows/fc2-post.yml"
LEDGER = "uploaded_fc2.json"


def gh(*args, payload=None):
    command = ["gh", *args]
    if payload is not None:
        command += ["--input", "-"]
    result = subprocess.run(
        command, input=json.dumps(payload) if payload is not None else None,
        capture_output=True, text=True, encoding="utf-8", timeout=90,
    )
    if result.returncode:
        raise RuntimeError("GitHub request failed")
    return result.stdout


def eligible(run, jobs, branch):
    if (run.get("path") != PUBLISHER or run.get("conclusion") != "failure"
            or run.get("event") not in {"schedule", "workflow_dispatch"}
            or run.get("head_branch") != branch
            or (run.get("head_repository") or {}).get("full_name") != REPO
            or len(jobs) != 1):
        return False
    steps = jobs[0].get("steps") or []
    return (
        any(s.get("name", "").startswith("Run upload (attempt ")
            and s.get("conclusion") == "success" for s in steps)
        and any(s.get("name") == "Commit upload log"
                and s.get("conclusion") == "failure" for s in steps)
    )


def receipt_from_logs(logs):
    upload_lines = [line for line in logs.splitlines()
                    if "\tRun upload (attempt " in line]
    selected = re.findall(r"Selected: ([^\r\n]+\.(?:png|jpe?g|webp|gif))", "\n".join(upload_lines), re.I)
    created = re.findall(r"Post created! ID: (\d+)", "\n".join(upload_lines))
    success = re.findall(r"Success! Post ID: (\d+)", "\n".join(upload_lines))
    if (len(selected) != 1 or len(created) != 1 or len(success) != 1
            or created[0] != success[0]):
        raise RuntimeError("Post receipt is ambiguous")
    name = selected[0]
    if len(name) > 240 or PurePath(name).name != name or "\\" in name:
        raise RuntimeError("Post asset name is invalid")
    return name, success[0]


def main():
    if os.environ["GITHUB_REPOSITORY"] != REPO:
        raise RuntimeError("Unexpected repository")
    source_id = os.environ["SOURCE_RUN_ID"]
    if not source_id.isdecimal():
        raise ValueError("Source run ID must be numeric")
    repository = json.loads(gh("api", f"repos/{REPO}"))
    branch = repository["default_branch"]
    run = json.loads(gh("api", f"repos/{REPO}/actions/runs/{source_id}"))
    if str(run.get("id")) != source_id:
        raise RuntimeError("Source run ID mismatch")
    jobs = json.loads(gh("api", f"repos/{REPO}/actions/runs/{source_id}/jobs?per_page=100"))["jobs"]
    if not eligible(run, jobs, branch):
        print("No receipt repair required")
        return
    name, post_id = receipt_from_logs(gh("run", "view", source_id, "--repo", REPO, "--log"))
    content = json.loads(gh("api", f"repos/{REPO}/contents/{LEDGER}?ref={branch}"))
    ledger = json.loads(base64.b64decode(content["content"]).decode("utf-8"))
    if not isinstance(ledger, list) or not all(isinstance(item, str) for item in ledger):
        raise RuntimeError("Unexpected ledger format")
    if name in ledger:
        print("Published asset already recorded")
        return
    ledger.append(name)
    encoded = base64.b64encode((json.dumps(ledger, ensure_ascii=False, indent=2) + "\n").encode("utf-8")).decode("ascii")
    gh("api", "--method", "PUT", f"repos/{REPO}/contents/{LEDGER}", payload={
        "message": f"repair: record already published FC2 entry {post_id} [skip ci]",
        "content": encoded, "sha": content["sha"], "branch": branch,
    })
    print(f"Recorded existing post ID {post_id}; no publisher dispatch")


if __name__ == "__main__":
    main()
