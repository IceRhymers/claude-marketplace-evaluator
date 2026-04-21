---
name: submit-pr
description: Submit a pull request on GitHub for the current working branch
allowed-tools:
  - Bash
  - Read
---

Push the current branch to the remote repository and open a pull request for review. Verifies uncommitted changes are committed, then uses the GitHub CLI to create and return a PR link.
