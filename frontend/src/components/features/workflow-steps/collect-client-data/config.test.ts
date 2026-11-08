import { describe, expect, it } from "vitest";

import {
  buildCollectClientDataConfig,
  clampDnsConcurrency,
  clampDnsTimeout,
  DEFAULT_DNS_CONCURRENCY,
  DEFAULT_DNS_TIMEOUT_SECONDS,
  MAX_DNS_CONCURRENCY,
  MAX_DNS_TIMEOUT_SECONDS,
  MIN_DNS_CONCURRENCY,
  MIN_DNS_TIMEOUT_SECONDS,
} from "./config";

describe("clampDnsTimeout", () => {
  it("clamps into the backend range and falls back for non-numbers", () => {
    expect(clampDnsTimeout("0")).toBe(MIN_DNS_TIMEOUT_SECONDS);
    expect(clampDnsTimeout("500")).toBe(MAX_DNS_TIMEOUT_SECONDS);
    expect(clampDnsTimeout("2.5")).toBe(2.5);
    expect(clampDnsTimeout("abc")).toBe(DEFAULT_DNS_TIMEOUT_SECONDS);
    expect(clampDnsTimeout("")).toBe(DEFAULT_DNS_TIMEOUT_SECONDS);
  });
});

describe("clampDnsConcurrency", () => {
  it("clamps into the backend range and falls back for non-numbers", () => {
    expect(clampDnsConcurrency("0")).toBe(MIN_DNS_CONCURRENCY);
    expect(clampDnsConcurrency("1000")).toBe(MAX_DNS_CONCURRENCY);
    expect(clampDnsConcurrency("7")).toBe(7);
    expect(clampDnsConcurrency("x")).toBe(DEFAULT_DNS_CONCURRENCY);
  });
});

describe("buildCollectClientDataConfig", () => {
  it("defaults to IP, MAC and VRFs on and hostnames off", () => {
    const built = buildCollectClientDataConfig({});
    expect(built).toMatchObject({
      collect_ip_address: true,
      collect_mac_address: true,
      collect_vrfs: true,
      collect_hostname: false,
      collect_neighbors: false,
    });
  });

  it("keeps the neighbour switch as given and independent of the other tables", () => {
    expect(buildCollectClientDataConfig({}, { collect_neighbors: true }).collect_neighbors).toBe(
      true,
    );
    const built = buildCollectClientDataConfig(
      { collect_neighbors: true },
      { collect_ip_address: false },
    );
    expect(built.collect_neighbors).toBe(true);
  });

  it("keeps MAC on when the last other table is switched off", () => {
    const built = buildCollectClientDataConfig(
      { collect_mac_address: false },
      { collect_ip_address: false },
    );
    expect(built.collect_ip_address).toBe(false);
    expect(built.collect_mac_address).toBe(true);
  });

  it("keeps IP on when MAC is switched off while IP is already off", () => {
    const built = buildCollectClientDataConfig(
      { collect_ip_address: false },
      { collect_mac_address: false },
    );
    expect(built.collect_ip_address).toBe(true);
  });

  it("drops VRF and hostname collection when ARP is off", () => {
    const built = buildCollectClientDataConfig(
      { collect_hostname: true, collect_vrfs: true },
      { collect_ip_address: false },
    );
    expect(built.collect_vrfs).toBe(false);
    expect(built.collect_hostname).toBe(false);
  });

  it("does not touch unrelated keys", () => {
    const built = buildCollectClientDataConfig({ credential_reference: "lab" }, { dry_run: true });
    expect(built.credential_reference).toBe("lab");
    expect(built.dry_run).toBe(true);
  });
});
