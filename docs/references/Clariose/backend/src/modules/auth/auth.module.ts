import { Module, Logger } from '@nestjs/common';
import { JwtModule } from '@nestjs/jwt';
import { PassportModule } from '@nestjs/passport';
import { ConfigService } from '@nestjs/config';

import { AuthService } from './auth.service';
import { AuthController } from './auth.controller';
import { JwtStrategy } from './jwt.strategy';

const DEV_FALLBACK = 'dev-only-secret-change-me-please-min-32-bytes!!';

function resolveJwtSecret(cfg: ConfigService): string {
  const secret = cfg.get<string>('JWT_SECRET');
  const env = cfg.get<string>('NODE_ENV');

  if (!secret || secret.length < 32) {
    if (env === 'production') {
      // Fail closed in production rather than silently using a weak key.
      throw new Error(
        'JWT_SECRET is missing or shorter than 32 characters. ' +
          'Generate one with: openssl rand -hex 48',
      );
    }
    Logger.warn(
      'JWT_SECRET missing or short — using dev fallback. Do NOT run this way in production.',
      'AuthModule',
    );
    return DEV_FALLBACK;
  }
  return secret;
}

@Module({
  imports: [
    PassportModule,
    JwtModule.registerAsync({
      inject: [ConfigService],
      useFactory: (cfg: ConfigService) => ({
        secret: resolveJwtSecret(cfg),
        signOptions: {
          expiresIn: '7d',
          issuer: 'clariose',
          audience: 'clariose-web',
        },
        verifyOptions: {
          issuer: 'clariose',
          audience: 'clariose-web',
        },
      }),
    }),
  ],
  controllers: [AuthController],
  providers: [AuthService, JwtStrategy],
  exports: [AuthService],
})
export class AuthModule {}
