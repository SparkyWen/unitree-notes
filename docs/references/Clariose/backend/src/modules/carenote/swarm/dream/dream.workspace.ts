// Resolves a user's dream output directory and exposes safe read primitives.
// Path-sandboxed: every readFile call resolves through realpath and rejects
// anything that escapes the user's root. Only .md files are surfaced.
//
// Spec: docs/superpowers/specs/2026-04-30-dream-recall-design.md §6.2.

import { Injectable } from "@nestjs/common";
import { ConfigService } from "@nestjs/config";
import { promises as fs, type Stats } from "node:fs";
import { realpath } from "node:fs/promises";
import { extname, join, relative, resolve } from "node:path";

import type { TreeNode } from "./dream.types";

const MEMORY_ROOT_DEFAULT = "/home/ubuntu/Zai/.data/carenote/memory";
const MAX_FILE_BYTES = 512 * 1024;

@Injectable()
export class DreamWorkspace {
  constructor(private readonly cfg: ConfigService) {}

  rootForUser(userId: string): string {
    const root = this.cfg.get<string>("CARENOTE_MEMORY_ROOT") ?? MEMORY_ROOT_DEFAULT;
    return join(root, "users", userId);
  }

  async ensureRoot(userId: string): Promise<string> {
    const root = this.rootForUser(userId);
    await fs.mkdir(root, { recursive: true });
    return root;
  }

  /** Recursive directory walk. Returns dirs-first then files, both sorted by name. */
  async walkTree(userId: string): Promise<TreeNode[]> {
    const root = this.rootForUser(userId);
    try {
      await fs.access(root);
    } catch {
      return [];
    }
    return this.walk(root, "");
  }

  private async walk(absDir: string, relDir: string): Promise<TreeNode[]> {
    let entries: Array<{ name: string; isDir: boolean; isFile: boolean }>;
    try {
      const dirents = await fs.readdir(absDir, { withFileTypes: true });
      entries = dirents
        .filter((d) => !d.name.startsWith(".")) // hide .consolidation.lock, .dream-staging, etc
        .map((d) => ({
          name: d.name,
          isDir: d.isDirectory(),
          isFile: d.isFile(),
        }));
    } catch {
      return [];
    }
    entries.sort((a, b) => {
      if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
      // Case-sensitive ASCII sort so "MEMORY.md" (the index file) reliably
      // sorts before "memory_summary.md" — deterministic across locales.
      if (a.name < b.name) return -1;
      if (a.name > b.name) return 1;
      return 0;
    });

    const out: TreeNode[] = [];
    for (const e of entries) {
      const childRel = relDir ? `${relDir}/${e.name}` : e.name;
      const childAbs = join(absDir, e.name);
      if (e.isDir) {
        out.push({
          name: e.name,
          path: childRel,
          kind: "dir",
          children: await this.walk(childAbs, childRel),
        });
      } else if (e.isFile && e.name.endsWith(".md")) {
        const stat = await fs.stat(childAbs);
        const node: TreeNode = {
          name: e.name,
          path: childRel,
          kind: "file",
          mtime: stat.mtime.toISOString(),
          bytes: stat.size,
        };
        if (childRel.startsWith("rollout_summaries/")) {
          node.visitId = e.name.replace(/\.md$/, "");
        }
        out.push(node);
      }
    }
    return out;
  }

  /** Probe `rollout_summaries/<visitId>.md` for the visit picker. Returns
   *  the set of visit ids that already have a rollout summary file, so
   *  the sidebar can mark them with a "●" indicator without needing a
   *  separate stat() per visit. */
  async dreamedVisitIds(userId: string): Promise<Set<string>> {
    const root = this.rootForUser(userId);
    const dir = join(root, "rollout_summaries");
    try {
      const entries = await fs.readdir(dir);
      const ids = new Set<string>();
      for (const name of entries) {
        if (name.startsWith(".")) continue;
        if (!name.endsWith(".md")) continue;
        ids.add(name.replace(/\.md$/, ""));
      }
      return ids;
    } catch {
      return new Set();
    }
  }

  async readFile(
    userId: string,
    relPath: string,
  ): Promise<{ content: string; mtime: string; bytes: number; absPath: string }> {
    if (extname(relPath) !== ".md") {
      throw new Error(`disallowed extension: ${relPath}`);
    }
    // Lexical guard before any fs lookup — catches `../foo` and `/etc/foo`
    // even when the target file does not exist (realpath would 404 first).
    if (relPath.startsWith("/") || relPath.split("/").some((seg) => seg === "..")) {
      throw new Error(`path outside workspace: ${relPath}`);
    }
    const root = this.rootForUser(userId);
    const requested = resolve(root, relPath);
    let realRoot: string;
    let realFile: string;
    try {
      realRoot = await realpath(root);
    } catch {
      throw new Error(`workspace not initialized for user ${userId}`);
    }
    try {
      realFile = await realpath(requested);
    } catch {
      throw new Error(`file not found: ${relPath}`);
    }
    const rel = relative(realRoot, realFile);
    if (rel.startsWith("..") || rel.startsWith("/")) {
      throw new Error(`path outside workspace: ${relPath}`);
    }
    let stat: Stats;
    try {
      stat = await fs.stat(realFile);
    } catch {
      throw new Error(`file not found: ${relPath}`);
    }
    if (stat.size > MAX_FILE_BYTES) {
      throw new Error(`file too large: ${relPath}`);
    }
    const content = await fs.readFile(realFile, "utf-8");
    return {
      content,
      mtime: stat.mtime.toISOString(),
      bytes: stat.size,
      absPath: realFile,
    };
  }
}
