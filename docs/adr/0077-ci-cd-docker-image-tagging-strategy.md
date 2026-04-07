# ADR 0077: CI/CD Docker Image Tagging Strategy

## Status
**Implemented**

## Context

The existing CI pipeline runs tests on pull requests (`ci-tests.yml`) but only builds and pushes Docker images when code is merged to main or a git tag is pushed (`build-and-push.yml`). The `latest` tag is updated on every merge to main, which conflates "latest code on main" with "latest stable release."

This creates three problems:

### 1. No PR-specific images
When a PR is opened, there is no way to deploy or test the exact build artifact from that PR in a staging environment. Reviewers must either trust the test suite or manually build the image locally.

### 2. `latest` is ambiguous
In Docker convention, `latest` typically implies "the most recent stable release." However, the current pipeline updates `latest` on every merge to main — including incomplete features, experimental changes, and work-in-progress code that happens to be merged. Production deployments pulling `:latest` get whatever was last merged, not necessarily a release-quality build.

### 3. No release workflow
There is no GitHub Release-based workflow. Version tags produce images, but there is no distinction between a tagged build and a formally released build.

---

## Decision

Restructure the CI/CD workflows into four distinct event-driven pipelines, each with a clear purpose and tagging strategy:

| Event | Workflow | Image Tags |
|-------|----------|------------|
| PR opened/updated | `ci.yml` | `pr-{N}`, `sha-{hash}` |
| Push to main | `build-and-push.yml` | `main`, `sha-{hash}` |
| Version tag pushed (`v*`) | `build-and-push.yml` | `{tag}`, `sha-{hash}` |
| GitHub Release published | `build-and-push.yml` | `{tag}`, `sha-{hash}`, `latest` |

### Key design choices

#### 1. PR images with `pr-N` tags
The `ci.yml` workflow (replacing `ci-tests.yml`) runs the full test suite and then builds and pushes a production image tagged `pr-{N}` (e.g., `pr-5`). This allows staging deployments of exact PR artifacts. The tag is overwritten on each push to the PR, so `pr-5` always points to the latest build of PR #5.

Fork PRs are excluded from the build step via an `if:` guard (`github.event.pull_request.head.repo.full_name == github.repository`) because fork `GITHUB_TOKEN`s lack write access to GHCR.

#### 2. `main` tag instead of `latest`
Pushes to main produce a `main` tag instead of `latest`. This clearly communicates "latest code on the default branch" without implying release stability.

#### 3. Release applies `latest` during build
When a GitHub Release is published, `build-and-push.yml` triggers via its `release: types: [published]` event. A job-level `if:` guard (`startsWith(github.event.release.tag_name, 'v')`) ensures only `v*`-tagged releases proceed — non-version releases are skipped entirely. The `docker/metadata-action` conditionally adds the `latest` tag when `github.event_name == 'release'`. This means the release build produces the version tag, `sha-{hash}`, and `latest` in a single build-and-push step — no separate workflow, no `crane` dependency, and no retry logic for race conditions.

#### 4. Version tag pattern: `v*`
The tag trigger is narrowed from `**` (any tag) to `v*` (version tags). This avoids accidental builds from non-version tags.

### Workflow files

- **`.github/workflows/tests.yml`** — Reusable workflow for backend (Django) and frontend (Vitest) tests. Role and job structure unchanged; action versions updated separately.
- **`.github/workflows/ci.yml`** — Replaces `ci-tests.yml`. Runs tests + builds/pushes `pr-N` images on PRs.
- **`.github/workflows/cleanup-pr-image.yml`** — New. Deletes `pr-N` images from GHCR when pull requests are closed or merged.
- **`.github/workflows/build-and-push.yml`** — Modified. Tags `main` on pushes to main; applies `latest` on GitHub Release events; triggers on `v*` tags.

### Production compose update
`docker-compose.prod.yml` is updated to reference `:main` instead of `:latest`, since `latest` is now only updated on releases.

---

## Consequences

### Positive
- PR authors and reviewers can deploy exact PR builds to staging (`pr-N`)
- `latest` has clear semantic meaning: the most recent GitHub Release
- `main` tag always reflects the current state of the default branch
- Release workflow is lightweight — no redundant rebuilds
- SHA tags on every build provide immutable references for debugging and rollback

### Negative
- PR images are automatically cleaned up by `cleanup-pr-image.yml` when PRs are closed or merged. However, orphaned `sha-{hash}` tags from PR builds are not pruned and may accumulate over time.
- Fork PRs cannot produce images (by design — fork tokens lack GHCR write access). Contributors from forks must rely on test results only.
- Release events trigger a full rebuild rather than a lightweight re-tag. This takes longer than a `crane tag` approach but eliminates the race condition and external dependency entirely. With GHA layer caching, the rebuild typically completes in under 2 minutes.
