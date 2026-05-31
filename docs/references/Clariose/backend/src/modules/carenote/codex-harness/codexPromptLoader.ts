// codexPromptLoader — reads prompt files from disk relative to the repo
// root. Cached after first read. Returned as plain strings; the caller
// decides how to embed them.

import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

export class CodexPromptLoader {
  private cache = new Map<string, string>();
  private repoRoot: string;

  constructor(repoRoot: string) {
    this.repoRoot = repoRoot;
  }

  async load(promptFile: string): Promise<string> {
    const key = promptFile;
    const cached = this.cache.get(key);
    if (cached !== undefined) return cached;
    const abs = resolve(this.repoRoot, promptFile);
    const text = await readFile(abs, "utf8");
    this.cache.set(key, text);
    return text;
  }

  /** Test helper. */
  set(promptFile: string, body: string): void {
    this.cache.set(promptFile, body);
  }
}
