import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile("lib/request-security.ts", "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;
const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
const { isSameOriginRequest } = await import(moduleUrl);

function withEnv(env, fn) {
  const previous = {};
  for (const key of Object.keys(env)) {
    previous[key] = process.env[key];
    if (env[key] === undefined) {
      delete process.env[key];
    } else {
      process.env[key] = env[key];
    }
  }
  try {
    fn();
  } finally {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = value;
      }
    }
  }
}

test("allows production origin when proxied request URL is internal", () => {
  withEnv(
    {
      NEXTAUTH_URL: undefined,
      NEXT_PUBLIC_SITE_URL: "https://apirank.ttop5.cc",
      APP_DOMAIN: undefined,
    },
    () => {
      const request = new Request("http://app:3000/api/station-reviews", {
        method: "POST",
        headers: {
          origin: "https://apirank.ttop5.cc",
        },
      });

      assert.equal(isSameOriginRequest(request), true);
    },
  );
});

test("allows forwarded host and protocol origin", () => {
  const request = new Request("http://app:3000/api/station-reviews", {
    method: "POST",
    headers: {
      origin: "https://apirank.ttop5.cc",
      "x-forwarded-proto": "https",
      "x-forwarded-host": "apirank.ttop5.cc",
    },
  });

  assert.equal(isSameOriginRequest(request), true);
});

test("rejects cross-site origin", () => {
  const request = new Request("http://app:3000/api/station-reviews", {
    method: "POST",
    headers: {
      origin: "https://evil.example",
      "x-forwarded-proto": "https",
      "x-forwarded-host": "apirank.ttop5.cc",
    },
  });

  assert.equal(isSameOriginRequest(request), false);
});

test("rejects malformed origin headers", () => {
  const request = new Request("http://app:3000/api/station-reviews", {
    method: "POST",
    headers: {
      origin: "https://apirank.ttop5.cc/path",
      "x-forwarded-proto": "https",
      "x-forwarded-host": "apirank.ttop5.cc",
    },
  });

  assert.equal(isSameOriginRequest(request), false);
});

test("allows requests without origin and rejects null origin", () => {
  const noOrigin = new Request("http://app:3000/api/station-reviews", { method: "POST" });
  const nullOrigin = new Request("http://app:3000/api/station-reviews", {
    method: "POST",
    headers: { origin: "null" },
  });

  assert.equal(isSameOriginRequest(noOrigin), true);
  assert.equal(isSameOriginRequest(nullOrigin), false);
});
