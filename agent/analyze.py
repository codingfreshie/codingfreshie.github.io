"""Gemini analysis step.

  python -m agent.analyze models   list models your API key can use
  python -m agent.analyze run      analyze each collected bundle and write a draft (--force to redo, --limit N)
  python -m agent.analyze show     readable view of the drafts
  python -m agent.analyze apply    merge drafts into src/data/projects.json (validated; restored on failure)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .analysis import validate_analysis
from .apply import apply_drafts
from .draft import build_project
from .gemini import AnalysisError, GeminiClient, ValidationFailed
from .log import setup_logging
from .prompts import SYSTEM, build_user_prompt
from .schemas import response_schema
from .settings import OUT_DIR, PROJECTS_PATH, ROOT, Settings, load_settings
from .show_draft import render_draft

log = logging.getLogger("agent.analyze")
CATEGORIES_PATH = ROOT / "src" / "data" / "categories.json"


def load_categories() -> list[dict]:
    return json.loads(CATEGORIES_PATH.read_text("utf-8"))["categories"]


def analyze_bundle(gemini: GeminiClient, bundle: dict, categories: list[dict], taken_ids: set[str],
                   settings: Settings, attempts: int = 2) -> dict:
    ids = [c["id"] for c in categories]
    schema = response_schema(ids)
    feedback, last = None, None
    for _ in range(attempts):
        raw = gemini.generate_json(SYSTEM, build_user_prompt(bundle, categories, feedback), schema)
        try:
            cleaned, dropped = validate_analysis(raw, bundle, ids)
        except ValidationFailed as exc:
            feedback, last = str(exc), exc
            log.warning("event=validation_failed repo=%s reason=%s", bundle["repo"]["full_name"], exc)
            continue
        return build_project(bundle, cleaned, dropped, taken_ids, settings.min_confidence, gemini.model,
                         settings.ambiguity_max_confidence)
    raise last


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", "utf-8")


def _drafts(out: Path) -> list[dict]:
    return [json.loads(p.read_text("utf-8")) for p in sorted((out / "drafts").glob("draft-*.json"))]


def cmd_run(args, settings: Settings) -> int:
    bundles = sorted((args.out / "bundles").glob("bundle-*.json"))
    if not bundles:
        print(f"No bundles in {args.out / 'bundles'}. Run `python -m agent.collect run` first.")
        return 1
    projects = json.loads(PROJECTS_PATH.read_text("utf-8"))["projects"]
    done_repos = {p["repository_id"] for p in projects}
    taken = {p["id"] for p in projects} | {d["project"]["id"] for d in _drafts(args.out)}
    categories = load_categories()
    gemini = GeminiClient(settings.gemini_model, min_interval=settings.min_seconds_between_calls)

    made, failed, count = [], [], 0
    in_portfolio, has_draft, excluded = [], [], []
    for path in bundles:
        bundle = json.loads(path.read_text("utf-8"))
        rid, name = bundle["repo"]["id"], bundle["repo"]["full_name"]
        draft_path = args.out / "drafts" / f"draft-{rid}.json"
        if settings.is_excluded(name):
            excluded.append(name)
            continue
        if rid in done_repos:
            in_portfolio.append(name)
            continue
        if draft_path.exists() and not args.force:
            has_draft.append(name)
            continue
        if args.limit and count >= args.limit:
            break
        count += 1
        try:
            draft = analyze_bundle(gemini, bundle, categories, taken, settings)
        except AnalysisError as exc:
            log.error("event=analysis_failed repo=%s error=%s", name, exc)
            failed.append((name, str(exc)))
            if "rate limit" in str(exc).lower() or "not found for this key" in str(exc) or "GEMINI_API_KEY" in str(exc):
                break   # no point trying the rest
            continue
        taken.add(draft["project"]["id"])
        _write(draft_path, draft)
        made.append(draft)
        log.info("event=analyzed repo=%s category=%s confidence=%s review=%s", name,
                 draft["project"]["primary_category"], draft["project"]["confidence"], draft["project"]["needs_review"])

    log_path = args.out / "analysis_log.json"
    try:
        log_data = json.loads(log_path.read_text("utf-8"))
    except (OSError, ValueError):
        log_data = {}
    for d in made:
        log_data.pop(d["project"].get("repository_url", "").replace("https://github.com/", ""), None)
    log_data.update({name: err[:200] for name, err in failed})
    _write(log_path, log_data)

    print(f"\nDrafts written: {len(made)}   failed: {len(failed)}")
    for d in made:
        p = d["project"]
        print(f"  {p['name']:<40} {p['primary_category']:<22} conf {p['confidence']:<5} "
              f"{'REVIEW: ' + ', '.join(d['notes']['review_reasons']) if p['needs_review'] else 'ok'}")
    for name, err in failed:
        print(f"  FAILED {name}: {err}")
    if in_portfolio:
        print(f"\nSkipped {len(in_portfolio)} already in src/data/projects.json (--force does not apply to these; "
              f"remove them from that file to re-analyze): {', '.join(in_portfolio)}")
    if excluded:
        print(f"\nSkipped {len(excluded)} listed in exclude_repos: {', '.join(excluded)}")
    if has_draft:
        print(f"\nSkipped {len(has_draft)} that already have drafts (use --force to redo): {', '.join(has_draft)}")
    print("\nNext: `python -m agent.analyze show` to read them, then `python -m agent.analyze apply`.")
    return 1 if failed and not made else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent.analyze")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--force", action="store_true")
    run.add_argument("--limit", type=int, default=0)
    sub.add_parser("models")
    sub.add_parser("show")
    sub.add_parser("apply")
    args = parser.parse_args(argv)
    setup_logging()

    try:
        if args.command == "show":
            drafts = _drafts(args.out)
            if not drafts:
                print("No drafts yet. Run `python -m agent.analyze run`.")
                return 1
            print("\n".join(render_draft(d) for d in drafts))
            return 0
        if args.command == "apply":
            result = apply_drafts(args.out / "drafts", PROJECTS_PATH, is_excluded=load_settings().is_excluded)
            if not result["ok"]:
                print("Validation failed, so projects.json was left unchanged:\n" + result["output"])
                return 1
            print(f"Added {len(result['added'])}: {', '.join(result['added']) or '-'}   already present: {len(result['skipped'])}"
                  f"   excluded: {len(result['excluded'])}")
            if result["added"]:
                print("Run `npm run dev` to see them on the site.")
            return 0

        settings = load_settings()
        if args.command == "models":
            for name in GeminiClient(settings.gemini_model).list_models():
                print(name)
            return 0
        return cmd_run(args, settings)
    except AnalysisError as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
