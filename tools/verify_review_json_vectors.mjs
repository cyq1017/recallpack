import crypto from "node:crypto";
import fs from "node:fs";

const path = process.argv[2];
if (!path) throw new Error("usage: node verify_review_json_vectors.mjs <vectors.json>");
const vectors = JSON.parse(fs.readFileSync(path, "utf8"));

function canonicalize(value) {
  if (value === null || typeof value === "boolean" || typeof value === "string") {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("non-finite number");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonicalize).join(",")}]`;
  const fields = Object.keys(value)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${canonicalize(value[key])}`);
  return `{${fields.join(",")}}`;
}

for (const vector of vectors.vectors) {
  const canonical = canonicalize(vector.value);
  const digest = crypto.createHash("sha256").update(canonical, "utf8").digest("hex");
  if (canonical !== vector.canonical || digest !== vector.sha256) {
    throw new Error(`vector mismatch: ${vector.name}`);
  }
}

const timestampPattern = /^(?!0000)[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]Z$/;
function exactTimestamp(value) {
  if (!timestampPattern.test(value)) return false;
  const date = new Date(value);
  if (!Number.isFinite(date.valueOf())) return false;
  const iso = date.toISOString();
  return iso.slice(0, 19) + "Z" === value;
}
for (const value of vectors.timestamps.valid) {
  if (!exactTimestamp(value)) throw new Error(`valid timestamp rejected: ${value}`);
}
for (const value of vectors.timestamps.invalid) {
  if (exactTimestamp(value)) throw new Error(`invalid timestamp accepted: ${value}`);
}

console.log(`verified ${vectors.vectors.length} RFC 8785 vectors and timestamp boundaries`);
