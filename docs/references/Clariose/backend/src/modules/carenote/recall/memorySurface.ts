// CLARIOSE_V01 §4.2 Phase 3 — surface: read full content of selected files
// from disk, truncate per-file to MAX_BYTES_PER_FILE, compute freshness.

import { Injectable, Logger } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { readFile } from "node:fs/promises";
import { join, resolve } from "node:path";

import {
  MAX_BYTES_PER_FILE,
  MEMORY_ROOT_DEFAULT,
} from "./recall.constants";
import type { ManifestEntry, SurfacedFile } from "./recall.types";

@Injectable()
export class MemorySurfaceService {
  private readonly logger = new Logger("MemorySurface");

  constructor(private readonly cfg: ConfigService) {}

  private root(): string {
    return this.cfg.get<string>("CARENOTE_MEMORY_ROOT") ?? MEMORY_ROOT_DEFAULT;
  }

  async readForSurfacing(chosen: ManifestEntry[]): Promise<SurfacedFile[]> {
    // CLARIOSE_V01 §security — the manifest comes from our own scan so
    // entries are trustworthy by construction, but if a bad entry ever
    // slipped in (corrupted Redis cache, manual tampering) a `..` in
    // relPath could escape the memory root. Resolve and verify.
    const root = resolve(this.root());
    const out: SurfacedFile[] = [];
    for (const entry of chosen) {
      const absPath = resolve(join(root, entry.relPath));
      if (!absPath.startsWith(root + "/")) {
        this.logger.warn(
          `surface refused path-traversal: relPath=${entry.relPath}`,
        );
        continue;
      }
      try {
        const raw = await readFile(absPath, "utf-8");
        let content = raw;
        let truncated = false;
        if (Buffer.byteLength(raw, "utf8") > MAX_BYTES_PER_FILE) {
          content = sliceByByte(raw, MAX_BYTES_PER_FILE);
          truncated = true;
        }
        const freshDays = Math.floor(
          (Date.now() - entry.mtimeMs) / 86_400_000,
        );
        out.push({
          name: entry.name,
          relPath: entry.relPath,
          scope: entry.scope,
          absPath,
          content,
          truncated,
          freshDays,
          bytes: Buffer.byteLength(content, "utf8"),
        });
      } catch (err) {
        this.logger.warn(
          `surface read ${entry.relPath} failed: ${(err as Error).message}`,
        );
      }
    }
    return out;
  }
}

/** Slice a UTF-8 string to at most `maxBytes` without splitting a multi-byte
 *  codepoint (would corrupt CJK characters). Walks until we'd exceed the cap. */
function sliceByByte(s: string, maxBytes: number): string {
  if (Buffer.byteLength(s, "utf8") <= maxBytes) return s;
  let acc = 0;
  let end = 0;
  for (const ch of s) {
    const w = Buffer.byteLength(ch, "utf8");
    if (acc + w > maxBytes) break;
    acc += w;
    end += ch.length;
  }
  return s.slice(0, end);
}
