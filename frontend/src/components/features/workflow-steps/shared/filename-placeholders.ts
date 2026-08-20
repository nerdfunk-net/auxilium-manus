export const FILENAME_PLACEHOLDERS = [
  "{device.name}",
  "{device.hostname}",
  "{device.primary_ip4}",
  "{nautobot.location.name}",
  "{nautobot.role.name}",
  "{nautobot.custom_fields.<slug>}",
  "{git.source_file}",
  "{command.name}",
  "{parsed.output_key}",
  "{run.timestamp}",
  "{run.date}",
  "{run.id}",
] as const;

export const COMMIT_MESSAGE_PLACEHOLDERS = [
  "{timestamp}",
  "{run.id}",
  "{workflow.id}",
] as const;

export function filenamePlaceholderHint(prefix = "Placeholders"): string {
  return `${prefix}: ${FILENAME_PLACEHOLDERS.join(", ")}.`;
}
