// REST endpoints for the user's notes/ directory. All under /api/recall/notes.

import {
  Body,
  Controller,
  Delete,
  Get,
  Param,
  Patch,
  Post,
  UseGuards,
} from "@nestjs/common";
import { AuthGuard } from "@nestjs/passport";
import {
  IsArray,
  IsBoolean,
  IsOptional,
  IsString,
  ValidateNested,
} from "class-validator";
import { Type } from "class-transformer";

import { CurrentUser, type AuthedUser } from "../../common/decorators/current-user.decorator";
import { RecallNotesService } from "./recallNotes.service";

class UploadFileDto {
  @IsString() filename!: string;
  @IsString() content!: string;
}

class UploadDto {
  @IsArray()
  @ValidateNested({ each: true })
  @Type(() => UploadFileDto)
  files!: UploadFileDto[];
}

class PatchDto {
  @IsOptional() @IsBoolean() pinned?: boolean;
  @IsOptional() @IsString() collection?: string | null;
  @IsOptional() @IsString() type?: string | null;
  @IsOptional() @IsArray() @IsString({ each: true }) tags?: string[];
  @IsOptional() @IsString() description?: string | null;
  @IsOptional() @IsString() title?: string;
}

@UseGuards(AuthGuard("jwt"))
@Controller("recall/notes")
export class RecallNotesController {
  constructor(private readonly notes: RecallNotesService) {}

  @Get()
  async list(@CurrentUser() user: AuthedUser) {
    return this.notes.list(user.id);
  }

  @Post()
  async upload(@CurrentUser() user: AuthedUser, @Body() dto: UploadDto) {
    return this.notes.upload(user.id, dto.files);
  }

  @Get(":slug/content")
  async readContent(@CurrentUser() user: AuthedUser, @Param("slug") slug: string) {
    return this.notes.readContent(user.id, slug);
  }

  @Patch(":slug")
  async patch(
    @CurrentUser() user: AuthedUser,
    @Param("slug") slug: string,
    @Body() dto: PatchDto,
  ) {
    return this.notes.patch(user.id, slug, dto);
  }

  @Delete(":slug")
  async remove(@CurrentUser() user: AuthedUser, @Param("slug") slug: string) {
    await this.notes.remove(user.id, slug);
    return { ok: true };
  }
}
