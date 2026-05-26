import { Injectable } from '@nestjs/common';
import { PassportStrategy } from '@nestjs/passport';
import { ExtractJwt, Strategy } from 'passport-jwt';
import { ConfigService } from '@nestjs/config';

@Injectable()
export class JwtStrategy extends PassportStrategy(Strategy) {
  constructor(cfg: ConfigService) {
    const secret = cfg.get<string>('JWT_SECRET');
    super({
      // CLARIOSE_V01: EventSource cannot send Authorization headers, so SSE
      // endpoints (only) accept the JWT via ?token=... query param. All other
      // endpoints continue to require Authorization: Bearer ... — both
      // extractors are tried in order, header first.
      jwtFromRequest: ExtractJwt.fromExtractors([
        ExtractJwt.fromAuthHeaderAsBearerToken(),
        ExtractJwt.fromUrlQueryParameter('token'),
      ]),
      ignoreExpiration: false,
      secretOrKey:
        secret && secret.length >= 32
          ? secret
          : 'dev-only-secret-change-me-please-min-32-bytes!!',
      issuer: 'clariose',
      audience: 'clariose-web',
    });
  }

  async validate(payload: { sub: string; email: string; role: string }) {
    return { id: payload.sub, email: payload.email, role: payload.role };
  }
}
