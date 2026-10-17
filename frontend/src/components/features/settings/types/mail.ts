/** Mirrors backend/models/mail.py. */

export type MailSecurity = "none" | "starttls" | "ssl";

export interface MailSettings {
  smtp_server: string;
  smtp_port: number;
  security: MailSecurity;
  verify_tls: boolean;
  from_address: string;
  /** Name of a global generic credential (SMTP user and password); null sends without login. */
  credential_name: string | null;
  /** Only these domains (and subdomains) may receive reports; empty means any. */
  allowed_recipient_domains: string[];
}

export interface MailSettingsResponse extends MailSettings {
  /** Server and sender are set, so mail can be sent. */
  configured: boolean;
}

export interface MailTestResult {
  ok: boolean;
  message: string;
}

export const MAIL_SECURITY_OPTIONS: { value: MailSecurity; label: string; port: number }[] = [
  { value: "none", label: "None (plain SMTP)", port: 25 },
  { value: "starttls", label: "STARTTLS", port: 587 },
  { value: "ssl", label: "SSL/TLS (implicit)", port: 465 },
];
