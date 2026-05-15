export function GET() {
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
      <rect width="64" height="64" rx="14" fill="#1f1a15"/>
      <rect x="12" y="14" width="40" height="8" rx="4" fill="#0f766e"/>
      <rect x="12" y="28" width="40" height="8" rx="4" fill="#1d4ed8"/>
      <rect x="12" y="42" width="28" height="8" rx="4" fill="#a16207"/>
    </svg>
  `.trim();

  return new Response(svg, {
    headers: {
      "content-type": "image/svg+xml; charset=utf-8",
      "cache-control": "public, max-age=86400"
    }
  });
}
