# AutoPortfolio

A developer portfolio rendered entirely from JSON. Day 1 of the build: the static site, the data schema, validation, and deployment. The AI pipeline (Days 2 onward) writes to the same JSON files through pull requests.

## Run locally

```bash
npm install
npm run dev        # http://localhost:5173
npm run check      # validate data + production build
```

## Where things live

| Path | Purpose |
| --- | --- |
| `src/data/projects.json` | All project records and their timelines. The pipeline edits this file. |
| `src/data/categories.json` | Fixed category list (id, name, description, color). |
| `src/data/profile.json` | Your name, bio, and contact links. Edit by hand. |
| `schema/project.schema.json` | JSON Schema for `projects.json`. |
| `scripts/validate-data.mjs` | Schema check plus cross-checks (see below). |
| `public/images/` | Generated project illustrations. |

## Data rules enforced by `npm run validate`

- Matches the JSON Schema (required fields, enums, URL and SHA formats)
- `primary_category` must be an ID from `categories.json`
- No duplicate project `id`, `repository_id`, or `repository_url`
- No duplicate commit in a project's timeline
- Image paths must point to files that exist in `public/`
- Timeline dates cannot predate `created_at`; `last_updated` cannot be older than the newest update

## Deploy to GitHub Pages

1. Push this repo to GitHub on the `main` branch.
2. Settings > Pages > Source: **GitHub Actions**.
3. Pushes to `main` run `.github/workflows/deploy.yml`, which validates, builds, and deploys.
4. Pull requests run `validate.yml` (validation + build) only.

The site uses a hash router and relative asset paths, so it works at any Pages URL without extra config.

## Project record fields

`repository_id` (GitHub's numeric ID) is the stable identity, so renames don't create duplicates. `last_analyzed_commit` is advanced only after an update passes validation. `confidence` and `needs_review` let low-confidence entries show an "Under review" badge. `evidence` ties claims to files. `status: "archived"` hides a project from the site without deleting its data.

## Replace the sample data

The four projects in `projects.json` are placeholders. Replace them with your own (or delete them and set `"projects": []`), and update `profile.json`.
