"""Run a backup self-audit only after a hosted runner allocation failure."""

import json
import os
import subprocess
from pathlib import Path

PRIMARY = ".github/workflows/uploader-watchdog.yml"
FAILED = {"failure", "cancelled", "timed_out"}


def gh_json(endpoint):
    result = subprocess.run(
        ["gh", "api", endpoint], capture_output=True, text=True,
        encoding="utf-8", timeout=45,
    )
    if result.returncode:
        raise RuntimeError("GitHub API request failed")
    return json.loads(result.stdout)


def should_retry(run, jobs):
    return (
        run.get("path") == PRIMARY
        and run.get("event") in {"schedule", "workflow_dispatch"}
        and run.get("conclusion") in FAILED
        and len(jobs) == 1
        and jobs[0].get("name") == "monitor"
        and jobs[0].get("conclusion") == "cancelled"
        and jobs[0].get("runner_id") in (None, 0)
        and not jobs[0].get("steps")
    )


def main():
    repository = os.environ["GITHUB_REPOSITORY"]
    source_id = os.environ["SOURCE_RUN_ID"]
    if not source_id.isdecimal():
        raise ValueError("Source run ID must be numeric")
    run = gh_json(f"repos/{repository}/actions/runs/{source_id}")
    if str(run.get("id")) != source_id or (run.get("head_repository") or {}).get("full_name") != repository:
        raise RuntimeError("Source run does not belong to this repository")
    jobs = gh_json(f"repos/{repository}/actions/runs/{source_id}/jobs?per_page=100")["jobs"]
    retry = should_retry(run, jobs)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"retry={'true' if retry else 'false'}\n")
    print("Backup audit required" if retry else "No runner-acquisition failure to retry")


if __name__ == "__main__":
    main()
