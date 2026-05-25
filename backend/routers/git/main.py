"""
Consolidated Git router for repository management and version control operations.
This router combines all Git-related functionality with clean API structure:

- /api/git-repositories/    - Repository management (CRUD operations)
- /api/git/{repo_id}/       - Single repository operations (sync, branches, commits, files)
- /api/git-repositories/{repo_id}/debug/ - Debug and diagnostic operations

Refactored from a monolithic 1,790-line file into 5 focused modules:
- git_repositories.py: Repository CRUD operations
- git_operations.py: Repository sync and status operations
- git_version_control.py: Git VCS operations (branches, commits, diffs)
- git_files.py: File operations within repositories
- git_debug.py: Debug and diagnostic endpoints

Note: The git_compare.py module (cross-repository comparisons) has been removed as
it was only used by the deprecated /compare feature.
"""

from fastapi import APIRouter

from routers.git.debug import router as debug_router
from routers.git.files import router as files_router
from routers.git.operations import router as operations_router

# Import all Git sub-routers from new feature-based structure
from routers.git.repositories import router as repositories_router
from routers.git.version_control import router as version_control_router

# Create main router that will include all sub-routers
router = APIRouter()

# Include all Git sub-routers with clean API structure
router.include_router(repositories_router)  # /api/git-repositories/
router.include_router(operations_router)  # /api/git/{repo_id}/
router.include_router(version_control_router)  # /api/git/{repo_id}/
router.include_router(files_router)  # /api/git/{repo_id}/
router.include_router(debug_router)  # /api/git-repositories/{repo_id}/debug/
