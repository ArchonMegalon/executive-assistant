# EA Core product boundary

EA Core is the executive-assistant control plane. The Memorial product is owned by its standalone repository and runtime; EA Core must not contain or mount its application routes, voice profiles, source ingestion, release gates, deployment overlays, or operator studio.

## Runtime contract

- EA Core serves its office loop and system health endpoints independently.
- The former `/memorials` and `/api/memorials` route families return `404` from EA Core.
- The Docker image is built only from `ea/app`, the locked Python dependencies, and the EA LTD inventory.
- Every deployed response carries `X-EA-Source-Revision` when the image was built with an immutable 40-character revision.
- No source or data directory is symlinked between the two repositories.

Historical product data in older EA revisions remains recoverable from Git and from the operator's preserved pre-split worktree. It is not copied into, mounted by, or served from the EA Core image. Product migrations belong to the standalone product repository and require their own explicit import receipt.

## Local verification

Build the root `Dockerfile` with `--build-arg EA_SOURCE_REVISION=<sha>`, publish port `8090`, then verify `/`, `/healthz`, the revision header, and `404` responses for the retired route families. The standalone repository materializes the cross-repository closeout receipt against this running image.
