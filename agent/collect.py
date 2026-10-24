"""Command line entry point.

  python -m agent.collect discover        report new/renamed/archived/missing repositories
  python -m agent.collect repo OWNER/NAME collect one repository (for testing)
  python -m agent.collect run             discover, then collect each new repository
  python -m agent.collect status          where every public repository stands, and why
  python -m agent.collect inspect [FILE]  human-readable view of collected bundles (no file contents)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from .discovery import discover
from .fetcher import SkipRepo, collect_repo
from .github_client import GitHubClient, GitHubError
from .log import setup_logging
from .report import render_summary
from .settings import OUT_DIR, PROJECTS_PATH, load_settings

log = logging.getLogger("agent.collect")


def _client() -> GitHubClient:
    return GitHubClient(token=os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"))


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", "utf-8")


def _collect_one(client, settings, full_name: str, out_dir: Path) -> dict:
    result = {"full_name": full_name}
    try:
        bundle = collect_repo(client, full_name, settings)
    except SkipRepo as skip:
        log.info("event=collect_skipped repo=%s reason=%s", full_name, skip.reason)
        return {**result, "status": "skipped", "detail": skip.reason}
    except GitHubError as exc:
        log.error("event=collect_failed repo=%s status=%s", full_name, exc.status)
        return {**result, "status": "error", "detail": f"GitHub API {exc.status}"}
    except Exception as exc:  # one bad repo must not stop the others
        log.error("event=collect_failed repo=%s error=%s", full_name, type(exc).__name__)
        return {**result, "status": "error", "detail": type(exc).__name__}

    # File name comes from the numeric id, never from repository-controlled text.
    path = out_dir / "bundles" / f"bundle-{bundle['repo']['id']}.json"
    _write_json(path, bundle)
    log.info("event=collected repo=%s files=%d warnings=%d", full_name, len(bundle["files"]), len(bundle["warnings"]))
    return {**result, "status": "collected", "files_read": len(bundle["files"]),
            "review_reasons": bundle["review_reasons"], "bundle": str(path.relative_to(out_dir))}


def _write_step_summary(markdown: str) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(markdown + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent.collect")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--strict", action="store_true", help="exit non-zero if any repository failed")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("discover")
    sub.add_parser("run")
    sub.add_parser("status")
    look = sub.add_parser("inspect")
    look.add_argument("file", nargs="?", type=Path, help="a bundle JSON file; default: every bundle in the output folder")
    one = sub.add_parser("repo")
    one.add_argument("full_name")
    args = parser.parse_args(argv)

    setup_logging()

    if args.command == "inspect":
        from .inspect_bundle import render_bundle
        files = [args.file] if args.file else sorted((args.out / "bundles").glob("bundle-*.json"))
        if not files:
            print(f"No bundles found in {args.out / 'bundles'}. Run `python -m agent.collect run` first.")
            return 1
        for path in files:
            print(render_bundle(json.loads(Path(path).read_text("utf-8"))))
        return 0

    settings = load_settings()
    client = _client()

    try:
        if args.command == "repo":
            result = _collect_one(client, settings, args.full_name, args.out)
            print(json.dumps(result, indent=2))
            return 0 if result["status"] != "error" else 1

        if args.command == "status":
            from .discovery import list_user_repos, load_projects
            from .status import build_status, render_status
            rows = build_status(list_user_repos(client, settings.github_username), load_projects(PROJECTS_PATH), args.out, settings)
            print(render_status(rows))
            return 0

        discovery = discover(client, settings, PROJECTS_PATH)
        _write_json(args.out / "discovery.json", discovery)

        results: list[dict] = []
        if args.command == "run":
            for repo in discovery["to_collect"]:
                results.append(_collect_one(client, settings, repo["full_name"], args.out))
        if results:   # remember outcomes so `status` can explain them later
            log_path = args.out / "collect_log.json"
            try:
                log_data = json.loads(log_path.read_text("utf-8"))
            except (OSError, ValueError):
                log_data = {}
            log_data.update({r["full_name"]: {"status": r["status"], "detail": r.get("detail", "")} for r in results})
            _write_json(log_path, log_data)
        summary = render_summary(discovery, results)
        (args.out / "summary.md").write_text(summary, "utf-8")
        _write_step_summary(summary)
        print(summary)
        failed = any(r["status"] == "error" for r in results)
        return 1 if (failed and args.strict) else 0
    except GitHubError as exc:
        log.error("event=run_failed status=%s message=%s", exc.status, exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
