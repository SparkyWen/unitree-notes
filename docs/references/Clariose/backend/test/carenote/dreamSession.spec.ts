// In-memory session registry tests.

import { DreamSessionRegistry } from "../../src/modules/carenote/swarm/dream/dream.session";

describe("DreamSessionRegistry", () => {
  it("openSession produces unique dreamIds and registers under userId", () => {
    const r = new DreamSessionRegistry();
    const a = r.openSession("u1", "all", 3);
    const b = r.openSession("u1", "visit:v_x", 1);
    expect(a.dreamId).not.toEqual(b.dreamId);
    expect(
      r
        .listForUser("u1")
        .map((s) => s.dreamId)
        .sort(),
    ).toEqual([a.dreamId, b.dreamId].sort());
  });

  it("recordEvent appends and ringBuffer caps at 20 entries", () => {
    const r = new DreamSessionRegistry();
    const s = r.openSession("u1", "all", 1);
    for (let i = 0; i < 30; i++) {
      r.recordEvent(s.dreamId, { phase: "gather", pct: i, at: i, note: `n${i}` });
    }
    const buf = r.replayBuffer(s.dreamId);
    expect(buf).toHaveLength(20);
    expect(buf[0].pct).toBe(10);
    expect(buf[19].pct).toBe(29);
  });

  it("closeSession marks ended and findOpen returns null", () => {
    const r = new DreamSessionRegistry();
    const s = r.openSession("u1", "all", 1);
    r.recordEvent(s.dreamId, { phase: "orient", pct: 10, at: 0 });
    r.closeSession(s.dreamId, "succeeded");
    const open = r.findOpen("u1");
    expect(open).toBeNull();
    expect(r.replayBuffer(s.dreamId)).toHaveLength(1);
  });
});
