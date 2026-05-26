import { createParamDecorator, ExecutionContext } from '@nestjs/common';

export type AuthedUser = {
  id: string;
  email: string;
  role: 'PATIENT' | 'CLINICIAN' | 'CARETAKER' | 'ADMIN';
};

export const CurrentUser = createParamDecorator(
  (_: unknown, ctx: ExecutionContext): AuthedUser => {
    const req = ctx.switchToHttp().getRequest();
    return req.user as AuthedUser;
  },
);
