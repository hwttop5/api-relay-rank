import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const source = await readFile("lib/site-data.ts", "utf8");

assert.match(source, /return process\.env\.SITE_DATA_SOURCE\?\.trim\(\)\.toLowerCase\(\) \|\| "json"/);
assert.match(source, /siteDataSource\(\) === "postgres" && hasDatabaseUrl\(\)/);
assert.doesNotMatch(source, /if \(hasDatabaseUrl\(\)\) \{/);

console.log("site data source defaults to JSON and requires SITE_DATA_SOURCE=postgres for DB reads.");
