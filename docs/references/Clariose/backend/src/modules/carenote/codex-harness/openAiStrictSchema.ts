// openAiStrictSchema — recursively rewrite a JSON Schema so it is valid
// for OpenAI structured outputs in strict mode (used by `codex exec
// --output-schema` and the SDK's `outputSchema`).
//
// OpenAI strict mode requires:
//   1. Every object schema has additionalProperties: false.
//   2. Every key in `properties` is listed in `required`.
//   3. Optional fields cannot be modeled by omission from `required`;
//      they must be modeled as nullable types (e.g. `["string", "null"]`
//      or `anyOf: [..., { type: "null" }]`).
//   4. Rules apply recursively through nested objects and array `items`.
//
// We accept any JSON-Schema-shaped input and produce a deep-copied,
// strict-compatible variant. Original input is not mutated.

export type JsonSchemaLike = Record<string, unknown>;

const COMBINATORS = ["anyOf", "oneOf", "allOf"] as const;

export function toOpenAIStrictJsonSchema(schema: unknown): unknown {
  if (!isPlainObject(schema)) return schema;
  return normalize(schema);
}

function normalize(node: JsonSchemaLike): JsonSchemaLike {
  const out: JsonSchemaLike = { ...node };

  // Recurse through combinators first.
  for (const key of COMBINATORS) {
    const branches = out[key];
    if (Array.isArray(branches)) {
      out[key] = branches.map((b) =>
        isPlainObject(b) ? normalize(b) : b,
      );
    }
  }

  // $defs / definitions
  for (const key of ["$defs", "definitions"] as const) {
    const defs = out[key];
    if (isPlainObject(defs)) {
      const next: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(defs)) {
        next[k] = isPlainObject(v) ? normalize(v) : v;
      }
      out[key] = next;
    }
  }

  // Array items
  if (out.items !== undefined) {
    if (Array.isArray(out.items)) {
      out.items = (out.items as unknown[]).map((it) =>
        isPlainObject(it) ? normalize(it) : it,
      );
    } else if (isPlainObject(out.items)) {
      out.items = normalize(out.items);
    }
  }

  // additionalProperties as a schema (Zod record types) is incompatible
  // with OpenAI strict mode, which only accepts `additionalProperties:
  // false`. We close the object — the model must emit `{}` (or whatever
  // properties we explicitly list). This is a documented loss of
  // expressivity for `z.record()` outputs; downstream code already
  // accepts `{}` for those fields (`z.unknown()` parses anything).
  if (isPlainObject(out.additionalProperties)) {
    out.additionalProperties = false;
    if (!isPlainObject(out.properties)) {
      out.properties = {};
      out.required = [];
    }
  }

  // Object normalization — only when there is a `properties` map.
  const props = out.properties;
  if (isPlainObject(props)) {
    const existingRequired = new Set(
      Array.isArray(out.required) ? (out.required as string[]) : [],
    );
    const nextProps: Record<string, unknown> = {};
    const nextRequired: string[] = [];
    for (const [k, v] of Object.entries(props)) {
      let propSchema: unknown = isPlainObject(v) ? normalize(v) : v;
      // If this key was previously optional (not in required), promote
      // to required and make the property schema nullable so the model
      // can still signal "absent" by emitting null.
      if (!existingRequired.has(k)) {
        propSchema = ensureNullable(propSchema);
      }
      nextProps[k] = propSchema;
      nextRequired.push(k);
    }
    out.properties = nextProps;
    out.required = nextRequired;
    if (out.additionalProperties === undefined || out.additionalProperties === true) {
      out.additionalProperties = false;
    }
    if (out.type === undefined) out.type = "object";
  } else if (out.type === "object") {
    // Object with no declared properties — strict mode requires
    // properties + required + additionalProperties:false to all be
    // present even when empty.
    if (out.additionalProperties !== false) out.additionalProperties = false;
    if (!isPlainObject(out.properties)) out.properties = {};
    if (!Array.isArray(out.required)) out.required = [];
  }

  return out;
}

export function ensureNullable(schema: unknown): unknown {
  if (!isPlainObject(schema)) {
    // Unknown leaf — wrap as nullable union.
    return { anyOf: [schema, { type: "null" }] };
  }

  // anyOf / oneOf union — append null branch if missing.
  for (const key of ["anyOf", "oneOf"] as const) {
    const branches = schema[key];
    if (Array.isArray(branches)) {
      const hasNull = branches.some(
        (b) =>
          isPlainObject(b) &&
          (b.type === "null" ||
            (Array.isArray(b.type) && (b.type as unknown[]).includes("null"))),
      );
      if (hasNull) return schema;
      return { ...schema, [key]: [...branches, { type: "null" }] };
    }
  }

  // type: "x" → ["x", "null"]
  if (typeof schema.type === "string") {
    if (schema.type === "null") return schema;
    return { ...schema, type: [schema.type, "null"] };
  }
  // type: ["x", "y"] → add null if missing
  if (Array.isArray(schema.type)) {
    const arr = schema.type as string[];
    if (arr.includes("null")) return schema;
    return { ...schema, type: [...arr, "null"] };
  }

  // Schemas with no type but with const/enum/$ref — wrap in anyOf.
  if (
    schema.const !== undefined ||
    schema.enum !== undefined ||
    schema.$ref !== undefined
  ) {
    return { anyOf: [schema, { type: "null" }] };
  }

  // Empty schema or unknown shape — wrap.
  return { anyOf: [schema, { type: "null" }] };
}

function isPlainObject(v: unknown): v is JsonSchemaLike {
  return (
    typeof v === "object" &&
    v !== null &&
    !Array.isArray(v) &&
    Object.getPrototypeOf(v) === Object.prototype
  );
}
