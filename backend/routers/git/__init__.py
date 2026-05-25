"""
Git repository management routers.

This package contains routers for:
- Git repository CRUD operations
- Git operations (commit, push, pull)
- Git diff and comparison
- File operations in Git repositories
- Version control operations
- Git debugging utilities
"""

# Import the main consolidator router
from .main import router

# Export the main router (which includes all sub-routers)
__all__ = ["router"]
