import { TranscriptAssembler } from "../../src/modules/carenote/realtime/transcriptAssembler";

describe("TranscriptAssembler", () => {
  test("appends deltas and emits on completed", () => {
    const a = new TranscriptAssembler();
    const visit = "v1";
    expect(a.apply(visit, { type: "input_audio_buffer.committed", item_id: "i1", previous_item_id: null })).toEqual([]);
    expect(a.apply(visit, {
      type: "conversation.item.input_audio_transcription.delta",
      item_id: "i1",
      delta: "hello ",
    })).toEqual([]);
    expect(a.apply(visit, {
      type: "conversation.item.input_audio_transcription.delta",
      item_id: "i1",
      delta: "world",
    })).toEqual([]);
    const emitted = a.apply(visit, {
      type: "conversation.item.input_audio_transcription.completed",
      item_id: "i1",
      transcript: "hello world",
    });
    expect(emitted).toHaveLength(1);
    expect(emitted[0]!.turn.transcript).toBe("hello world");
    expect(emitted[0]!.turn.ordering_confidence).toBe("high");
  });

  test("does not emit empty turns", () => {
    const a = new TranscriptAssembler();
    const out = a.apply("v1", {
      type: "conversation.item.input_audio_transcription.completed",
      item_id: "i1",
      transcript: "",
    });
    expect(out).toEqual([]);
  });

  test("reconstructs ordering from previous_item_id chain", () => {
    const a = new TranscriptAssembler();
    const v = "v1";
    // Out-of-order arrival.
    a.apply(v, { type: "input_audio_buffer.committed", item_id: "c", previous_item_id: "b" });
    a.apply(v, { type: "input_audio_buffer.committed", item_id: "a", previous_item_id: null });
    a.apply(v, { type: "input_audio_buffer.committed", item_id: "b", previous_item_id: "a" });
    a.apply(v, {
      type: "conversation.item.input_audio_transcription.completed",
      item_id: "c",
      transcript: "C",
    });
    a.apply(v, {
      type: "conversation.item.input_audio_transcription.completed",
      item_id: "a",
      transcript: "A",
    });
    a.apply(v, {
      type: "conversation.item.input_audio_transcription.completed",
      item_id: "b",
      transcript: "B",
    });
    const order = a.reconstructOrder(v);
    expect(order).toEqual(["a", "b", "c"]);
  });

  test("falls back to created_at order with low confidence when no chain", () => {
    const a = new TranscriptAssembler();
    const v = "v1";
    a.apply(v, {
      type: "conversation.item.input_audio_transcription.completed",
      item_id: "x",
      transcript: "X",
    });
    a.apply(v, {
      type: "conversation.item.input_audio_transcription.completed",
      item_id: "y",
      transcript: "Y",
    });
    expect(a.stats(v).ordering_confidence).toBe("low");
  });
});
