import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const inputPath = process.argv[2] ?? "analysis/stage2_translation_sheet_rows_20260827.json";
const outputDir = process.argv[3] ?? "outputs/20260827_translation_master";
const outputPath = `${outputDir}/ggen_advance_translation_master_20260827.xlsx`;
const previewPath = `${outputDir}/ggen_advance_translation_master_preview.png`;

const report = JSON.parse(await fs.readFile(inputPath, "utf8"));
const rows = report.records;
const summary = report.summary;
const pointer = report.pointer_plan;

const columns = [
  "record_id", "target_file_offset", "primary_category", "semantic_category",
  "storage_contract", "pointer_group", "source_text", "translation_ko",
  "translation_status", "translation_confidence", "source_decode_status",
  "source_unresolved_slots", "original_byte_length", "translated_byte_length",
  "byte_delta", "pointer_recalc_required", "pointer_owner_field_count",
  "source_families_text", "translator_notes", "raw_hex", "translated_raw_hex",
];

const valueOf = (row, column) => {
  if (column === "source_text") return row.source_text ?? row.decoded_text_seed ?? "";
  if (column === "source_unresolved_slots") return row.source_unresolved_slots ?? "";
  if (column === "source_families_text") return row.source_families_text ?? "";
  if (column === "raw_hex") return row.raw_hex ?? "";
  if (column === "translated_raw_hex") return row.translated_raw_hex ?? "";
  return row[column] ?? "";
};

const wb = Workbook.create();
const sheet = wb.worksheets.add("TranslationMaster");
sheet.showGridLines = false;

sheet.mergeCells("A1:U1");
sheet.getRange("A1").values = [["G Generation Advance 한국어 번역 마스터 · 정적 분석 / 32 MiB PoC"]];
sheet.getRange("A1:U1").format = {
  fill: "#17365D",
  font: { bold: true, color: "#FFFFFF", size: 14 },
  horizontalAlignment: "left",
  verticalAlignment: "center",
};
sheet.getRange("A1:U1").format.rowHeight = 28;

sheet.mergeCells("A2:U2");
sheet.getRange("A2").values = [[
  `원본 SHA-256: ${report.source.sha256} · production identity: ${report.record_identity_sha256} · translation content: ${report.translation_content_sha256}`,
]];
sheet.getRange("A3:U3").merge();
sheet.getRange("A3").values = [[
  `레코드 ${summary.records} · 번역 입력 ${summary.translated_rows} · 문자맵/검토 보류 ${summary.translation_status_counts.needs_charmap_resolution + summary.translation_status_counts.translated_font_pending + summary.translation_status_counts.needs_review} · 길이 변화 ${summary.byte_length_changed_rows}`,
]];
sheet.getRange("A4:U4").merge();
sheet.getRange("A4").values = [[
  `포인터 재계산: u32 owner ${pointer.pointer_recalculation.owner_u32_fields}개 + 상대 u16 ${pointer.pointer_recalculation.relative_u16_table_values}개 · PoC high-water ${pointer.text_region.high_water} · 검증 ${pointer.verification.result}`,
]];
sheet.getRange("A2:U4").format = {
  fill: "#EAF1F8",
  font: { color: "#1F2937", size: 10 },
  wrapText: true,
  verticalAlignment: "center",
};
sheet.getRange("A2:U4").format.rowHeight = 21;

const headerRow = 6;
const dataStart = headerRow + 1;
const dataEnd = dataStart + rows.length - 1;
sheet.getRange(`A${headerRow}:U${headerRow}`).values = [columns];
sheet.getRange(`A${headerRow}:U${headerRow}`).format = {
  fill: "#2F75B5",
  font: { bold: true, color: "#FFFFFF", size: 10 },
  wrapText: true,
  horizontalAlignment: "center",
  verticalAlignment: "center",
  borders: { preset: "all", style: "thin", color: "#B4C7E7" },
};
sheet.getRange(`A${headerRow}:U${headerRow}`).format.rowHeight = 32;

const matrix = rows.map((row) => columns.map((column) => valueOf(row, column)));
sheet.getRange(`A${dataStart}:U${dataEnd}`).values = matrix;
sheet.getRange(`A${dataStart}:U${dataEnd}`).format = {
  font: { color: "#1F2937", size: 9 },
  verticalAlignment: "top",
  wrapText: true,
};
sheet.getRange(`A${dataStart}:U${dataEnd}`).format.borders = {
  insideHorizontal: { style: "hair", color: "#D9E2F3" },
  bottom: { style: "hair", color: "#D9E2F3" },
};

// Numeric columns remain typed values for sorting/filtering in Excel.
sheet.getRange(`M${dataStart}:Q${dataEnd}`).format.numberFormat = "0";
sheet.getRange(`O${dataStart}:O${dataEnd}`).format.numberFormat = "+0;-0;0";
sheet.getRange(`P${dataStart}:P${dataEnd}`).format.horizontalAlignment = "center";
sheet.getRange(`I${dataStart}:I${dataEnd}`).format.horizontalAlignment = "center";
sheet.getRange(`J${dataStart}:J${dataEnd}`).format.horizontalAlignment = "center";

const table = sheet.tables.add(`A${headerRow}:U${dataEnd}`, true, "TranslationMasterTable");
table.style = "TableStyleMedium2";
table.showFilterButton = true;

sheet.freezePanes.freezeRows(headerRow);
sheet.freezePanes.freezeColumns(2);

const widths = {
  A: 22, B: 16, C: 24, D: 32, E: 38, F: 25, G: 34, H: 34,
  I: 25, J: 16, K: 17, L: 25, M: 14, N: 16, O: 11, P: 16,
  Q: 15, R: 34, S: 46, T: 48, U: 48,
};
for (const [column, width] of Object.entries(widths)) {
  sheet.getRange(`${column}1:${column}${dataEnd}`).format.columnWidth = width;
}

// Status/QA cues keep the one-sheet source of truth usable as an editing queue.
sheet.getRange(`I${dataStart}:I${dataEnd}`).conditionalFormats.add("containsText", {
  text: "translated",
  format: { fill: "#E2F0D9", font: { color: "#215E21" } },
});
sheet.getRange(`I${dataStart}:I${dataEnd}`).conditionalFormats.add("containsText", {
  text: "preserve",
  format: { fill: "#E7E6E6", font: { color: "#595959" } },
});
sheet.getRange(`I${dataStart}:I${dataEnd}`).conditionalFormats.add("containsText", {
  text: "needs_",
  format: { fill: "#FFF2CC", font: { color: "#7F6000" } },
});
sheet.getRange(`P${dataStart}:P${dataEnd}`).conditionalFormats.add("cellIs", {
  operator: "equal",
  formula: 1,
  format: { fill: "#FCE4D6", font: { bold: true, color: "#9C0006" } },
});

sheet.getRange(`I${dataStart}:I${dataEnd}`).dataValidation = {
  rule: { type: "list", values: ["translated", "translated_same", "translated_partial_charmap_preserved", "translated_font_pending", "needs_review", "needs_charmap_resolution", "preserve", "source_empty"] },
};

await fs.mkdir(outputDir, { recursive: true });

const inspect = await wb.inspect({
  kind: "table",
  range: `TranslationMaster!A1:U16`,
  include: "values,formulas",
  tableMaxRows: 16,
  tableMaxCols: 21,
  tableMaxCellChars: 120,
});
console.log(inspect.ndjson);
const errors = await wb.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "translation sheet formula error scan",
});
console.log(errors.ndjson);

const preview = await wb.render({
  sheetName: "TranslationMaster",
  range: "A1:U16",
  scale: 1,
  format: "png",
});
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));

const xlsx = await SpreadsheetFile.exportXlsx(wb);
await xlsx.save(outputPath);
console.log(JSON.stringify({ outputPath, previewPath, rows: rows.length, sheetCount: 1 }));
