import { z } from "zod";

import {
  toOpenAIStrictJsonSchema,
  ensureNullable,
} from "../../src/modules/carenote/codex-harness/openAiStrictSchema";
import { zodToJsonSchema } from "../../src/modules/carenote/codex-harness/zodToJsonSchemaShim";
import {
  MedicalInstructionExtractorOutputSchema,
  RoleOutputSchemas,
} from "../../src/modules/carenote/medical/medicalSchemas";

type AnyObj = Record<string, unknown>;

function isObj(v: unknown): v is AnyObj {
  return !!v && typeof v === "object" && !Array.isArray(v);
}

function walkObjects(node: unknown, visit: (n: AnyObj, path: string) => void, path = "$"): void {
  if (Array.isArray(node)) {
    node.forEach((c, i) => walkObjects(c, visit, `${path}[${i}]`));
    return;
  }
  if (!isObj(node)) return;
  visit(node, path);
  for (const [k, v] of Object.entries(node)) {
    walkObjects(v, visit, `${path}.${k}`);
  }
}

function assertEveryObjectIsStrict(schema: unknown): void {
  walkObjects(schema, (n, path) => {
    if (isObj(n.properties)) {
      // additionalProperties must be false
      expect({ path, additionalProperties: n.additionalProperties }).toEqual({
        path,
        additionalProperties: false,
      });
      // required must include every key in properties
      const propKeys = Object.keys(n.properties as AnyObj);
      expect({ path, required: n.required }).toEqual({
        path,
        required: propKeys,
      });
    }
  });
}

describe("toOpenAIStrictJsonSchema", () => {
  it("forces additionalProperties:false on every object with properties", () => {
    const input = {
      type: "object",
      properties: {
        a: { type: "string" },
        b: {
          type: "object",
          properties: { c: { type: "number" } },
        },
      },
    };
    const out = toOpenAIStrictJsonSchema(input) as AnyObj;
    assertEveryObjectIsStrict(out);
  });

  it("includes every property key in `required`", () => {
    const input = {
      type: "object",
      properties: { a: { type: "string" }, b: { type: "number" } },
      required: ["a"],
    };
    const out = toOpenAIStrictJsonSchema(input) as AnyObj;
    expect(out.required).toEqual(["a", "b"]);
  });

  it("converts previously-optional fields to nullable when promoting to required", () => {
    const input = {
      type: "object",
      properties: { a: { type: "string" }, b: { type: "number" } },
      required: ["a"],
    };
    const out = toOpenAIStrictJsonSchema(input) as AnyObj;
    const props = out.properties as AnyObj;
    expect((props.a as AnyObj).type).toBe("string");
    expect((props.b as AnyObj).type).toEqual(["number", "null"]);
  });

  it("preserves anyOf nullable unions and does not double-add null", () => {
    const input = {
      type: "object",
      properties: {
        a: { anyOf: [{ type: "string" }, { type: "null" }] },
      },
    };
    const out = toOpenAIStrictJsonSchema(input) as AnyObj;
    const a = (out.properties as AnyObj).a as AnyObj;
    expect(a.anyOf).toEqual([{ type: "string" }, { type: "null" }]);
    expect(out.required).toEqual(["a"]);
  });

  it("recurses into array items", () => {
    const input = {
      type: "object",
      properties: {
        list: {
          type: "array",
          items: {
            type: "object",
            properties: { x: { type: "string" } },
          },
        },
      },
    };
    const out = toOpenAIStrictJsonSchema(input) as AnyObj;
    assertEveryObjectIsStrict(out);
    const item = ((out.properties as AnyObj).list as AnyObj).items as AnyObj;
    expect(item.additionalProperties).toBe(false);
    expect(item.required).toEqual(["x"]);
  });

  it("recurses into anyOf / oneOf branches", () => {
    const input = {
      anyOf: [
        { type: "object", properties: { a: { type: "string" } } },
        { type: "object", properties: { b: { type: "number" } } },
      ],
    };
    const out = toOpenAIStrictJsonSchema(input) as AnyObj;
    assertEveryObjectIsStrict(out);
  });

  it("does not mutate the input schema", () => {
    const input = {
      type: "object",
      properties: { a: { type: "string" } },
    };
    const before = JSON.stringify(input);
    toOpenAIStrictJsonSchema(input);
    expect(JSON.stringify(input)).toBe(before);
  });
});

describe("ensureNullable", () => {
  it("turns single-string type into [type, null]", () => {
    expect(ensureNullable({ type: "string" })).toEqual({ type: ["string", "null"] });
  });

  it("appends null to type arrays", () => {
    expect(ensureNullable({ type: ["string", "number"] })).toEqual({
      type: ["string", "number", "null"],
    });
  });

  it("does not double-append null", () => {
    expect(ensureNullable({ type: ["string", "null"] })).toEqual({
      type: ["string", "null"],
    });
  });

  it("appends null branch to anyOf if missing", () => {
    expect(ensureNullable({ anyOf: [{ type: "string" }] })).toEqual({
      anyOf: [{ type: "string" }, { type: "null" }],
    });
  });

  it("wraps const/enum/$ref schemas in anyOf with null", () => {
    expect(ensureNullable({ const: "x" })).toEqual({
      anyOf: [{ const: "x" }, { type: "null" }],
    });
    expect(ensureNullable({ enum: ["a", "b"] })).toEqual({
      anyOf: [{ enum: ["a", "b"] }, { type: "null" }],
    });
  });
});

describe("RoleOutputSchemas → strict JSON schema", () => {
  it("medical_instruction_extractor's normalized object lists every key in required and allows null", () => {
    const json = zodToJsonSchema(
      MedicalInstructionExtractorOutputSchema,
    ) as AnyObj;
    assertEveryObjectIsStrict(json);

    const facts = (json.properties as AnyObj).facts as AnyObj;
    expect(facts.type).toBe("array");
    const factItem = facts.items as AnyObj;
    expect(factItem.additionalProperties).toBe(false);
    expect((factItem.required as string[]).sort()).toEqual(
      [
        "fact_type",
        "original_text",
        "normalized",
        "missing_fields",
        "confidence",
        "requires_confirmation",
        "source_turn_ids",
      ].sort(),
    );

    const normalized = (factItem.properties as AnyObj).normalized as AnyObj;
    const expectedNormalizedKeys = [
      "medication_name",
      "dose",
      "frequency",
      "timing",
      "duration",
      "route",
      "date",
      "test_name",
      "condition",
    ];
    expect((normalized.required as string[]).sort()).toEqual(
      expectedNormalizedKeys.slice().sort(),
    );
    expect(normalized.additionalProperties).toBe(false);

    // Every normalized.* property must allow null.
    for (const k of expectedNormalizedKeys) {
      const prop = (normalized.properties as AnyObj)[k] as AnyObj;
      const allowsNull =
        prop.type === "null" ||
        (Array.isArray(prop.type) && (prop.type as string[]).includes("null")) ||
        (Array.isArray(prop.anyOf) &&
          (prop.anyOf as AnyObj[]).some(
            (b) =>
              b.type === "null" ||
              (Array.isArray(b.type) && (b.type as string[]).includes("null")),
          ));
      expect({ field: k, allowsNull }).toEqual({ field: k, allowsNull: true });
    }
  });

  it("every role output schema is OpenAI-strict-compatible", () => {
    for (const [role, schema] of Object.entries(RoleOutputSchemas)) {
      const json = zodToJsonSchema(schema as z.ZodTypeAny);
      try {
        assertEveryObjectIsStrict(json);
      } catch (err) {
        throw new Error(
          `role ${role} produced a non-strict schema: ${(err as Error).message}`,
        );
      }
    }
  });
});
