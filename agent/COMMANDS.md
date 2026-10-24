# AutoPortfolio command cheat sheet

Run everything from the project folder. Needs `GH_TOKEN`; commands that call Gemini also need `GEMINI_API_KEY`.
Every command that changes `src/data/projects.json` backs it up first and restores it if validation fails.

## Adding new repositories
```
python -m agent.collect status        where every public repo stands, and why
python -m agent.collect run           find new repos and collect their files
python -m agent.analyze run           write a portfolio entry for each (Gemini)
python -m agent.analyze show          read them
python -m agent.analyze apply         add them to projects.json
```

## New commits on existing projects (timeline)
```
python -m agent.track run             compare each project with its last-analyzed commit
python -m agent.track show
python -m agent.track apply
```

## Updating a project's description, features, tags, category (timeline is never touched)
```
python -m agent.refresh run --project ID     (or --stale, or --all)
python -m agent.refresh show                 before/after for every field
python -m agent.refresh apply                (--only description,tags  to take just some fields)
```
Fields you have locked are never changed. Fields you edit after a proposal is made are never overwritten.

## Editing and protecting your own wording
```
python -m agent.manage set ID description "Your wording"   (also: name, overview, category, tags, tech, status, demo_url)
python -m agent.manage pin ID description category          protect fields from refresh   (unpin to release; "all" works)
```
`set` locks the field automatically.

## Hiding, removing, undoing
```
python -m agent.manage list
python -m agent.manage hide ID        off the site, everything kept (reversible: unhide)
python -m agent.manage remove ID      deleted, and the repo is added to exclude_repos so it never returns
python -m agent.manage undo           restore the previous projects.json (repeat to step further back)
```

## Renamed, deleted or private repositories
```
python -m agent.sync run              compares GitHub with projects.json
python -m agent.sync show
python -m agent.sync apply            fixes renamed links; HIDES (never deletes) projects whose repo is gone
```

## After any apply
Commit and push `src/data/projects.json` (and `agent/settings.json` if `remove` changed it).
