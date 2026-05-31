import { Injectable, Logger, ServiceUnavailableException } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';

/**
 * RealtimeService — mints short-lived client_secret values for the OpenAI
 * Realtime API. The browser uses the client_secret to open a WebRTC peer to
 * api.openai.com directly; the long-lived API key never leaves the server.
 *
 * Docs: https://platform.openai.com/docs/guides/realtime
 */
@Injectable()
export class RealtimeService {
  private readonly logger = new Logger(RealtimeService.name);

  constructor(private readonly cfg: ConfigService) {}

  get model(): string {
    // Configurable so we can move to gpt-realtime-1.5 / 2 / etc. later.
    return this.cfg.get<string>('OPENAI_REALTIME_MODEL') || 'gpt-realtime';
  }

  async mintEphemeralKey(): Promise<{ clientSecret: string; expiresAt: number }> {
    const apiKey = this.cfg.get<string>('OPENAI_API_KEY');
    if (!apiKey) {
      throw new ServiceUnavailableException(
        'OPENAI_API_KEY is not configured on the server',
      );
    }

    const resp = await fetch('https://api.openai.com/v1/realtime/sessions', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model: this.model,
        // Transcription-only: we want gpt-realtime to listen, not speak.
        modalities: ['text'],
      }),
    });

    if (!resp.ok) {
      const errText = await resp.text();
      this.logger.error(`Realtime session mint failed: ${resp.status} ${errText}`);
      throw new ServiceUnavailableException('Could not mint realtime session');
    }

    const data = (await resp.json()) as {
      client_secret: { value: string; expires_at: number };
    };
    return {
      clientSecret: data.client_secret.value,
      expiresAt: data.client_secret.expires_at,
    };
  }
}
