"""Every request model rejects unknown fields (Q7). Shrink LEGACY_LENIENT; never grow it.

To convert a domain: add ``model_config = ConfigDict(extra="forbid")`` to its request models,
delete their names below, then check the frontend payload for that domain (compare the keys the
UI sends with the model) and run that flow in the browser.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

from pydantic import BaseModel

import models

SUFFIXES = ("Request", "Create", "Update")

LEGACY_LENIENT: set[str] = {
    "models.attribute_path.AttributePathResolveRequest",
    "models.auth.LoginRequest",
    "models.auth.OIDCCallbackRequest",
    "models.auth.OIDCTestLoginRequest",
    "models.batfish.BatfishBgpFactsQueryRequest",
    "models.batfish.BatfishExtractFactsQueryRequest",
    "models.batfish.BatfishGenericQueryRequest",
    "models.batfish.BatfishInterfacePropertiesQueryRequest",
    "models.batfish.BatfishNodePropertiesQueryRequest",
    "models.batfish.BatfishOspfFactsQueryRequest",
    "models.batfish.BatfishReachabilityQueryRequest",
    "models.batfish.BatfishRoutesQueryRequest",
    "models.batfish.BatfishSourceCreateRequest",
    "models.batfish.BatfishSourceUpdateRequest",
    "models.batfish.BatfishTestConnectionRequest",
    "models.batfish.BatfishTestFiltersQueryRequest",
    "models.catalyst_center.CatalystCenterDevicePreviewRequest",
    "models.catalyst_center.CatalystCenterSourceCreateRequest",
    "models.catalyst_center.CatalystCenterSourceUpdateRequest",
    "models.catalyst_center.CatalystCenterTestConnectionRequest",
    "models.certificates.AddCertificateRequest",
    "models.change_requests.ChangeRequestApproveRequest",
    "models.change_requests.ChangeRequestRejectRequest",
    "models.crypto_attribute.DecryptAttributeTestRequest",
    "models.crypto_attribute.EncryptAttributeTestRequest",
    "models.git.GitBranchRequest",
    "models.git.GitCommitRequest",
    "models.git_repositories.GitConnectionTestRequest",
    "models.git_repositories.GitRepositoryRequest",
    "models.git_repositories.GitRepositoryUpdateRequest",
    "models.git_repositories.GitSyncRequest",
    "models.ise.ISEDeviceGroupChildCreateRequest",
    "models.ise.ISEDeviceGroupRootCreateRequest",
    "models.ise.ISEDeviceGroupUpdateRequest",
    "models.ise.ISELocationCreateRequest",
    "models.ise.ISENetworkDeviceCreate",
    "models.ise.ISENetworkDeviceUpdate",
    "models.ise.ISESourceCreateRequest",
    "models.ise.ISESourceUpdateRequest",
    "models.ise.ISETestConnectionRequest",
    "models.mattermost.MattermostSourceCreateRequest",
    "models.mattermost.MattermostSourceUpdateRequest",
    "models.mattermost.MattermostTestConnectionRequest",
    "models.netmiko.NetmikoGetConfigsRequest",
    "models.netmiko.NetmikoRunCommandsRequest",
    "models.pyats.PyATSSourceCreateRequest",
    "models.pyats.PyATSSourceUpdateRequest",
    "models.pyats.PyATSTestConnectionRequest",
    "models.rbac.PermissionCreate",
    "models.rbac.RoleCreate",
    "models.rbac.RoleUpdate",
    "models.runs.WorkflowRunCreate",
    "models.schedules.WorkflowScheduleCreate",
    "models.schedules.WorkflowScheduleUpdate",
    "models.settings.SettingCreate",
    "models.settings.SettingUpdate",
    "models.sources_nautobot.CreateInventoryRequest",
    "models.sources_nautobot.DeviceAttributesRequest",
    "models.sources_nautobot.DeviceDetailsRequest",
    "models.sources_nautobot.DeviceIdsPreviewRequest",
    "models.sources_nautobot.DeviceSearchRequest",
    "models.sources_nautobot.ImportInventoryRequest",
    "models.sources_nautobot.InventoryPreviewRequest",
    "models.sources_nautobot.NautobotObjectResolveRequest",
    "models.sources_nautobot.NautobotTestConnectionRequest",
    "models.sources_nautobot.RenameGroupRequest",
    "models.sources_nautobot.UpdateInventoryRequest",
    "models.templates.ParseStructuredRequest",
    "models.templates.TemplateCreate",
    "models.templates.TemplateRenderRequest",
    "models.templates.TemplateUpdate",
    "models.update_attribute.UpdateAttributeProbeDeviceRequest",
    "models.update_attribute.UpdateAttributeProbeRequest",
    "models.update_content.UpdateContentProbeRequest",
    "models.user_preferences.DashboardLayoutUpdate",
    "models.workflow_ai_session.WorkflowAiSessionEnableRequest",
    "models.workflow_validation.WorkflowValidateRequest",
    "models.workflows.WorkflowCreate",
    "models.workflows.WorkflowGitDiffRequest",
    "models.workflows.WorkflowGitRestoreRequest",
    "models.workflows.WorkflowNotesUpdate",
    "models.workflows.WorkflowUpdate",
}


def _request_models():
    for info in pkgutil.iter_modules(models.__path__):
        module = importlib.import_module(f"models.{info.name}")
        for name, cls in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(cls, BaseModel)
                and cls.__module__ == module.__name__
                and name.endswith(SUFFIXES)
            ):
                yield f"{module.__name__}.{name}", cls


def test_request_models_forbid_extra() -> None:
    lenient = {key for key, cls in _request_models() if cls.model_config.get("extra") != "forbid"}
    assert lenient == LEGACY_LENIENT, sorted(lenient ^ LEGACY_LENIENT)
