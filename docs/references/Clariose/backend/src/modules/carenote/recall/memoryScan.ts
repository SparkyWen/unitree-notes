// CLARIOSE_V01 §4.2 Phase 1 — scan memory roots, parse frontmatter, build manifest.
//
// Visit-scoped + user-scoped roots are merged into a single manifest. Only
// `.md` files are considered. Frontmatter parsing is a tiny inline parser
// (no `gray-matter` dep) — we only need keywords / description / type.

import { Injectable, Logger } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { readFile, readdir, stat } from "node:fs/promises";
import { join, relative } from "node:path";

import {
  MEMORY_ROOT_DEFAULT,
} from "./recall.constants";
import type { ManifestEntry, MemoryScope, ScanResult } from "./recall.types";

type Frontmatter = {
  name?: string;
  description?: string;
  keywords?: string[];
  type?: string;
};

@Injectable()
export class MemoryScanService {
  private readonly logger = new Logger("MemoryScan");

  constructor(private readonly cfg: ConfigService) {}

  memoryRoot(): string {
    return this.cfg.get<string>("CARENOTE_MEMORY_ROOT") ?? MEMORY_ROOT_DEFAULT;
  }

  /**
   * Build manifest for one visit by walking both the visit-scoped and the
   * owner's user-scoped roots. user_id may be null in the rare case the
   * scope is unknown (we still walk the visit root).
   */
  async scanForVisit(visit_id: string, user_id: string | null): Promise<ScanResult> {
    const root = this.memoryRoot();
    const manifest: ManifestEntry[] = [];

    // Visit scope
    await this.walk(
      join(root, "visits", visit_id),
      "visit",
      root,
      manifest,
    );

    // User scope
    if (user_id) {
      await this.walk(
        join(root, "users", user_id),
        "user",
        root,
        manifest,
      );
    }

    return { manifest, generatedAt: Date.now() };
  }

  /** Recursive directory walk; parse frontmatter; push to manifest. */
  private async walk(
    dir: string,
    scope: MemoryScope,
    root: string,
    out: ManifestEntry[],
  ): Promise<void> {
    let entries: { name: string; isDir: boolean }[];
    try {
      const dirents = await readdir(dir, { withFileTypes: true });
      entries = dirents.map((d) => ({
        name: d.name,
        isDir: d.isDirectory(),
      }));
    } catch (err) {
      if ((err as NodeJS.ErrnoException).code === "ENOENT") return;
      this.logger.warn(`scan ${dir} failed: ${(err as Error).message}`);
      return;
    }
    for (const ent of entries) {
      if (ent.name.startsWith(".")) continue;
      const abs = join(dir, ent.name);
      if (ent.isDir) {
        await this.walk(abs, scope, root, out);
        continue;
      }
      if (!ent.name.endsWith(".md")) continue;
      try {
        const stats = await stat(abs);
        const content = await readFile(abs, "utf-8");
        const fm = parseFrontmatter(content);
        const body = stripFrontmatter(content);
        const description =
          fm.description?.trim() ||
          firstSentence(body) ||
          "(no description)";
        const name = fm.name?.trim() || ent.name.replace(/\.md$/, "");
        out.push({
          name,
          relPath: relative(root, abs),
          scope,
          keywords: (fm.keywords ?? []).map((k) => k.toLowerCase()),
          description,
          mtimeMs: stats.mtimeMs,
          bytes: stats.size,
          type: fm.type,
        });
      } catch (err) {
        this.logger.warn(`scan parse ${abs}: ${(err as Error).message}`);
      }
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Tiny inline frontmatter parser. Supports a flat top-level YAML-ish block
// of the form `key: value` and `key: [a, b, c]`. Anything more complex is
// ignored. We don't need full YAML for this use case.
// ─────────────────────────────────────────────────────────────────────────────

const FM_OPEN = /^---\s*\r?\n/;
const FM_CLOSE = /\r?\n---\s*\r?\n?/;

function parseFrontmatter(src: string): Frontmatter {
  if (!FM_OPEN.test(src)) return {};
  const afterOpen = src.replace(FM_OPEN, "");
  const closeIdx = afterOpen.search(FM_CLOSE);
  if (closeIdx < 0) return {};
  const block = afterOpen.slice(0, closeIdx);
  const out: Frontmatter = {};
  for (const lineRaw of block.split(/\r?\n/)) {
    const line = lineRaw.trim();
    if (!line || line.startsWith("#")) continue;
    const m = /^([A-Za-z0-9_-]+):\s*(.*)$/.exec(line);
    if (!m) continue;
    const key = m[1]!;
    const valRaw = m[2]!.trim();
    if (key === "keywords" || key === "tags") {
      out.keywords = parseListy(valRaw);
    } else if (key === "name") {
      out.name = unquote(valRaw);
    } else if (key === "description") {
      out.description = unquote(valRaw);
    } else if (key === "type") {
      out.type = unquote(valRaw);
    }
  }
  return out;
}

function stripFrontmatter(src: string): string {
  if (!FM_OPEN.test(src)) return src;
  const afterOpen = src.replace(FM_OPEN, "");
  const closeIdx = afterOpen.search(FM_CLOSE);
  if (closeIdx < 0) return src;
  return afterOpen.slice(closeIdx).replace(FM_CLOSE, "");
}

function parseListy(val: string): string[] {
  if (!val) return [];
  if (val.startsWith("[") && val.endsWith("]")) {
    return val
      .slice(1, -1)
      .split(",")
      .map((s) => unquote(s.trim()))
      .filter(Boolean);
  }
  return [unquote(val)];
}

function unquote(s: string): string {
  if (s.length >= 2) {
    const first = s[0];
    const last = s[s.length - 1];
    if ((first === '"' && last === '"') || (first === "'" && last === "'")) {
      return s.slice(1, -1);
    }
  }
  return s;
}

function firstSentence(body: string): string {
  const trimmed = body.trim();
  if (!trimmed) return "";
  const m = /^([^\.\n]{8,200})[\.\n]/.exec(trimmed);
  if (m) return m[1]!.trim();
  return trimmed.slice(0, 120);
}
