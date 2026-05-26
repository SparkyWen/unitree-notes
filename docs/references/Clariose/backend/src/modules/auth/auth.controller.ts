import { Body, Controller, Get, Post, Req, UseGuards } from '@nestjs/common';
import { AuthGuard } from '@nestjs/passport';
import { Throttle } from '@nestjs/throttler';
import {
  IsEmail,
  IsEnum,
  IsString,
  Matches,
  MaxLength,
  MinLength,
} from 'class-validator';
import { Transform } from 'class-transformer';
import { UserRole } from '@prisma/client';
import type { Request } from 'express';

import { AuthService } from './auth.service';
import { CurrentUser, AuthedUser } from '../../common/decorators/current-user.decorator';

class RegisterDto {
  @Transform(({ value }) =>
    typeof value === 'string' ? value.trim().toLowerCase() : value,
  )
  @IsEmail()
  @MaxLength(254)
  email!: string;

  @IsString()
  @MinLength(10)
  @MaxLength(128)
  // Require letters AND digits — the cheapest meaningful complexity rule.
  // Don't compose enforcement with regex-only — class-validator runs both.
  @Matches(/[A-Za-z]/, { message: 'password must contain a letter' })
  @Matches(/\d/, { message: 'password must contain a digit' })
  password!: string;

  @IsString() @MinLength(1) @MaxLength(80) displayName!: string;
  @IsEnum(UserRole) role!: UserRole;
}

class LoginDto {
  @Transform(({ value }) =>
    typeof value === 'string' ? value.trim().toLowerCase() : value,
  )
  @IsEmail()
  @MaxLength(254)
  email!: string;

  @IsString() @MinLength(1) @MaxLength(128) password!: string;
}

function clientIp(req: Request): string | undefined {
  const fwd = req.headers['x-forwarded-for'];
  if (typeof fwd === 'string') return fwd.split(',')[0]!.trim();
  return req.ip ?? undefined;
}

@Controller('auth')
export class AuthController {
  constructor(private readonly auth: AuthService) {}

  // 5 attempts per minute per IP — defends against credential-stuffing without
  // locking out a typo-ing real user.
  @Throttle({ default: { limit: 5, ttl: 60_000 } })
  @Post('login')
  login(@Body() dto: LoginDto, @Req() req: Request) {
    return this.auth.login(dto.email, dto.password, clientIp(req));
  }

  // Registration is more expensive (argon2 hash) — keep it tighter.
  @Throttle({ default: { limit: 5, ttl: 60 * 60_000 } })
  @Post('register')
  register(@Body() dto: RegisterDto, @Req() req: Request) {
    return this.auth.register(dto, clientIp(req));
  }

  @UseGuards(AuthGuard('jwt'))
  @Get('me')
  me(@CurrentUser() user: AuthedUser) {
    return this.auth.me(user.id);
  }
}
