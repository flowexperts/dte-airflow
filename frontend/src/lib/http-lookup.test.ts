import { describe, expect, it } from "vitest";
import { emptyStep } from "@/components/builder/steps/types";
import { missingPlaceholders, urlPlaceholders } from "./http-lookup";

describe("urlPlaceholders", () => {
  it("returns each placeholder once, in order", () => {
    expect(urlPlaceholders("https://x/{name}/v/{ver}/{name}")).toEqual(["name", "ver"]);
  });

  it("is empty for a url without placeholders", () => {
    expect(urlPlaceholders("https://pypi.org/simple/")).toEqual([]);
  });
});

describe("missingPlaceholders", () => {
  it("names placeholders that are not columns at this step", () => {
    expect(missingPlaceholders("https://x/{name}/{nmae}", ["name", "rule"])).toEqual(["nmae"]);
  });

  it("stays quiet while the schema is unknown", () => {
    expect(missingPlaceholders("https://x/{anything}", [])).toEqual([]);
  });
});

describe("emptyStep('http_lookup')", () => {
  it("starts with the shape the backend expects", () => {
    expect(emptyStep("http_lookup")).toEqual({
      op: "http_lookup",
      url: "https://",
      fields: [{ name: "", path: "", type: "string" }],
      max_rows: 500,
      on_error: "null",
    });
  });
});
