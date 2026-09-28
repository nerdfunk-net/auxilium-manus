import type {
  NautobotUuidResolution,
  NautobotUuidResourceType,
} from "@/components/features/workflow-steps/shared/nautobot-field-rows";
import type { NautobotJobVariable } from "@/hooks/queries/use-nautobot-job-variables-query";

// Mirrors backend's services/nautobot/devices/uuid_resolver.py::OBJECTVAR_MODEL_TO_RESOURCE_TYPE.
const OBJECTVAR_MODEL_TO_RESOURCE_TYPE: Record<string, NautobotUuidResourceType> = {
  "dcim.location": "location",
  "dcim.device": "device",
  "dcim.platform": "platform",
  "dcim.rack": "rack",
  "dcim.devicetype": "device_type",
  "extras.role": "role",
  "extras.status": "status",
  "ipam.namespace": "namespace",
};

const OBJECT_VAR_TYPES = new Set(["ObjectVar", "MultiObjectVar"]);

function guessContentType(name: string): string {
  return name.toLowerCase().includes("interface") ? "dcim.interface" : "dcim.device";
}

function guessFromName(name: string): NautobotUuidResolution | undefined {
  const lower = name.toLowerCase();
  if (lower.includes("location")) return { resource_type: "location" };
  if (lower.includes("platform")) return { resource_type: "platform" };
  if (lower.includes("rack")) return { resource_type: "rack" };
  if (lower.includes("namespace")) return { resource_type: "namespace" };
  if (lower.includes("device_type") || lower.includes("devicetype")) {
    return { resource_type: "device_type" };
  }
  if (lower.includes("role")) {
    return { resource_type: "role", content_type: guessContentType(name) };
  }
  if (lower.includes("status")) {
    return { resource_type: "status", content_type: guessContentType(name) };
  }
  if (lower.includes("device")) return { resource_type: "device" };
  return undefined;
}

/** Suggest a UUID resolution for a job parameter, from its declared type/model first,
 * falling back to a name heuristic when Nautobot didn't declare it as an ObjectVar. */
export function detectUuidResolution(
  variable: NautobotJobVariable,
): NautobotUuidResolution | undefined {
  if (OBJECT_VAR_TYPES.has(variable.type) && variable.model) {
    const resourceType = OBJECTVAR_MODEL_TO_RESOURCE_TYPE[variable.model];
    if (resourceType) {
      return resourceType === "role" || resourceType === "status"
        ? { resource_type: resourceType, content_type: guessContentType(variable.name) }
        : { resource_type: resourceType };
    }
  }
  return guessFromName(variable.name);
}
