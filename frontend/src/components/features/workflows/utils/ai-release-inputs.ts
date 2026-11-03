import type {
  AiReleaseInput,
  AiReleaseNode,
} from "../types/workflow-ai-release";

/** The step kind whose `device_param` names the run input that receives the devices. */
const DEVICE_INPUT_STEP_KIND = "get-from-user";

/** Text run inputs: the only kind that can receive the device lines. */
export function textInputs(
  inputs: AiReleaseInput[] | null | undefined,
): AiReleaseInput[] {
  return (inputs ?? []).filter((input) => input.type === "string");
}

/** Credential run inputs: the ones the confirming user fills in on the card. */
export function credentialInputs(
  inputs: AiReleaseInput[] | null | undefined,
): AiReleaseInput[] {
  return (inputs ?? []).filter(
    (input) => input.type === "reference" && input.ref_kind === "credential",
  );
}

/** Names of the text inputs read by an enabled Get from User step. */
export function deviceInputsInUse(
  nodes: AiReleaseNode[] | null | undefined,
): string[] {
  const names = new Set<string>();
  for (const node of nodes ?? []) {
    const data = node.data;
    const param = data?.pluginConfig?.device_param;
    if (
      data?.kind === DEVICE_INPUT_STEP_KIND &&
      data.disabled !== true &&
      typeof param === "string" &&
      param
    ) {
      names.add(param);
    }
  }
  return [...names];
}

/**
 * The devices input to pre-select when the workflow has none released yet: the single text input
 * an enabled Get from User step reads. Several candidates (or none) leave the choice to the user.
 */
export function suggestedDevicesInput(
  nodes: AiReleaseNode[] | null | undefined,
  inputs: AiReleaseInput[] | null | undefined,
): string | null {
  const text = new Set(textInputs(inputs).map((input) => input.name));
  const candidates = deviceInputsInUse(nodes).filter((name) => text.has(name));
  return candidates.length === 1 ? candidates[0] : null;
}
