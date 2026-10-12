import { describe, expect, it, vi } from "vitest";

// The language module reads the phone's locale through an Expo native module.
vi.mock("expo-localization", () => ({ getLocales: () => [{ languageCode: "en" }] }));

import { en } from "../src/i18n/en";
import { translate } from "../src/i18n";
import { yo } from "../src/i18n/yo";

const placeholders = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe("translations", () => {
  it("only translate keys that exist", () => {
    const unknown = Object.keys(yo).filter((k) => !(k in en));
    expect(unknown).toEqual([]);
  });

  it("cover every string the agent reads", () => {
    const missing = Object.keys(en).filter((k) => !(k in yo));
    expect(missing).toEqual([]);
  });

  it("keep every placeholder, so no number or name goes missing", () => {
    for (const [key, text] of Object.entries(yo)) {
      expect(placeholders(text as string), key).toEqual(placeholders(en[key as keyof typeof en]));
    }
  });

  it("are never blank", () => {
    for (const [key, text] of Object.entries(yo)) {
      expect((text as string).trim().length, key).toBeGreaterThan(0);
    }
  });

  it("fill values in and fall back to English", () => {
    expect(translate("en", "today.version", { n: 2, when: "5 min ago" })).toBe(
      "Version 2 · 5 min ago",
    );
    expect(translate("yo", "today.version", { n: 2, when: "5 min ago" })).toContain("2");
    expect(translate("yo", "tab.today")).toBe("Òní");
  });
});
