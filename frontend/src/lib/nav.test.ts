import { describe, expect, it } from "vitest";
import { ownerOf } from "./nav";

describe("ownerOf", () => {
  it("mounts each section under the Airflow nav entry that owns it", () => {
    expect(ownerOf("/sources")).toBe("/plugin/dte-sources");
    expect(ownerOf("/sources/edit?id=x")).toBe("/plugin/dte-sources");
    expect(ownerOf("/lookup-tables")).toBe("/plugin/dte-lookup-tables");
    expect(ownerOf("/pipelines/detail?id=x")).toBe("/plugin/dte");
    // A prefix match must be a whole segment.
    expect(ownerOf("/sourcesx")).toBe("/plugin/dte");
  });
});
