def get_config() -> dict:
    return {
        "credential_reference": "",
        # "fixed" → use credential_reference above. "run_param" → use the
        # credential vault name held in the run parameter named by
        # credential_param (a workflow static_attribute of type "reference",
        # ref_kind "credential"), resolved per triggering user.
        "credential_source": "fixed",
        "credential_param": "",
        "config_format": "both",
    }
