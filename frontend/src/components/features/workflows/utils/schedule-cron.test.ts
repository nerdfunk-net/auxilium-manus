import { describe, expect, it } from "vitest";

import { buildCronExpression, parseCronExpression } from "./schedule-cron";

describe("buildCronExpression", () => {
  it("builds daily 09:00 UTC", () => {
    expect(
      buildCronExpression({
        frequency: "daily",
        time: "09:00",
      }),
    ).toBe("0 9 * * *");
  });

  it("builds weekly Mon/Wed/Fri at 14:30 UTC", () => {
    expect(
      buildCronExpression({
        frequency: "weekly",
        time: "14:30",
        days: ["mon", "wed", "fri"],
      }),
    ).toBe("30 14 * * 1,3,5");
  });

  it("builds hourly at minute 15", () => {
    expect(
      buildCronExpression({
        frequency: "hourly",
        minute: "15",
      }),
    ).toBe("15 * * * *");
  });

  it("passes through custom cron unchanged", () => {
    expect(
      buildCronExpression({
        frequency: "custom",
        customCron: "0 9 * * 1-5",
      }),
    ).toBe("0 9 * * 1-5");
  });
});

describe("parseCronExpression", () => {
  it("parses daily 09:00 UTC", () => {
    expect(parseCronExpression("0 9 * * *")).toEqual({
      frequency: "daily",
      time: "09:00",
    });
  });

  it("parses weekly Mon/Wed/Fri at 14:30 UTC", () => {
    expect(parseCronExpression("30 14 * * 1,3,5")).toEqual({
      frequency: "weekly",
      time: "14:30",
      days: ["mon", "wed", "fri"],
    });
  });

  it("falls back to custom for non-standard expressions", () => {
    expect(parseCronExpression("0 9 * *")).toEqual({
      frequency: "custom",
      customCron: "0 9 * *",
    });
  });
});
