// CodexSchemaValidator — validates parsed JSON against the role's Zod
// schema. Defence-in-depth on top of Codex's `outputSchema`.

import type { z } from "zod";

import { RoleOutputSchemas } from "../medical/medicalSchemas";
import type { CodexAgentRole } from "../medical/medicalSchemas";

export type ValidationResult<T = unknown> =
  | { ok: true; value: T }
  | { ok: false; errors: string[] };

export function validateRoleOutput<T = unknown>(
  role: CodexAgentRole,
  value: unknown,
): ValidationResult<T> {
  const schema = RoleOutputSchemas[role] as z.ZodSchema<T>;
  const r = schema.safeParse(value);
  if (r.success) return { ok: true, value: r.data };
  return {
    ok: false,
    errors: r.error.issues.map(
      (i: z.ZodIssue) => `${i.path.join(".") || "<root>"}: ${i.message}`,
    ),
  };
}
