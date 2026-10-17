/** Same limit and shape rule as backend/models/mail.py (`MAX_RECIPIENTS`, `clean_address`). */
export const MAX_RECIPIENTS = 20;
const ADDRESS = /^[^@\s<>,;]+@[^@\s<>,;]+$/;

export interface ParsedRecipients {
  addresses: string[];
  invalid: string[];
  tooMany: boolean;
}

/** Addresses typed into a text box: separated by commas, semicolons, spaces or line breaks. */
export function parseRecipients(text: string): ParsedRecipients {
  const addresses: string[] = [];
  const invalid: string[] = [];
  for (const entry of text.split(/[\s,;]+/)) {
    if (entry === "") continue;
    if (!ADDRESS.test(entry)) {
      if (!invalid.includes(entry)) invalid.push(entry);
    } else if (!addresses.includes(entry)) {
      addresses.push(entry);
    }
  }
  return { addresses, invalid, tooMany: addresses.length > MAX_RECIPIENTS };
}

export function formatRecipients(addresses: readonly string[]): string {
  return addresses.join("\n");
}
