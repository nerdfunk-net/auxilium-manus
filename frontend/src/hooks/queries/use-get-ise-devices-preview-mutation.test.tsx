import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createQueryWrapper } from "@/test/query-wrapper";

import {
  useGetIseDevicesPreviewMutation,
  type IsePreviewRequest,
} from "./use-get-ise-devices-preview-mutation";

const apiCall = vi.fn();
vi.mock("@/hooks/use-api", () => ({ useApi: () => ({ apiCall }) }));

type Detail = {
  id?: string;
  name?: string;
  NetworkDeviceIPList?: { ipaddress?: string; mask?: number }[];
  NetworkDeviceGroupList?: string[];
};

const detail = (id: string, ip: string, mask = 32, extra: Partial<Detail> = {}): Detail => ({
  id,
  name: `sw-${id}`,
  NetworkDeviceIPList: [{ ipaddress: ip, mask }],
  ...extra,
});

/** Routes apiCall by URL: details by id, lists by path prefix. */
function route(handlers: {
  details?: Record<string, Detail | Error>;
  names?: Record<string, Detail | Error | unknown>;
  lists?: (url: string) => unknown;
}) {
  apiCall.mockImplementation(async (url: string) => {
    const nameMatch = url.match(/devices\/name\/([^?]+)/);
    if (nameMatch) {
      const hit = handlers.names?.[decodeURIComponent(nameMatch[1])];
      if (hit === undefined || hit instanceof Error) throw hit ?? new Error("404");
      return hit;
    }
    const idMatch = url.match(/devices\/([0-9a-z-]+)$/);
    if (idMatch && handlers.details) {
      const hit = handlers.details[idMatch[1]];
      if (!hit || hit instanceof Error) throw hit ?? new Error("404");
      return { NetworkDevice: hit };
    }
    return handlers.lists?.(url);
  });
}

async function preview(request: IsePreviewRequest) {
  const { wrapper } = createQueryWrapper();
  const { result } = renderHook(() => useGetIseDevicesPreviewMutation(), { wrapper });
  let response!: Awaited<ReturnType<typeof result.current.mutateAsync>>;
  await act(async () => {
    response = await result.current.mutateAsync(request);
  });
  return response;
}

beforeEach(() => {
  apiCall.mockReset();
});

describe("name mode", () => {
  it("looks each name up (URL-encoded) and skips the ones ISE does not know", async () => {
    route({ names: { "core 1": { NetworkDevice: detail("a", "10.0.0.1") } } });
    const out = await preview({
      source_id: "s1",
      query_mode: "name",
      device_names: ["core 1", "ghost"],
    });
    expect(apiCall).toHaveBeenCalledWith("sources/ise/s1/devices/name/core%201", { method: "GET" });
    expect(out.devices.map((d) => d.id)).toEqual(["a"]);
    expect(out.truncated).toBe(false);
  });

  it("maps the first IP, the mask and the groups", async () => {
    route({
      names: {
        x: { NetworkDevice: detail("a", "10.1.0.0", 24, { NetworkDeviceGroupList: ["Location#All"] }) },
      },
    });
    const out = await preview({ source_id: "s1", query_mode: "name", device_names: ["x"] });
    expect(out.devices[0]).toEqual({
      id: "a",
      name: "sw-a",
      primary_ip4: "10.1.0.0",
      mask: 24,
      is_group_or_prefix: true,
      groups: ["Location#All"],
    });
  });

  it("a /32 entry is a plain host, not a prefix", async () => {
    route({ names: { x: { NetworkDevice: detail("a", "10.0.0.1", 32) } } });
    const out = await preview({ source_id: "s1", query_mode: "name", device_names: ["x"] });
    expect(out.devices[0].is_group_or_prefix).toBe(false);
  });

  it("drops a device without id or name and keeps the rest", async () => {
    route({
      names: {
        a: { NetworkDevice: { name: "no-id" } },
        b: { NetworkDevice: { id: "x" } },
        c: { NetworkDevice: detail("c", "10.0.0.3") },
      },
    });
    const out = await preview({ source_id: "s1", query_mode: "name", device_names: ["a", "b", "c"] });
    expect(out.devices.map((d) => d.id)).toEqual(["c"]);
  });

  it("survives a 200 answer without a NetworkDevice", async () => {
    route({ names: { a: {}, b: { NetworkDevice: detail("b", "10.0.0.2") } } });
    const out = await preview({ source_id: "s1", query_mode: "name", device_names: ["a", "b"] });
    expect(out.devices.map((d) => d.id)).toEqual(["b"]);
  });

  it("previews at most 25 names and says the list was cut", async () => {
    const names = Array.from({ length: 30 }, (_, i) => `n${i}`);
    const hits = Object.fromEntries(
      names.map((n, i) => [n, { NetworkDevice: detail(`d${i}`, `10.0.0.${i}`) }]),
    );
    route({ names: hits });
    const out = await preview({ source_id: "s1", query_mode: "name", device_names: names });
    expect(apiCall).toHaveBeenCalledTimes(25);
    expect(out.devices).toHaveLength(25);
    expect(out.truncated).toBe(true);
  });

  it("exactly 25 names are not truncated", async () => {
    const names = Array.from({ length: 25 }, (_, i) => `n${i}`);
    route({ names: Object.fromEntries(names.map((n, i) => [n, { NetworkDevice: detail(`d${i}`, "10.0.0.1") }])) });
    const out = await preview({ source_id: "s1", query_mode: "name", device_names: names });
    expect(out.truncated).toBe(false);
  });

  it("no names means no request and no devices", async () => {
    const out = await preview({ source_id: "s1", query_mode: "name" });
    expect(apiCall).not.toHaveBeenCalled();
    expect(out).toEqual({ devices: [], truncated: false });
  });
});

describe("group mode", () => {
  it("lists the group (URL-encoded, 25 per page) and detail-fetches the members", async () => {
    route({
      details: { a: detail("a", "10.0.0.1"), b: detail("b", "10.0.0.2") },
      lists: () => ({ total: 2, resources: [{ id: "a" }, { id: "b" }], next_page: null }),
    });
    const out = await preview({ source_id: "s1", query_mode: "group", group_name: "Location#All Locations" });
    expect(apiCall.mock.calls[0][0]).toBe(
      "sources/ise/s1/devices/ndg/Location%23All%20Locations?page=1&size=25",
    );
    expect(out.devices.map((d) => d.id)).toEqual(["a", "b"]);
    expect(out.truncated).toBe(false);
  });

  it("flags truncation when the group has more members than the page", async () => {
    route({
      details: { a: detail("a", "10.0.0.1") },
      lists: () => ({ total: 90, resources: [{ id: "a" }], next_page: "p2" }),
    });
    const out = await preview({ source_id: "s1", query_mode: "group", group_name: "g" });
    expect(out.truncated).toBe(true);
  });

  it("skips a member whose detail request fails and ignores summaries without an id", async () => {
    route({
      details: { a: detail("a", "10.0.0.1"), b: new Error("boom") },
      lists: () => ({ total: 3, resources: [{ id: "a" }, { id: "b" }, { name: "no-id" }], next_page: null }),
    });
    const out = await preview({ source_id: "s1", query_mode: "group", group_name: "g" });
    expect(out.devices.map((d) => d.id)).toEqual(["a"]);
  });

  it("a failing group listing rejects the preview", async () => {
    apiCall.mockRejectedValue(new Error("ISE unreachable"));
    const { wrapper } = createQueryWrapper();
    const { result } = renderHook(() => useGetIseDevicesPreviewMutation(), { wrapper });
    act(() => result.current.mutate({ source_id: "s1", query_mode: "group", group_name: "g" }));
    await waitFor(() => expect(result.current.error?.message).toBe("ISE unreachable"));
  });

  it("detail-fetches at most 10 members at a time", async () => {
    let inFlight = 0;
    let peak = 0;
    apiCall.mockImplementation(async (url: string) => {
      if (url.includes("/ndg/")) {
        return { total: 25, resources: Array.from({ length: 25 }, (_, i) => ({ id: `d${i}` })), next_page: null };
      }
      inFlight += 1;
      peak = Math.max(peak, inFlight);
      await new Promise((r) => setTimeout(r, 1));
      inFlight -= 1;
      const id = url.split("/").pop()!;
      return { NetworkDevice: detail(id, "10.0.0.1") };
    });
    const out = await preview({ source_id: "s1", query_mode: "group", group_name: "g" });
    expect(out.devices).toHaveLength(25);
    expect(peak).toBe(10);
  });
});

describe("cidr mode: single host", () => {
  it("a bare address filters server-side", async () => {
    route({
      details: { a: detail("a", "10.0.0.5") },
      lists: () => ({ total: 1, resources: [{ id: "a" }], next_page: null }),
    });
    const out = await preview({ source_id: "s1", query_mode: "cidr", cidr: " 10.0.0.5 " });
    expect(apiCall.mock.calls[0][0]).toBe(
      `sources/ise/s1/devices?filter=${encodeURIComponent("ipaddress.EQ.10.0.0.5")}`,
    );
    expect(out.devices.map((d) => d.id)).toEqual(["a"]);
  });

  it("/32 is treated as a host", async () => {
    route({ lists: () => ({ total: 0, resources: [], next_page: null }) });
    await preview({ source_id: "s1", query_mode: "cidr", cidr: "10.0.0.5/32" });
    expect(apiCall.mock.calls[0][0]).toContain("ipaddress.EQ.10.0.0.5");
  });
});

describe("cidr mode: range", () => {
  const scan = (devices: Record<string, Detail>, pages: { total: number; ids: string[]; next: string | null }[]) => {
    let call = 0;
    route({
      details: devices,
      lists: () => {
        const page = pages[Math.min(call, pages.length - 1)];
        call += 1;
        return { total: page.total, resources: page.ids.map((id) => ({ id })), next_page: page.next };
      },
    });
  };

  it("scans every page, then keeps only devices inside the range", async () => {
    scan(
      {
        a: detail("a", "10.1.0.4"),
        b: detail("b", "192.168.0.1"),
        c: detail("c", "10.1.255.254"),
        d: detail("d", "10.2.0.1"),
      },
      [
        { total: 4, ids: ["a", "b"], next: "p2" },
        { total: 4, ids: ["c", "d"], next: null },
      ],
    );
    const out = await preview({ source_id: "s1", query_mode: "cidr", cidr: "10.1.0.0/16" });
    expect(apiCall.mock.calls[0][0]).toBe("sources/ise/s1/devices?page=1&size=100");
    expect(apiCall.mock.calls[1][0]).toBe("sources/ise/s1/devices?page=2&size=100");
    expect(out.devices.map((d) => d.id)).toEqual(["a", "c"]);
    expect(out.truncated).toBe(false);
  });

  it("matches on any of a device's addresses", async () => {
    route({
      details: {
        a: { id: "a", name: "multi", NetworkDeviceIPList: [{ ipaddress: "172.16.0.1" }, { ipaddress: "10.1.0.9" }] },
      },
      lists: () => ({ total: 1, resources: [{ id: "a" }], next_page: null }),
    });
    const out = await preview({ source_id: "s1", query_mode: "cidr", cidr: "10.1.0.0/24" });
    expect(out.devices.map((d) => d.id)).toEqual(["a"]);
  });

  it("stops at 500 summaries and reports truncation", async () => {
    const ids = (from: number) => Array.from({ length: 100 }, (_, i) => `d${from + i}`);
    const devices = Object.fromEntries(
      Array.from({ length: 700 }, (_, i) => [`d${i}`, detail(`d${i}`, "10.9.0.1")]),
    );
    scan(devices, [0, 100, 200, 300, 400, 500, 600].map((from, i) => ({ total: 700, ids: ids(from), next: i < 6 ? "n" : null })));
    const out = await preview({ source_id: "s1", query_mode: "cidr", cidr: "10.9.0.0/16" });
    expect(apiCall.mock.calls.filter(([u]) => String(u).includes("?page="))).toHaveLength(5);
    expect(out.devices).toHaveLength(500);
    expect(out.truncated).toBe(true);
  });

  it("an empty page ends the scan even if ISE still offers a next page", async () => {
    scan({}, [{ total: 5, ids: [], next: "p2" }]);
    const out = await preview({ source_id: "s1", query_mode: "cidr", cidr: "10.0.0.0/8" });
    expect(apiCall).toHaveBeenCalledTimes(1);
    expect(out).toEqual({ devices: [], truncated: true });
  });

  it.each([
    ["10.0.0.0/0", "203.0.113.9", true],
    ["10.0.0.0/8", "10.255.255.255", true],
    ["10.0.0.0/8", "11.0.0.0", false],
    ["10.0.0.128/25", "10.0.0.200", true],
    ["10.0.0.128/25", "10.0.0.127", false],
  ])("range %s contains %s: %s", async (cidr, ip, expected) => {
    scan({ a: detail("a", ip) }, [{ total: 1, ids: ["a"], next: null }]);
    const out = await preview({ source_id: "s1", query_mode: "cidr", cidr });
    expect(out.devices.length === 1).toBe(expected);
  });

  it.each([
    ["an IPv6 address", "0.0.0.0/8", "fe80::1"],
    ["a malformed address", "0.0.0.0/8", "not-an-ip"],
    ["a short address", "0.0.0.0/8", "1.2"],
    ["an octet above 255", "0.0.0.0/8", "0.0.0.256"],
  ])("never matches %s", async (_label, cidr, ip) => {
    scan({ a: detail("a", ip) }, [{ total: 1, ids: ["a"], next: null }]);
    const out = await preview({ source_id: "s1", query_mode: "cidr", cidr });
    expect(out.devices).toEqual([]);
  });

  it.each([
    ["a prefix above 32", "10.0.0.0/33"],
    ["a negative prefix", "10.0.0.0/-1"],
    ["a non-numeric prefix", "10.0.0.0/abc"],
    ["a malformed network", "abc/8"],
  ])("a range with %s matches nothing", async (_label, cidr) => {
    scan({ a: detail("a", "10.0.0.1"), z: detail("z", "0.0.0.1") }, [{ total: 2, ids: ["a", "z"], next: null }]);
    const out = await preview({ source_id: "s1", query_mode: "cidr", cidr });
    expect(out.devices).toEqual([]);
  });
});

describe("empty input never reaches the backend", () => {
  async function rejection(request: IsePreviewRequest) {
    const { wrapper } = createQueryWrapper();
    const { result } = renderHook(() => useGetIseDevicesPreviewMutation(), { wrapper });
    let error: Error | undefined;
    await act(async () => {
      await result.current.mutateAsync(request).catch((e: Error) => {
        error = e;
      });
    });
    return error;
  }

  it.each(["", "   "])("a blank group name %j is refused without a request", async (groupName) => {
    const error = await rejection({ source_id: "s1", query_mode: "group", group_name: groupName });
    expect(error?.message).toBe("Enter a network device group name");
    expect(apiCall).not.toHaveBeenCalled();
  });

  it("a missing group name is refused too", async () => {
    const error = await rejection({ source_id: "s1", query_mode: "group" });
    expect(error?.message).toBe("Enter a network device group name");
    expect(apiCall).not.toHaveBeenCalled();
  });

  it.each(["", "  "])("a blank CIDR %j is refused without a request", async (cidr) => {
    const error = await rejection({ source_id: "s1", query_mode: "cidr", cidr });
    expect(error?.message).toBe("Enter an IP address or CIDR range");
    expect(apiCall).not.toHaveBeenCalled();
  });

  it("a missing CIDR is refused too", async () => {
    const error = await rejection({ source_id: "s1", query_mode: "cidr" });
    expect(error?.message).toBe("Enter an IP address or CIDR range");
    expect(apiCall).not.toHaveBeenCalled();
  });

  it("surrounding spaces in the group name are not sent", async () => {
    route({ lists: () => ({ total: 0, resources: [], next_page: null }) });
    await preview({ source_id: "s1", query_mode: "group", group_name: "  Location#All  " });
    expect(apiCall.mock.calls[0][0]).toBe(
      "sources/ise/s1/devices/ndg/Location%23All?page=1&size=25",
    );
  });
});

describe("useGetIseDevicesPreviewMutation stability", () => {
  it("keeps the same mutate function across renders", () => {
    const { wrapper } = createQueryWrapper();
    const { result, rerender } = renderHook(() => useGetIseDevicesPreviewMutation(), { wrapper });
    const first = result.current.mutate;
    rerender();
    expect(result.current.mutate).toBe(first);
  });
});
