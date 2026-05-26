// In-memory state for active dream runs. Holds:
//   - dreamId → user / scope / status / phase
//   - per-dream ring buffer of last 20 progress events (for SSE replay-on-connect)
// Survives only as long as the Nest process. Persistence is in DreamRun rows.
//
// Spec: docs/superpowers/specs/2026-04-30-dream-recall-design.md §6.

import { Injectable } from "@nestjs/common";
import { randomUUID } from "node:crypto";

import type { DreamProgressEvent } from "./dream.types";

const RING_BUFFER_MAX = 20;

interface InternalSession {
  dreamId: string;
  userId: string;
  scope: string;
  visitCount: number;
  status: "running" | "succeeded" | "failed" | "cancelled";
  ringBuffer: DreamProgressEvent[];
  startedAt: number;
}

@Injectable()
export class DreamSessionRegistry {
  private readonly byId = new Map<string, InternalSession>();

  openSession(userId: string, scope: string, visitCount: number): { dreamId: string } {
    const dreamId = randomUUID();
    this.byId.set(dreamId, {
      dreamId,
      userId,
      scope,
      visitCount,
      status: "running",
      ringBuffer: [],
      startedAt: Date.now(),
    });
    return { dreamId };
  }

  recordEvent(dreamId: string, ev: DreamProgressEvent): void {
    const s = this.byId.get(dreamId);
    if (!s) return;
    s.ringBuffer.push(ev);
    if (s.ringBuffer.length > RING_BUFFER_MAX) {
      s.ringBuffer.splice(0, s.ringBuffer.length - RING_BUFFER_MAX);
    }
  }

  closeSession(dreamId: string, status: "succeeded" | "failed" | "cancelled"): void {
    const s = this.byId.get(dreamId);
    if (!s) return;
    s.status = status;
  }

  replayBuffer(dreamId: string): DreamProgressEvent[] {
    return this.byId.get(dreamId)?.ringBuffer.slice() ?? [];
  }

  listForUser(userId: string): InternalSession[] {
    return [...this.byId.values()].filter((s) => s.userId === userId);
  }

  /** Returns the most recent still-running session for this user, or null. */
  findOpen(userId: string): InternalSession | null {
    const open = this.listForUser(userId).filter((s) => s.status === "running");
    if (open.length === 0) return null;
    open.sort((a, b) => b.startedAt - a.startedAt);
    return open[0];
  }
}
