// CodexThreadStore — JSON-mirror persistence for per-(team, role) thread
// IDs and their prompt/schema versions.
//
// MVP uses a JSON file under `.data/carenote/`. The interface is shaped
// so a future Postgres-backed implementation can be dropped in without
// touching the rest of the harness.

import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

import type {
  CodexAgentRole,
  CodexAgentThreadState,
} from "../medical/medicalSchemas";

export interface CodexThreadStore {
  get(team_id: string, role: CodexAgentRole): Promise<CodexAgentThreadState | null>;
  upsert(rec: CodexAgentThreadState): Promise<void>;
  reset(team_id: string, role: CodexAgentRole, reason: string): Promise<void>;
  recordRun(team_id: string, role: CodexAgentRole, summary: string): Promise<void>;
  list(team_id: string): Promise<CodexAgentThreadState[]>;
}

type FileShape = {
  team_id: string;
  updated_at: string;
  agents: Record<string, CodexAgentThreadState>;
};

export class JsonFileCodexThreadStore implements CodexThreadStore {
  constructor(private readonly path: string) {}

  async get(team_id: string, role: CodexAgentRole): Promise<CodexAgentThreadState | null> {
    const file = await this.read(team_id);
    return file.agents[role] ?? null;
  }

  async upsert(rec: CodexAgentThreadState): Promise<void> {
    const file = await this.read(rec.team_id);
    file.agents[rec.role] = { ...rec, updated_at: new Date().toISOString() };
    file.updated_at = new Date().toISOString();
    await this.write(file);
  }

  async reset(team_id: string, role: CodexAgentRole, reason: string): Promise<void> {
    const file = await this.read(team_id);
    const cur = file.agents[role];
    if (!cur) return;
    file.agents[role] = {
      ...cur,
      thread_id: null,
      status: "reset",
      reset_reason: reason,
      updated_at: new Date().toISOString(),
    };
    file.updated_at = new Date().toISOString();
    await this.write(file);
  }

  async recordRun(team_id: string, role: CodexAgentRole, summary: string): Promise<void> {
    const file = await this.read(team_id);
    const cur = file.agents[role];
    if (!cur) return;
    file.agents[role] = {
      ...cur,
      last_run_at: new Date().toISOString(),
      last_summary: summary,
      updated_at: new Date().toISOString(),
    };
    file.updated_at = new Date().toISOString();
    await this.write(file);
  }

  async list(team_id: string): Promise<CodexAgentThreadState[]> {
    const file = await this.read(team_id);
    return Object.values(file.agents);
  }

  private async read(team_id: string): Promise<FileShape> {
    try {
      const raw = await readFile(this.path, "utf8");
      const parsed = JSON.parse(raw) as FileShape;
      if (parsed.team_id !== team_id) {
        // Cross-team contamination: treat as empty.
        return { team_id, updated_at: new Date().toISOString(), agents: {} };
      }
      return parsed;
    } catch {
      return { team_id, updated_at: new Date().toISOString(), agents: {} };
    }
  }

  private async write(file: FileShape): Promise<void> {
    await mkdir(dirname(this.path), { recursive: true });
    await writeFile(this.path, JSON.stringify(file, null, 2), "utf8");
  }
}

/** In-memory store. Useful for tests. */
export class InMemoryCodexThreadStore implements CodexThreadStore {
  private map = new Map<string, CodexAgentThreadState>();
  private key(team_id: string, role: CodexAgentRole): string {
    return `${team_id}::${role}`;
  }
  async get(team_id: string, role: CodexAgentRole): Promise<CodexAgentThreadState | null> {
    return this.map.get(this.key(team_id, role)) ?? null;
  }
  async upsert(rec: CodexAgentThreadState): Promise<void> {
    this.map.set(this.key(rec.team_id, rec.role), {
      ...rec,
      updated_at: new Date().toISOString(),
    });
  }
  async reset(team_id: string, role: CodexAgentRole, reason: string): Promise<void> {
    const cur = await this.get(team_id, role);
    if (!cur) return;
    await this.upsert({
      ...cur,
      thread_id: null,
      status: "reset",
      reset_reason: reason,
    });
  }
  async recordRun(team_id: string, role: CodexAgentRole, summary: string): Promise<void> {
    const cur = await this.get(team_id, role);
    if (!cur) return;
    await this.upsert({ ...cur, last_run_at: new Date().toISOString(), last_summary: summary });
  }
  async list(team_id: string): Promise<CodexAgentThreadState[]> {
    return [...this.map.values()].filter((s) => s.team_id === team_id);
  }
}
