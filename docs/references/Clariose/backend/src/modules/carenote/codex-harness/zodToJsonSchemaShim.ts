// Minimal Zod → JSON Schema shim.
//
// We pass this output to Codex via `TurnOptions.outputSchema`. Codex
// forwards it to OpenAI as `response_format.json_schema` in strict mode,
// which has rules that plain JSON Schema doesn't enforce (every property
// must be in `required`, `additionalProperties` must be false, etc.). We
// post-process every output through `toOpenAIStrictJsonSchema` so the
// schema we actually hand to Codex satisfies those rules.
//
// Our own Zod re-validation in CodexSchemaValidator remains the safety
// net for the parsed model output.
//
// The shim tries to dynamic-import `zod-to-json-schema` if installed and
// falls back to a hand-rolled converter that covers the JSON-y subset we
// actually use (object, array, string, number, boolean, null, enum, union
// with literal/null, optional, nullable, default, record).

import type { ZodTypeAny } from "zod";

import { toOpenAIStrictJsonSchema } from "./openAiStrictSchema";

let cached: ((schema: ZodTypeAny) => Record<string, unknown>) | null = null;

export function zodToJsonSchema(schema: ZodTypeAny): Record<string, unknown> {
  if (!cached) {
    try {
      const req = Function("name", "return require(name)") as (n: string) => {
        zodToJsonSchema: (s: ZodTypeAny) => Record<string, unknown>;
      };
      const mod = req("zod-to-json-schema");
      cached = (s) => mod.zodToJsonSchema(s);
    } catch {
      cached = handRolled;
    }
  }
  const raw = cached(schema);
  return toOpenAIStrictJsonSchema(raw) as Record<string, unknown>;
}

function handRolled(schema: ZodTypeAny): Record<string, unknown> {
  const def = (schema as unknown as { _def: Record<string, unknown> })._def;
  const typeName = def.typeName as string;
  switch (typeName) {
    case "ZodString":
      return { type: "string" };
    case "ZodNumber":
      return { type: "number" };
    case "ZodBoolean":
      return { type: "boolean" };
    case "ZodNull":
      return { type: "null" };
    case "ZodLiteral": {
      // Strict mode requires `type` even for const schemas. Infer from
      // the literal value (we only ever use string/number/boolean
      // literals).
      const v = def.value;
      const t =
        typeof v === "string"
          ? "string"
          : typeof v === "number"
          ? "number"
          : typeof v === "boolean"
          ? "boolean"
          : v === null
          ? "null"
          : undefined;
      return t ? { type: t, const: v } : { const: v };
    }
    case "ZodEnum":
      return { type: "string", enum: def.values as string[] };
    case "ZodArray":
      return {
        type: "array",
        items: handRolled(def.type as ZodTypeAny),
      };
    case "ZodObject": {
      const shapeFn = def.shape as () => Record<string, ZodTypeAny>;
      const shape = shapeFn();
      const properties: Record<string, unknown> = {};
      const required: string[] = [];
      for (const [k, v] of Object.entries(shape)) {
        properties[k] = handRolled(v);
        // ZodDefault keeps the field required: the model is expected to
        // emit a concrete value (e.g. []) and Zod's `.default()` only
        // triggers on `undefined`, not on `null`. ZodOptional means the
        // field can semantically be absent, so we leave it out of
        // `required` here and let the strict normalizer promote it to
        // required-but-nullable.
        const innerName = (v as unknown as { _def: { typeName: string } })._def.typeName;
        if (innerName !== "ZodOptional") required.push(k);
      }
      const out: Record<string, unknown> = {
        type: "object",
        properties,
        additionalProperties: false,
      };
      if (required.length > 0) out.required = required;
      return out;
    }
    case "ZodOptional":
    case "ZodDefault":
      return handRolled(def.innerType as ZodTypeAny);
    case "ZodNullable": {
      const inner = handRolled(def.innerType as ZodTypeAny);
      return { anyOf: [inner, { type: "null" }] };
    }
    case "ZodUnion": {
      const opts = (def.options as ZodTypeAny[]).map(handRolled);
      return { anyOf: opts };
    }
    case "ZodRecord":
      return {
        type: "object",
        additionalProperties: handRolled(def.valueType as ZodTypeAny),
      };
    case "ZodUnknown":
    case "ZodAny":
      // OpenAI strict mode rejects empty `{}` schemas. We approximate
      // "any value" with a primitive-only type union (object/array
      // would themselves require fully-defined sub-schemas). Downstream
      // Zod validators are `z.unknown()`/`z.any()` which accept this.
      return { type: ["string", "number", "integer", "boolean", "null"] };
    default:
      return {};
  }
}
