export function isSameOriginRequest(request: Request) {
  const origin = request.headers.get("origin");
  if (!origin) {
    return true;
  }
  return origin === new URL(request.url).origin;
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
