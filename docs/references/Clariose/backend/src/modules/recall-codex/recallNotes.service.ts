// RecallNotes — file CRUD over the user's notes/ directory plus a Postgres
// row per note for fast listing. The on-disk file is the source of truth;
// the DB row mirrors metadata only.

import { Injectable, BadRequestException, NotFoundException } from "@nestjs/common";
import { promises as fs } from "node:fs";
import { join } from "node:path";

import { PrismaService } from "../../common/prisma/prisma.service";
import { FilesystemBootstrapper } from "./filesystemBootstrapper";
import {
  NOTE_ALLOWED_KINDS,
  NOTE_MAX_BYTES,
  type NoteKind,
} from "./recall.constants";
import type {
  RecallNoteView,
  RecallNotePatchRequest,
} from "./recall.types";

@Injectable()
export class RecallNotesService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly bootstrapper: FilesystemBootstrapper,
  ) {}

  async list(userId: string): Promise<RecallNoteView[]> {
    await this.bootstrapper.ensure(userId);
    const rows = await this.prisma.recallNote.findMany({
      where: { userId },
      orderBy: [{ pinned: "desc" }, { mtime: "desc" }],
    });
    return rows.map(toView);
  }

  async upload(
    userId: string,
    files: { filename: string; content: string }[],
  ): Promise<RecallNoteView[]> {
    if (!files?.length) throw new BadRequestException("no files supplied");
    const { root } = await this.bootstrapper.ensure(userId);
    const notesDir = join(root, "notes");

    for (const f of files) {
      validateUpload(f);
      const kind = extToKind(f.filename);
      const slug = slugify(stripExt(f.filename));
      const filename = `${slug}.${kind}`;
      const path = join(notesDir, filename);

      await fs.writeFile(path, f.content, "utf8");
      const stat = await fs.stat(path);
      const description = peekDescription(f.content);

      await this.prisma.recallNote.upsert({
        where: { userId_slug: { userId, slug } },
        create: {
          userId,
          slug,
          filename,
          kind,
          bytes: stat.size,
          mtime: stat.mtime,
          description,
        },
        update: {
          filename,
          kind,
          bytes: stat.size,
          mtime: stat.mtime,
          description,
        },
      });
    }
    return this.list(userId);
  }

  async readContent(
    userId: string,
    slug: string,
  ): Promise<{ note: RecallNoteView; content: string }> {
    const row = await this.prisma.recallNote.findUnique({
      where: { userId_slug: { userId, slug } },
    });
    if (!row) throw new NotFoundException("note not found");
    const { root } = await this.bootstrapper.ensure(userId);
    const path = join(root, "notes", row.filename);
    const content = await fs.readFile(path, "utf8");
    return { note: toView(row), content };
  }

  async patch(
    userId: string,
    slug: string,
    body: RecallNotePatchRequest,
  ): Promise<RecallNoteView> {
    const row = await this.prisma.recallNote.findUnique({
      where: { userId_slug: { userId, slug } },
    });
    if (!row) throw new NotFoundException("note not found");
    const updated = await this.prisma.recallNote.update({
      where: { userId_slug: { userId, slug } },
      data: {
        pinned: body.pinned ?? undefined,
        collection: body.collection === undefined ? undefined : body.collection,
        type: body.type === undefined ? undefined : body.type,
        tags: body.tags ?? undefined,
        description: body.description === undefined ? undefined : body.description,
      },
    });
    return toView(updated);
  }

  async remove(userId: string, slug: string): Promise<void> {
    const row = await this.prisma.recallNote.findUnique({
      where: { userId_slug: { userId, slug } },
    });
    if (!row) throw new NotFoundException("note not found");
    const { root } = await this.bootstrapper.ensure(userId);
    const path = join(root, "notes", row.filename);
    try {
      await fs.unlink(path);
    } catch {
      /* file may already be gone — DB row removal is the source of truth */
    }
    await this.prisma.recallNote.delete({
      where: { userId_slug: { userId, slug } },
    });
  }
}

function validateUpload(f: { filename: string; content: string }): void {
  if (!f.filename) throw new BadRequestException("filename required");
  if (typeof f.content !== "string") throw new BadRequestException("content must be string");
  const bytes = Buffer.byteLength(f.content, "utf8");
  if (bytes > NOTE_MAX_BYTES) {
    throw new BadRequestException(`${f.filename} exceeds ${NOTE_MAX_BYTES} bytes`);
  }
  const kind = extToKind(f.filename);
  if (!NOTE_ALLOWED_KINDS.includes(kind)) {
    throw new BadRequestException(`unsupported note kind: ${kind}`);
  }
}

function extToKind(filename: string): NoteKind {
  const m = /\.([^.]+)$/.exec(filename);
  const ext = (m?.[1] ?? "").toLowerCase();
  if (ext === "markdown") return "md";
  if (ext === "json" || ext === "ndjson") return "jsonl";
  return (ext as NoteKind);
}

function stripExt(filename: string): string {
  return filename.replace(/\.[^.]+$/, "");
}

function slugify(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9一-鿿]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64) || `note-${Date.now().toString(36)}`;
}

function peekDescription(content: string): string | null {
  // First non-blank, non-frontmatter line, truncated to 160 chars.
  const lines = content.split(/\n/);
  let inFrontmatter = false;
  for (const raw of lines) {
    const line = raw.trim();
    if (line === "---") {
      inFrontmatter = !inFrontmatter;
      continue;
    }
    if (inFrontmatter) continue;
    if (!line) continue;
    return line.replace(/^#+\s*/, "").slice(0, 160);
  }
  return null;
}

function toView(row: {
  slug: string;
  filename: string;
  kind: string;
  bytes: number;
  mtime: Date;
  pinned: boolean;
  collection: string | null;
  type: string | null;
  tags: string[];
  description: string | null;
}): RecallNoteView {
  return {
    slug: row.slug,
    filename: row.filename,
    title: stripExt(row.filename),
    kind: row.kind as NoteKind,
    bytes: row.bytes,
    mtime: row.mtime.toISOString(),
    pinned: row.pinned,
    collection: row.collection,
    type: row.type,
    tags: row.tags ?? [],
    description: row.description,
  };
}
