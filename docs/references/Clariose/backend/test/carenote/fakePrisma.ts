// Minimal in-memory PrismaService stand-in for carenote service tests.
// Implements only the surface that CareNoteService touches:
//   user.findUnique, patient.{findUnique,create}, consultSession.{create,findUnique,findMany,update}.
// Keeps test shape identical to a real Postgres without spinning up a DB.

import type { PrismaService } from "../../src/common/prisma/prisma.service";

type UserRow = { id: string; email: string; displayName: string | null };
type PatientRow = { id: string; userId: string; fullName: string };
type SessionRow = {
  id: string;
  ownerUserId: string;
  patientId: string;
  language: string | null;
  consentRecorded: boolean;
  rawAudioSaved: boolean;
  status: "ACTIVE" | "ENDED" | "ARCHIVED";
  startedAt: Date;
  endedAt: Date | null;
  durationSec: number;
  utteranceCount: number;
  visitState: object;
  summaryMd: string | null;
};

let cuidCounter = 0;
const nextCuid = (): string => `cuid_${++cuidCounter}_${Date.now().toString(36)}`;

export function makeFakePrisma(seedUsers: UserRow[] = [{ id: "u1", email: "u1@test", displayName: "U1" }]) {
  const users = new Map<string, UserRow>();
  const patientsById = new Map<string, PatientRow>();
  const patientsByUser = new Map<string, PatientRow>();
  const sessions = new Map<string, SessionRow>();

  for (const u of seedUsers) users.set(u.id, u);

  return {
    user: {
      findUnique: async ({ where }: { where: { id: string } }) =>
        users.get(where.id) ?? null,
    },
    patient: {
      findUnique: async ({ where }: { where: { userId: string } }) =>
        patientsByUser.get(where.userId) ?? null,
      create: async ({ data }: { data: { userId: string; fullName: string } }) => {
        const row: PatientRow = { id: nextCuid(), ...data };
        patientsById.set(row.id, row);
        patientsByUser.set(row.userId, row);
        return row;
      },
    },
    consultSession: {
      create: async ({ data }: { data: any }) => {
        const row: SessionRow = {
          id: nextCuid(),
          ownerUserId: data.ownerUserId,
          patientId: data.patientId,
          language: data.language ?? null,
          consentRecorded: data.consentRecorded ?? false,
          rawAudioSaved: data.rawAudioSaved ?? false,
          status: data.status ?? "ACTIVE",
          startedAt: new Date(),
          endedAt: null,
          durationSec: 0,
          utteranceCount: 0,
          visitState: data.visitState ?? {},
          summaryMd: null,
        };
        sessions.set(row.id, row);
        return row;
      },
      findUnique: async ({ where, select }: { where: { id: string }; select?: any }) => {
        const r = sessions.get(where.id);
        if (!r) return null;
        if (!select) return r;
        const out: any = {};
        for (const k of Object.keys(select)) if (select[k]) out[k] = (r as any)[k];
        return out;
      },
      findMany: async ({ where, orderBy: _o, take: _t, select: _s }: any) => {
        const rows = [...sessions.values()].filter(
          (r) => !where?.ownerUserId || r.ownerUserId === where.ownerUserId,
        );
        return rows;
      },
      update: async ({ where, data }: { where: { id: string }; data: any }) => {
        const r = sessions.get(where.id);
        if (!r) throw new Error(`session ${where.id} not found`);
        Object.assign(r, data);
        return r;
      },
    },
  } as unknown as PrismaService;
}
