"""Daily self-monitor for the currently authorized cloud publishing workflows."""
import json
import os
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

PUBLISHERS = {
    "deviantart-auto-uploader": ["upload.yml"],
    "ameblo-auto-uploader": ["ameblo-post.yml"],
    "fc2-auto-uploader": ["fc2-post.yml"],
    "fc2-adult-auto-uploader": ["post.yml"],
    "hatena-auto-uploader": ["hatena-post.yml", "hatena-post-musclelove777.yml"],
}


def api(endpoint, method="GET"):
    r = subprocess.run(["gh", "api", "--method", method, endpoint],
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    if r.returncode:
        raise RuntimeError("GitHub API unavailable")
    return json.loads(r.stdout) if r.stdout.strip() else None


def main():
    repository = os.environ["GITHUB_REPOSITORY"]
    name = repository.split("/")[-1]
    now = datetime.now(timezone.utc)
    report = {"checked_at": now.isoformat(), "repository": repository,
              "repairs": [], "publishers": [], "issues": []}
    for workflow in PUBLISHERS[name]:
        row = {"workflow": workflow, "issues": []}
        try:
            endpoint = f"repos/{repository}/actions/workflows/{workflow}"
            definition = api(endpoint)
            row["observed_state"] = definition["state"]
            if definition["state"] != "active":
                api(endpoint + "/enable", "PUT")
                row["current_state"] = "active"
                report["repairs"].append("enabled:" + workflow)
            source = Path(".github/workflows") / workflow
            if not source.exists() or "schedule:" not in source.read_text(encoding="utf-8"):
                row["issues"].append("missing_publisher_schedule")
            runs = api(endpoint + "/runs?per_page=3")["workflow_runs"]
            latest = runs[0] if runs else None
            row["latest_run"] = ({k: latest.get(k) for k in
                                  ("id", "created_at", "status", "conclusion", "event")}
                                 if latest else None)
            if not latest:
                row["issues"].append("publisher_has_no_runs")
            elif latest["conclusion"] in {"failure", "timed_out", "cancelled", "action_required"}:
                row["issues"].append("publisher_failed")
            elif latest["status"] != "completed" and datetime.fromisoformat(
                    latest["created_at"].replace("Z", "+00:00")) < now - timedelta(hours=2):
                row["issues"].append("publisher_run_over_2h")
            elif datetime.fromisoformat(latest["created_at"].replace("Z", "+00:00")) < now - timedelta(hours=48):
                row["issues"].append("publisher_stale_48h")
        except Exception as error:
            row["issues"].append("audit_unavailable:" + type(error).__name__)
        report["publishers"].append(row)
    Path("cloud_guard_latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary = "# Daily publisher self-monitor\n\n" + json.dumps(report, indent=2)
    Path(os.environ.get("GITHUB_STEP_SUMMARY", "cloud_guard_summary.md")).write_text(summary, encoding="utf-8")
    print(summary)
    return int(any(row["issues"] for row in report["publishers"]))


if __name__ == "__main__":
    raise SystemExit(main())
