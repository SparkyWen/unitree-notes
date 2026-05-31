import { Controller, Get } from '@nestjs/common';

@Controller('health')
export class HealthController {
  @Get()
  status() {
    return { ok: true, service: 'clariose-api', time: new Date().toISOString() };
  }
}
