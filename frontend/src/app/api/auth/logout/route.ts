import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { clearAuthCookie } from "@/lib/auth";

export async function POST() {
  const cookieStore = await cookies();
  clearAuthCookie(cookieStore);

  return NextResponse.json({ ok: true });
}
