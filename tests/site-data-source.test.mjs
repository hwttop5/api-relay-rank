import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const siteDataSource = await readFile("lib/site-data.ts", "utf8");
const appStartup = await readFile("deploy/start-app.sh", "utf8");
const schedulerStartup = await readFile("deploy/start-scheduler.sh", "utf8");
const compose = await readFile("deploy/docker-compose.yml", "utf8");
const refreshCron = await readFile("deploy/cron/refresh.cron", "utf8");

assert.match(siteDataSource, /return process\.env\.SITE_DATA_SOURCE\?\.trim\(\)\.toLowerCase\(\) \|\| "json"/);
assert.match(siteDataSource, /siteDataSource\(\) === "postgres" && hasDatabaseUrl\(\)/);
assert.doesNotMatch(siteDataSource, /if \(hasDatabaseUrl\(\)\) \{/);

assert.match(appStartup, /\[ "\$\{SITE_DATA_SOURCE:-json\}" = "postgres" \]/);
assert.match(schedulerStartup, /\[ "\$\{SITE_DATA_SOURCE:-json\}" = "postgres" \]/);
assert.match(compose, /SITE_DATA_SOURCE: \$\{SITE_DATA_SOURCE:-postgres\}/);
assert.match(compose, /SITE_DATA_MERGE_POSTGRES_BASE: \$\{SITE_DATA_MERGE_POSTGRES_BASE:-1\}/);
assert.match(compose, /DATABASE_URL: postgresql:\/\/\$\{POSTGRES_USER\}:\$\{POSTGRES_PASSWORD\}@postgres:5432\/\$\{POSTGRES_DB\}/);
assert.match(refreshCron, /python scripts\/run_server_refresh\.py/);
assert.doesNotMatch(refreshCron, /SITE_DATA_SOURCE/);

console.log("site data defaults to JSON and only uses PostgreSQL when SITE_DATA_SOURCE=postgres.");
