import { NextResponse } from "next/server";

const backendBaseUrl =
  process.env.BACKEND_INTERNAL_BASE_URL ?? "http://backend:8000";

export async function GET() {
  try {
    const response = await fetch(
      `${backendBaseUrl}/api/v1/system/health/ready/`,
      {
        cache: "no-store"
      }
    );

    if (!response.ok) {
      throw new Error("backend not ready");
    }

    return NextResponse.json({
      status: "ok",
      service: "frontend"
    });
  } catch {
    return NextResponse.json(
      {
        status: "degraded",
        service: "frontend"
      },
      { status: 503 }
    );
  }
}
