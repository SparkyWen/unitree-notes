import { parseCodexJson } from "../../src/modules/carenote/codex-harness/codexOutputParser";

describe("codexOutputParser hardening", () => {
  test("extracts JSON from prose preamble", () => {
    const raw = "Sure! Here is the result:\n{\n  \"facts\": []\n}\nThat's all.";
    const r = parseCodexJson(raw);
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.value).toEqual({ facts: [] });
      expect(r.source).toBe("extracted");
    }
  });

  test("extracts JSON from a fenced block embedded in prose", () => {
    const raw = "Here you go:\n\n```json\n{\"facts\":[{\"x\":1}]}\n```\n\nDone.";
    const r = parseCodexJson(raw);
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.value).toEqual({ facts: [{ x: 1 }] });
  });

  test("repairs trailing commas", () => {
    const raw = '{"facts": [{"a": 1,},],}';
    const r = parseCodexJson(raw);
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.value).toEqual({ facts: [{ a: 1 }] });
      expect(r.source).toBe("repaired");
    }
  });

  test("returns explicit error with preview on failure", () => {
    const r = parseCodexJson("the model said no JSON here at all");
    expect(r.ok).toBe(false);
    if (!r.ok) {
      expect(r.error.length).toBeGreaterThan(0);
      expect(r.preview.length).toBeGreaterThan(0);
    }
  });

  test("handles braces inside string literals correctly", () => {
    const raw =
      'Here:\n{"label": "value with } brace", "facts": []}';
    const r = parseCodexJson(raw);
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect((r.value as { facts: unknown[] }).facts).toEqual([]);
    }
  });

  test("flags empty output", () => {
    const r = parseCodexJson("   \n  ");
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error).toMatch(/empty/);
  });
});
