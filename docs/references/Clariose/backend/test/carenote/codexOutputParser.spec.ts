import { parseCodexJson, stripFences } from "../../src/modules/carenote/codex-harness/codexOutputParser";

describe("codexOutputParser", () => {
  test("strips ```json fences", () => {
    const input = "```json\n{\"a\":1}\n```";
    expect(stripFences(input)).toBe('{"a":1}');
  });

  test("strips bare ``` fences", () => {
    expect(stripFences("```\n{\"x\":2}\n```")).toBe('{"x":2}');
  });

  test("parses fenced JSON", () => {
    const r = parseCodexJson("```json\n{\"k\":\"v\"}\n```");
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value).toEqual({ k: "v" });
  });

  test("reports parse error for malformed JSON", () => {
    const r = parseCodexJson("not json at all");
    expect(r.ok).toBe(false);
  });
});
