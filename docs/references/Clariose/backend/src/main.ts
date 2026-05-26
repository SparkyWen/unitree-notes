// Bootstrap entry-point for the Clariose API.
import 'reflect-metadata';
import { NestFactory } from '@nestjs/core';
import type { NestExpressApplication } from '@nestjs/platform-express';
import { ValidationPipe, Logger } from '@nestjs/common';
import { json, urlencoded } from 'express';
import helmet from 'helmet';
import { AppModule } from './app.module';

async function bootstrap() {
  const app = await NestFactory.create<NestExpressApplication>(AppModule, {
    bufferLogs: true,
  });

  // Behind nginx — trust the loopback proxy so req.ip and rate-limit keys are
  // the real client IP, not 127.0.0.1.
  app.getHttpAdapter().getInstance().set('trust proxy', 'loopback');

  // CLARIOSE_V01 §security — cap request bodies. Realtime events are tiny
  // (a few KB at most); 256 KB is comfortably above any legitimate request
  // and rejects accidental gigabyte payloads early.
  app.use(json({ limit: '256kb' }));
  app.use(urlencoded({ limit: '256kb', extended: true }));

  app.use(helmet({ contentSecurityPolicy: false }));
  app.setGlobalPrefix('api');
  app.useGlobalPipes(
    new ValidationPipe({
      whitelist: true,
      transform: true,
      // CLARIOSE_V01 §security — reject any field not on the DTO. Combined
      // with whitelist, this surfaces accidental client-side leaks (e.g.
      // posting `user_id` to /api/visits, which Week 1 made privileged).
      forbidNonWhitelisted: true,
    }),
  );

  // CLARIOSE_V01 §security — same-origin only in prod. nginx serves the
  // Nuxt site at https://zai.gold and proxies /api → 127.0.0.1; there is
  // no legitimate cross-origin caller. Allow * only in dev.
  const corsOrigin = process.env.NODE_ENV === 'production'
    ? (process.env.APP_BASE_URL || 'https://zai.gold')
    : true;
  app.enableCors({ origin: corsOrigin, credentials: true });

  const port = parseInt(process.env.APP_PORT || '4000', 10);
  await app.listen(port, '127.0.0.1');
  new Logger('Bootstrap').log(`Clariose API listening on http://127.0.0.1:${port}/api`);
}
bootstrap();
