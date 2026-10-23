// Validates portfolio data. Run locally with `npm run validate`;
// the same script runs in CI on every pull request.
import { readFileSync, existsSync } from "node:fs";
import Ajv from "ajv";
import addFormats from "ajv-formats";

const read = (p) => JSON.parse(readFileSync(new URL(p, import.meta.url), "utf8"));
const schema = read("../schema/project.schema.json");
const projectsFile = read("../src/data/projects.json");
const categoriesFile = read("../src/data/categories.json");

const errors = [];
const ajv = new Ajv({ allErrors: true });
addFormats(ajv);

if (!ajv.validate(schema, projectsFile)) {
  for (const e of ajv.errors) errors.push(`schema: ${e.instancePath || "/"} ${e.message}`);
}

const categoryIds = new Set(categoriesFile.categories.map((c) => c.id));
const seen = { id: new Set(), repoId: new Set(), url: new Set() };

for (const p of projectsFile.projects ?? []) {
  const where = `project "${p.id}"`;
  if (!categoryIds.has(p.primary_category)) errors.push(`${where}: unknown category "${p.primary_category}"`);
  for (const [key, value] of [["id", p.id], ["repoId", p.repository_id], ["url", p.repository_url?.toLowerCase()]]) {
    if (seen[key].has(value)) errors.push(`${where}: duplicate ${key} "${value}"`);
    seen[key].add(value);
  }
  if (p.image && !existsSync(new URL(`../public/${p.image}`, import.meta.url))) {
    errors.push(`${where}: image file "public/${p.image}" does not exist`);
  }
  const commits = new Set();
  for (const u of p.updates ?? []) {
    if (commits.has(u.commit)) errors.push(`${where}: duplicate timeline entry for commit ${u.commit.slice(0, 7)}`);
    commits.add(u.commit);
    if (u.date < p.created_at) errors.push(`${where}: update ${u.commit.slice(0, 7)} predates created_at`);
  }
  if (p.updates?.length && p.last_updated < p.updates.map((u) => u.date).sort().at(-1)) {
    errors.push(`${where}: last_updated is older than its newest update`);
  }
}

if (errors.length) {
  console.error(`Data validation failed (${errors.length}):`);
  for (const e of errors) console.error(`  - ${e}`);
  process.exit(1);
}
console.log(`OK: ${projectsFile.projects.length} projects, ${categoryIds.size} categories.`);
