import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { FileBlob, SpreadsheetFile } from "file:///C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const inputPath = path.join(root, "integrated", "translation", "ggen_advance_translation_master.xlsx");
const jsonPath = path.join(root, "integrated", "translation", "ggen_advance_translation_merged.json");
const outputDir = path.join(root, "outputs", "20260906_ggen_advance_sea_translation");
const outputPath = path.join(outputDir, "ggen_advance_translation_master_edited.xlsx");
const previewBefore = path.join(outputDir, "translationmaster_sea_before.png");
const previewAfter = path.join(outputDir, "translationmaster_sea_after.png");

const merged = JSON.parse(await fs.readFile(jsonPath, "utf8"));
const row = merged.records.find((item) => item.record_id === "GGA-TEXT-0018CF9C");
if (!row || row.translation_ko !== "바다" || row.translation_status !== "translated") {
  throw new Error("gate failed: canonical JSON Sea row is not updated");
}

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const sheet = workbook.worksheets.getItem("TranslationMaster");
await fs.mkdir(outputDir, { recursive: true });

const before = await workbook.render({ sheetName: "TranslationMaster", range: "L1823:AC1827", scale: 1, format: "png" });
await fs.writeFile(previewBefore, new Uint8Array(await before.arrayBuffer()));

const values = {
  N: row.source_text,
  P: row.translation_ko,
  Q: row.translation_status,
  R: row.translation_source,
  S: row.review_status,
  T: row.source_decode_status,
  U: JSON.stringify(row.source_unresolved_slots ?? []),
  Y: row.qa_status,
  Z: row.overlay_batch_id,
  AA: row.translator_notes,
  AC: row.translation_payload_sha256,
};
for (const [column, value] of Object.entries(values)) {
  sheet.getRange(`${column}1825`).values = [[value ?? ""]];
}

const check = await workbook.inspect({
  kind: "table",
  range: "TranslationMaster!N1825:AC1825",
  include: "values,formulas",
  tableMaxRows: 1,
  tableMaxCols: 16,
  tableMaxCellChars: 240,
});
console.log(check.ndjson);
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);

const after = await workbook.render({ sheetName: "TranslationMaster", range: "L1823:AC1827", scale: 1, format: "png" });
await fs.writeFile(previewAfter, new Uint8Array(await after.arrayBuffer()));
const exported = await SpreadsheetFile.exportXlsx(workbook);
await exported.save(outputPath);
console.log(JSON.stringify({ outputPath, previewBefore, previewAfter, recordId: row.record_id }, null, 2));
