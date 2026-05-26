// Transcript event bus.
//
// A minimal in-process pub/sub built on RxJS Subject. The interface is
// kept narrow so a future implementation can swap in BullMQ/Redis with
// no change to consumers.

import { Observable, Subject } from "rxjs";
import type { DoctorVisitTranscriptTurnCompleted } from "./realtimeEventTypes";

export interface TranscriptEventBus {
  publish(event: DoctorVisitTranscriptTurnCompleted): void;
  stream(visit_id?: string): Observable<DoctorVisitTranscriptTurnCompleted>;
  on(
    handler: (e: DoctorVisitTranscriptTurnCompleted) => void | Promise<void>,
  ): { unsubscribe: () => void };
}

export class InMemoryTranscriptEventBus implements TranscriptEventBus {
  private subject = new Subject<DoctorVisitTranscriptTurnCompleted>();

  publish(event: DoctorVisitTranscriptTurnCompleted): void {
    this.subject.next(event);
  }

  stream(visit_id?: string): Observable<DoctorVisitTranscriptTurnCompleted> {
    if (!visit_id) return this.subject.asObservable();
    return new Observable((subscriber) => {
      const sub = this.subject.subscribe({
        next: (e) => {
          if (e.visit_id === visit_id) subscriber.next(e);
        },
        error: (err) => subscriber.error(err),
        complete: () => subscriber.complete(),
      });
      return () => sub.unsubscribe();
    });
  }

  on(
    handler: (e: DoctorVisitTranscriptTurnCompleted) => void | Promise<void>,
  ): { unsubscribe: () => void } {
    const sub = this.subject.subscribe({
      next: async (e) => {
        try {
          await handler(e);
        } catch {
          // Subscribers must not crash the bus. Errors are swallowed; the
          // CodexRunManager logs its own errors via agent_runs.
        }
      },
    });
    return { unsubscribe: () => sub.unsubscribe() };
  }
}
