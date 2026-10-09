import { describe, expect, it } from "vitest";
import { dictionaries, translate } from "@/lib/i18n";

describe("i18n", () => {
  it("translates and falls back to English then to the key", () => {
    expect(translate("es", "nav.inbox")).toBe("Bandeja");
    expect(translate("en", "nav.inbox")).toBe("Inbox");
    expect(translate("es", "nope" as never)).toBe("nope");
  });
  it("every locale defines exactly the same keys as English (no missing translations)", () => {
    const en = Object.keys(dictionaries.en).sort();
    for (const [loc, d] of Object.entries(dictionaries)) expect(Object.keys(d).sort(), loc).toEqual(en);
  });
});
