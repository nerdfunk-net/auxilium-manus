from __future__ import annotations


def get_config() -> dict:
    return {
        # The Cisco ACI source (APIC) to back up, and the git repository to write to.
        "aci_source_id": "",
        "git_repository_id": None,
        # Folder in the repository, one fabric per folder (tenants/ and access-policies.json).
        "repository_subdirectory": "aci",
        # Tenants to back up; empty = every tenant of the fabric.
        "tenants": [],
        "include_access_policies": True,
        # Commit the changes; push the commit (needs commit).
        "commit": True,
        "push": False,
        # {source_id} is replaced by the ACI source id.
        "commit_message": "ACI configuration backup of {source_id}",
        # Run metadata entry "<node id>.<output_key>" holds the result.
        "output_key": "aci_backup",
    }
