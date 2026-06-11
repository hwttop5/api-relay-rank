function normalizeOrigin(value: string | null | undefined, defaultProtocol = "https", strictOrigin = false) {
  const raw = value?.trim();
  if (!raw || raw === "null") {
    return null;
  }

  try {
    const withProtocol = /^[a-z][a-z0-9+.-]*:\/\//i.test(raw) ? raw : `${defaultProtocol}://${raw}`;
    const parsed = new URL(withProtocol);
    if (strictOrigin && parsed.href.replace(/\/$/, "") !== parsed.origin) {
      return null;
    }
    return parsed.origin;
  } catch {
    return null;
  }
}

function firstHeaderValue(value: string | null) {
  return value?.split(",")[0]?.trim() || null;
}

function addAllowedOrigin(origins: Set<string>, value: string | null | undefined, defaultProtocol?: string) {
  const origin = normalizeOrigin(value, defaultProtocol);
  if (origin) {
    origins.add(origin);
  }
}

function getAllowedOrigins(request: Request) {
  const origins = new Set<string>();
  const forwardedProto = firstHeaderValue(request.headers.get("x-forwarded-proto")) || "https";
  const forwardedHost = firstHeaderValue(request.headers.get("x-forwarded-host")) || firstHeaderValue(request.headers.get("host"));

  addAllowedOrigin(origins, request.url, forwardedProto);
  addAllowedOrigin(origins, forwardedHost, forwardedProto);
  addAllowedOrigin(origins, process.env.NEXTAUTH_URL);
  addAllowedOrigin(origins, process.env.NEXT_PUBLIC_SITE_URL);
  addAllowedOrigin(origins, process.env.APP_DOMAIN);

  return origins;
}

export function isSameOriginRequest(request: Request) {
  const origin = normalizeOrigin(request.headers.get("origin"), "https", true);
  if (!origin) {
    return !request.headers.has("origin");
  }
  return getAllowedOrigins(request).has(origin);
}

export function noindexJson(payload: unknown, init?: ResponseInit) {
  return Response.json(payload, {
    ...init,
    headers: {
      "X-Robots-Tag": "noindex",
      ...(init?.headers || {}),
    },
  });
}
