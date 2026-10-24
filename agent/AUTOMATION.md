# Turning on the GitHub automation

One-time setup on github.com (portfolio repo):

1. Settings > Secrets and variables > Actions > **Secrets** > New repository secret
   Name `GEMINI_API_KEY`, value = your key.
2. Settings > Actions > General > Workflow permissions: choose **Read and write permissions**, and tick
   **Allow GitHub Actions to create and approve pull requests**. Save.
3. Push the workflow (`.github/workflows/agent.yml`) and the `agent` folder to `main`.

First run (changes nothing):
4. Actions tab > **Portfolio agent** > Run workflow > leave **dry_run** ticked. Open the run and read the log.

Second run (opens a pull request):
5. Run workflow again with **dry_run** unticked. A pull request called "Portfolio update" appears. Read it, then merge.
   Merging publishes the site through the existing deploy workflow.

Switch it on:
6. Settings > Secrets and variables > Actions > **Variables** > `AUTOMATION_ENABLED` = `true`.
   It then runs daily. Set it to `false` to pause (manual runs still work).

Good to know
- Only one pull request is open at a time. While it waits, scheduled runs skip; merge or close it to continue.
- The PR page will not show the "Validate portfolio data" check (GitHub does not run other workflows for pull requests
  opened by the built-in token). The agent workflow runs the same validation itself before opening the PR.
- If a run fails, GitHub emails you. Failed stages retry on the next run because nothing advances unless it validated.
- Things that need you: descriptions marked out of date (`python -m agent.refresh run --project ID`) and any proposal
  flagged for suspicious text. The PR description lists them.
