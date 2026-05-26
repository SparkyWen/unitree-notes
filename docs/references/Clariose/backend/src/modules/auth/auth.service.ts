import {
  Injectable,
  UnauthorizedException,
  ConflictException,
  ForbiddenException,
} from '@nestjs/common';
import { JwtService } from '@nestjs/jwt';
import * as argon2 from 'argon2';
import { PrismaService } from '../../common/prisma/prisma.service';
import { UserRole } from '@prisma/client';

// argon2id parameters tuned for ~100ms on a modern server CPU. Tweak only with
// a benchmark — going lower weakens hashes, going higher denies-of-services
// the login endpoint.
const ARGON2_OPTS = {
  type: argon2.argon2id,
  memoryCost: 19_456, // 19 MiB
  timeCost: 2,
  parallelism: 1,
} as const;

// A pre-computed hash used to spend constant time on logins for unknown
// emails — prevents timing-based account enumeration.
let DUMMY_HASH: string | null = null;

@Injectable()
export class AuthService {
  constructor(private readonly prisma: PrismaService, private readonly jwt: JwtService) {}

  async register(
    input: { email: string; password: string; displayName: string; role: UserRole },
    ip?: string,
  ) {
    const existing = await this.prisma.user.findUnique({ where: { email: input.email } });
    if (existing) throw new ConflictException('Email already registered');

    const passwordHash = await argon2.hash(input.password, ARGON2_OPTS);

    const user = await this.prisma.user.create({
      data: {
        email: input.email,
        passwordHash,
        displayName: input.displayName,
        role: input.role,
        // PATIENT users get a Patient profile auto-created so sessions can attach to it.
        patientProfile:
          input.role === UserRole.PATIENT
            ? { create: { fullName: input.displayName } }
            : undefined,
        clinicianProfile:
          input.role === UserRole.CLINICIAN
            ? { create: { fullName: input.displayName } }
            : undefined,
      },
    });

    await this.audit(user.id, 'auth.register', ip);
    return this.issueToken(user);
  }

  async login(email: string, password: string, ip?: string) {
    const user = await this.prisma.user.findUnique({ where: { email } });

    // Always run a verify, even on a miss, so response time doesn't leak
    // whether the email exists.
    const ok = user
      ? await argon2.verify(user.passwordHash, password).catch(() => false)
      : await argon2.verify(await this.dummyHash(), password).catch(() => false);

    if (!user || !ok) {
      await this.audit(user?.id, 'auth.login.failed', ip, { email });
      throw new UnauthorizedException('Invalid credentials');
    }
    if (!user.isActive) {
      await this.audit(user.id, 'auth.login.disabled', ip);
      throw new ForbiddenException('Account is disabled');
    }

    // Lazy rehash if we ever bump argon2 params.
    if (argon2.needsRehash(user.passwordHash, ARGON2_OPTS)) {
      const passwordHash = await argon2.hash(password, ARGON2_OPTS);
      await this.prisma.user.update({ where: { id: user.id }, data: { passwordHash } });
    }

    await this.prisma.user.update({
      where: { id: user.id },
      data: { lastLoginAt: new Date() },
    });
    await this.audit(user.id, 'auth.login.ok', ip);
    return this.issueToken(user);
  }

  async me(userId: string) {
    const user = await this.prisma.user.findUnique({ where: { id: userId } });
    if (!user) throw new UnauthorizedException();
    return this.publicUser(user);
  }

  private async dummyHash(): Promise<string> {
    if (!DUMMY_HASH) {
      DUMMY_HASH = await argon2.hash('not-a-real-password', ARGON2_OPTS);
    }
    return DUMMY_HASH;
  }

  private async issueToken(user: {
    id: string;
    email: string;
    role: UserRole;
    displayName: string | null;
  }) {
    const token = await this.jwt.signAsync({
      sub: user.id,
      email: user.email,
      role: user.role,
    });
    return { token, user: this.publicUser(user) };
  }

  private publicUser(u: {
    id: string;
    email: string;
    role: UserRole;
    displayName: string | null;
  }) {
    return { id: u.id, email: u.email, role: u.role, displayName: u.displayName };
  }

  private async audit(
    userId: string | undefined,
    action: string,
    ip?: string,
    detail: Record<string, unknown> = {},
  ) {
    try {
      await this.prisma.auditLog.create({
        data: {
          userId: userId ?? null,
          action,
          ip: ip ?? null,
          detail: detail as any,
        },
      });
    } catch {
      // Audit failures must not block auth flow.
    }
  }
}
