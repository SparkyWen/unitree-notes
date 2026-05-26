// dream workspace tests — tree walk + path-sandboxed read.

import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ConfigService } from "@nestjs/config";

import { DreamWorkspace } from "../../src/modules/carenote/swarm/dream/dream.workspace";

function cfg(root: string): ConfigService {
  return {
    get: (k: string) => (k === "CARENOTE_MEMORY_ROOT" ? root : undefined),
  } as any;
}

describe("DreamWorkspace", () => {
  let tmp: string;
  beforeEach(async () => {
    tmp = await mkdtemp(join(tmpdir(), "dream-ws-"));
  });
  afterEach(async () => {
    await rm(tmp, { recursive: true, force: true });
  });

  it("walkTree returns sorted dir-then-file structure", async () => {
    const root = join(tmp, "users", "u1");
    await mkdir(join(root, "rollout_summaries"), { recursive: true });
    await mkdir(join(root, "skills"), { recursive: true });
    await writeFile(join(root, "MEMORY.md"), "# index\n");
    await writeFile(join(root, "memory_summary.md"), "# summary\n");
    await writeFile(join(root, "rollout_summaries", "v_abc.md"), "# v_abc\n");
    await writeFile(join(root, "skills", "med.md"), "# skill\n");

    const ws = new DreamWorkspace(cfg(tmp));
    const nodes = await ws.walkTree("u1");

    const names = nodes.map((n) => n.name);
    expect(names).toEqual([
      "rollout_summaries",
      "skills",
      "MEMORY.md",
      "memory_summary.md",
    ]);
    const rs = nodes.find((n) => n.name === "rollout_summaries")!;
    expect(rs.kind).toBe("dir");
    expect(rs.children!.map((c) => c.name)).toEqual(["v_abc.md"]);
    expect(rs.children![0].visitId).toBe("v_abc");
  });

  it("walkTree on missing root returns empty array (no throw)", async () => {
    const ws = new DreamWorkspace(cfg(tmp));
    expect(await ws.walkTree("nonexistent")).toEqual([]);
  });

  it("readFile returns content for in-bounds .md path", async () => {
    const root = join(tmp, "users", "u1");
    await mkdir(root, { recursive: true });
    await writeFile(join(root, "MEMORY.md"), "hello\n");

    const ws = new DreamWorkspace(cfg(tmp));
    const r = await ws.readFile("u1", "MEMORY.md");
    expect(r.content).toBe("hello\n");
    expect(r.bytes).toBe(6);
  });

  it("readFile rejects path traversal", async () => {
    const root = join(tmp, "users", "u1");
    await mkdir(root, { recursive: true });
    await writeFile(join(tmp, "secret.md"), "nope\n");

    const ws = new DreamWorkspace(cfg(tmp));
    await expect(ws.readFile("u1", "../secret.md")).rejects.toThrow(
      /outside workspace|extension/i,
    );
  });

  it("readFile rejects non-md extensions", async () => {
    const root = join(tmp, "users", "u1");
    await mkdir(root, { recursive: true });
    await writeFile(join(root, "secret.txt"), "nope\n");

    const ws = new DreamWorkspace(cfg(tmp));
    await expect(ws.readFile("u1", "secret.txt")).rejects.toThrow(/extension/i);
  });
});
