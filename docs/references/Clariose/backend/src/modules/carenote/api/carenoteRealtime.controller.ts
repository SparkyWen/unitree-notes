// CareNote realtime broker — separate from the legacy Clariose
// /api/realtime/sessions controller. Mounted at the singular route
// `/api/realtime/session` because (a) the spec calls for it and (b) the
// legacy plural route remains live for the consult product.

import { Body, Controller, Post, UseGuards } from "@nestjs/common";
import { AuthGuard } from "@nestjs/passport";
import { IsIn, IsString } from "class-validator";

import { CareNoteService } from "./carenote.service";
import { AuthedUser, CurrentUser } from "../../../common/decorators/current-user.decorator";

class CreateSessionDto {
  @IsString() visit_id!: string;
  @IsIn(["doctor_visit"]) mode!: "doctor_visit";
}

@UseGuards(AuthGuard("jwt"))
@Controller("realtime")
export class CareNoteRealtimeController {
  constructor(private readonly carenote: CareNoteService) {}

  @Post("session")
  async create(
    @Body() dto: CreateSessionDto,
    @CurrentUser() user: AuthedUser,
  ) {
    // CLARIOSE_V01: was previously unguarded — any logged-in user could mint
    // a realtime session bound to another user's visit_id. Enforce ownership.
    await this.carenote.ensureOwner(dto.visit_id, user.id);
    return this.carenote.mintRealtimeSession(dto.visit_id, dto.mode);
  }
}
