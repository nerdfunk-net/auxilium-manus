export type FileFormat = "yaml" | "csv";

export const FILE_FORMAT_KEY = "file_format";
export const CSV_DELIMITER_KEY = "csv_delimiter";
export const CSV_MULTILINE_KEY = "csv_multiline";

export const DEFAULT_PATTERN: Record<FileFormat, string> = {
  yaml: "*.yaml",
  csv: "*.csv",
};

export interface DelimiterOption {
  value: string;
  label: string;
}

export const CSV_DELIMITERS: readonly DelimiterOption[] = [
  { value: ";", label: "Semicolon ( ; )" },
  { value: ",", label: "Comma ( , )" },
  { value: "\t", label: "Tab" },
  { value: "|", label: "Pipe ( | )" },
];

export const DEFAULT_DELIMITER = ";";

export function fileFormatFromConfig(config: Record<string, unknown>): FileFormat {
  return config[FILE_FORMAT_KEY] === "csv" ? "csv" : "yaml";
}

export function delimiterFromConfig(config: Record<string, unknown>): string {
  const raw = config[CSV_DELIMITER_KEY];
  return typeof raw === "string" && CSV_DELIMITERS.some((option) => option.value === raw)
    ? raw
    : DEFAULT_DELIMITER;
}

export function multilineFromConfig(config: Record<string, unknown>): boolean {
  return config[CSV_MULTILINE_KEY] === true;
}

/** Switch the filename pattern with the file type, but only while it still holds a default. */
export function patternForFormat(currentPattern: string, next: FileFormat): string {
  const isDefault = Object.values(DEFAULT_PATTERN).includes(currentPattern.trim());
  return isDefault || !currentPattern.trim() ? DEFAULT_PATTERN[next] : currentPattern;
}
