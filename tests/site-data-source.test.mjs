import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const source = await readFile("lib/site-data.ts", "utf8");
const appStartup = await readFile("deploy/start-app.sh", "utf8");
const schedulerStartup = await readFile("deploy/start-scheduler.sh", "utf8");
const refreshCron = await readFile("deploy/cron/refresh.cron", "utf8");

assert.match(source, /return process\.env\.SITE_DATA_SOURCE\?\.trim\(\)\.toLowerCase\(\) \|\| "json"/);
assert.match(source, /siteDataSource\(\) === "postgres" && hasDatabaseUrl\(\)/);
assert.doesNotMatch(source, /if \(hasDatabaseUrl\(\)\) \{/);
assert.match(appStartup, /\[ "\$\{SITE_DATA_SOURCE:-json\}" = "postgres" \]/);
assert.match(schedulerStartup, /\[ "\$\{SITE_DATA_SOURCE:-json\}" = "postgres" \]/);
assert.match(refreshCron, /SITE_DATA_SOURCE:-json/);
assert.match(refreshCron, /python scripts\/run_server_refresh\.py/);

console.log("site data source defaults to JSON and gates DB reads and refresh jobs behind SITE_DATA_SOURCE=postgres.");
