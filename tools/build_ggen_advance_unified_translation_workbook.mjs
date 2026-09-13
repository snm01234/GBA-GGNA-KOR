#!/usr/bin/env node
/*
 * Export the current merged translation source as the one active workbook.
 * Historical date-stamped XLSX files stay under outputs for audit only; this
 * builder writes integrated/translation/ggen_advance_translation_master.xlsx.
 */
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SpreadsheetFile, Workbook } from "file:///C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";

const toolDir = path.dirname(fileURLToPath(import.meta.url));
const advanceRoot = path.resolve(toolDir, "..");
const defaultInput = path.join(advanceRoot, "integrated", "translation", "ggen_advance_translation_merged.json");
const defaultOutput = path.join(advanceRoot, "integrated", "translation", "ggen_advance_translation_master.xlsx");
const defaultPreviewDir = path.join(advanceRoot, "integrated", "translation", "previews");
const inputPath = path.resolve(process.argv[2] ?? defaultInput);
const outputPath = path.resolve(process.argv[3] ?? defaultOutput);
const previewDir = path.resolve(process.argv[4] ?? defaultPreviewDir);
const mode = process.argv[5] ?? "full";
const followupReportPath = path.join(advanceRoot, "analysis", "ggen_advance_measured_followup_20260829.json");
const glyphAuditPath = path.join(advanceRoot, "analysis", "ggen_advance_measured_glyph_corrections_20260829.json");

const merged = JSON.parse(await fs.readFile(inputPath, "utf8"));
if (!merged || !Array.isArray(merged.records)) {
  throw new Error("gate failed: merged translation JSON has no records array");
}

const stringify = (value) => {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value) || typeof value === "object") return JSON.stringify(value);
  return value;
};

const columns = [
  "record_id", "source_scope", "scope_status", "record_kind", "alias_of",
  "target_file_offset", "target_address", "semantic_category", "storage_contract",
  "relocation_schema", "pointer_group", "translation_unit_id", "context_bundle_id",
  "source_text", "baseline_translation_ko", "translation_ko", "translation_status",
  "translation_source", "review_status", "source_decode_status", "source_unresolved_slots",
  "original_byte_length", "pointer_recalc_required", "owner_count", "qa_status",
  "overlay_batch_id", "translator_notes", "raw_hex", "translation_payload_sha256",
  "source_families", "source_types", "control_signature", "segments", "translation_segments",
  "source_fingerprint",
];

const valueOf = (row, column) => stringify(row[column]);
const matrix = (rows, fields) => rows.map((row) => fields.map((field) => valueOf(row, field)));

function columnLetter(number) {
  let value = number;
  let result = "";
  while (value > 0) {
    const remainder = (value - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    value = Math.floor((value - 1) / 26);
  }
  return result;
}

function title(sheet, range, text) {
  sheet.mergeCells(range);
  sheet.getRange(range.split(":")[0]).values = [[text]];
  sheet.getRange(range).format = {
    fill: "#17365D",
    font: { bold: true, color: "#FFFFFF", size: 14 },
    horizontalAlignment: "left",
    verticalAlignment: "center",
  };
  sheet.getRange(range).format.rowHeight = 28;
}

function header(sheet, range) {
  sheet.getRange(range).format = {
    fill: "#2F75B5",
    font: { bold: true, color: "#FFFFFF", size: 10 },
    wrapText: true,
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: { preset: "all", style: "thin", color: "#B4C7E7" },
  };
  sheet.getRange(range).format.rowHeight = 32;
}

function dataStyle(sheet, range) {
  // Keep the large data blocks unstyled.  The artifact model stores cell-level
  // formatting eagerly; styling 20k+ rows makes XLSX export exceed the heap.
  // Header/title styling and column widths still keep the workbook navigable.
}

function applyWidths(sheet, widths, _lastRow) {
  for (const [column, width] of Object.entries(widths)) {
    // A one-cell anchor applies the column width without materializing a
    // formatted range for every data row.
    sheet.getRange(`${column}1:${column}1`).format.columnWidth = width;
  }
}

async function buildFollowupWorkbook() {
  const followup = JSON.parse(await fs.readFile(followupReportPath, "utf8"));
  const glyphAudit = JSON.parse(await fs.readFile(glyphAuditPath, "utf8"));
  const changes = Array.isArray(followup.records) ? followup.records : [];
  const sourceRecords = new Map(merged.records.map((row) => [String(row.record_id), row]));

  const wb = Workbook.create();
  const summarySheet = wb.worksheets.add("Summary");
  const correctionsSheet = wb.worksheets.add("Corrections");
  const auditSheet = wb.worksheets.add("JapaneseAudit");
  const glyphSheet = wb.worksheets.add("GlyphEvidence");
  for (const sheet of [summarySheet, correctionsSheet, auditSheet, glyphSheet]) {
    sheet.showGridLines = false;
  }

  const correctionColumns = [
    "record_id", "source_scope", "target_file_offset", "source_before", "source_after",
    "translation_before", "translation_after", "changes", "translation_status", "translation_segments_after",
  ];
  const correctionRows = changes.map((row) => [
    row.record_id ?? "", row.source_scope ?? "", row.target_file_offset ?? "", row.source_before ?? "",
    row.source_after ?? "", row.translation_before ?? "", row.translation_after ?? "",
    row.changes ?? [], sourceRecords.get(String(row.record_id))?.translation_status ?? "",
    row.translation_segments_after ?? [],
  ]);
  const correctionEnd = 6 + correctionRows.length;

  const auditColumns = ["evidence", "screenshot_text", "record_id", "source_text", "translation_ko", "status", "action"];
  const auditRows = [];
  const classification = glyphAudit.screenshot_classification ?? {};
  for (const recordId of classification.translated_records_already_in_unified_sheet ?? []) {
    const row = sourceRecords.get(String(recordId)) ?? {};
    auditRows.push([
      "attached capture", "", recordId, row.source_text ?? "", row.translation_ko ?? "",
      "already in active unified scope", "included in 20260836 rebuild",
    ]);
  }
  for (const screenshotText of classification.not_found_in_active_unified_scope ?? []) {
    auditRows.push([
      "attached capture", screenshotText, "", "", "", "active scope not found",
      "kept in audit only; no ROM patch without verified owner/pointer contract",
    ]);
  }
  const tail = classification.tail_probe_not_promoted;
  if (tail) {
    auditRows.push([
      "tail probe", tail.raw_prefix ?? "", "", displayHex(tail.file_offset), "", "not promoted",
      tail.reason ?? "",
    ]);
  }
  const auditEnd = 6 + auditRows.length;

  const glyphColumns = ["font_mode", "slot", "previous_decode", "corrected_decode", "dictionary_token", "expanded_slots", "next_slot_decode", "bitmap_observation"];
  function displayHex(value) {
    const text = String(value ?? "");
    return /^0x/i.test(text) ? `hex ${text}` : text;
  }
  const glyphRows = (glyphAudit.corrections ?? []).map((row) => [
    row.font_mode ?? "", displayHex(row.slot), row.previous_decode ?? "", row.corrected_decode ?? "",
    displayHex(row.basis?.dictionary_token), row.basis?.expanded_slots ?? [], row.basis?.next_slot_decode ?? "",
    row.basis?.bitmap_observation ?? "",
  ]);
  const glyphEnd = 6 + glyphRows.length;

  title(summarySheet, "A1:H1", "G Generation Advance · 실측 후속 감사");
  summarySheet.mergeCells("A2:H2");
  summarySheet.getRange("A2").values = [[
    "전체 정본은 integrated/translation/ggen_advance_translation_merged.json이며, 이 workbook은 이번 실측 수정·글리프 판독·미소유 일본어 문자열만 추적합니다.",
  ]];
  summarySheet.mergeCells("A3:H3");
  summarySheet.getRange("A3").values = [[
    `batch ${followup.batch_id ?? ""} · identity ${followup.identity_sha256 ?? ""} · source ${merged.source?.sha256 ?? ""}`,
  ]];
  summarySheet.getRange("A2:H3").format = { fill: "#EAF1F8", font: { color: "#1F2937", size: 10 }, wrapText: true, verticalAlignment: "center" };
  summarySheet.getRange("A2:H3").format.rowHeight = 28;
  summarySheet.getRange("A5:C5").values = [["항목", "값", "근거 / 사용 방법"]];
  header(summarySheet, "A5:C5");
  const summaryRows = [
    ["변경 record", `=COUNTA('Corrections'!$A$7:$A$${correctionEnd})`, "실측 후속에서 변경된 행"],
    ["번역 변경", `=COUNTIF('Corrections'!$I$7:$I$${correctionEnd},\"translated\")`, "1인칭/인물명/문맥 교정 포함"],
    ["스크린샷 감사 행", `=COUNTA('JapaneseAudit'!$A$7:$A$${auditEnd})`, "이미 통합됨·미소유·tail 보류"],
    ["판독 글리프", `=COUNTA('GlyphEvidence'!$A$7:$A$${glyphEnd})`, "12x12/8x16 공통 토큰 근거"],
    ["대사 폭 제한", 15, "map-script 세그먼트 최대 셀 수"],
    ["ROM 후보", "outputs/20260829_ggen_advance_unified_rom/ggen_advance_unified_translation_poc_20260836.gba", "검증 후 main TIP 승격 대상"],
    ["통합 JSON", path.relative(advanceRoot, inputPath).replaceAll(path.sep, "/"), "전체 record 정본"],
  ];
  summarySheet.getRange(`A6:C${5 + summaryRows.length}`).values = summaryRows.map(([label, value, note]) => [label, typeof value === "string" && value.startsWith("=") ? null : value, note]);
  summaryRows.forEach(([, value], index) => {
    if (typeof value === "string" && value.startsWith("=")) summarySheet.getRange(`B${6 + index}`).formulas = [[value]];
  });
  summarySheet.mergeCells("A15:H15");
  summarySheet.getRange("A15").values = [[glyphAudit.semantic_result ?? ""]];
  summarySheet.getRange("A15:H15").format = { fill: "#FFF2CC", font: { color: "#7F6000", size: 10 }, wrapText: true, verticalAlignment: "center" };
  summarySheet.getRange("A15:H15").format.rowHeight = 28;
  summarySheet.freezePanes.freezeRows(5);
  applyWidths(summarySheet, { A: 24, B: 72, C: 66, D: 14, E: 14, F: 14, G: 14, H: 14 }, 15);

  title(correctionsSheet, "A1:J1", "Corrections · measured follow-up rows");
  correctionsSheet.mergeCells("A2:J2");
  correctionsSheet.getRange("A2").values = [["원문 판독 보정과 번역 보정을 함께 기록합니다. translation_before/after는 재현 가능한 검토용 snapshot입니다."]];
  correctionsSheet.getRange("A2:J2").format = { fill: "#EAF1F8", font: { color: "#1F2937", size: 10 }, wrapText: true };
  correctionsSheet.getRange("A6:J6").values = [correctionColumns];
  header(correctionsSheet, "A6:J6");
  correctionsSheet.getRange(`A7:J${correctionEnd}`).values = correctionRows.map((row) => row.map(stringify));
  correctionsSheet.freezePanes.freezeRows(6);
  correctionsSheet.freezePanes.freezeColumns(2);
  applyWidths(correctionsSheet, { A: 28, B: 22, C: 18, D: 42, E: 42, F: 42, G: 42, H: 30, I: 18, J: 42 }, correctionEnd);

  title(auditSheet, "A1:G1", "JapaneseAudit · screenshot classification");
  auditSheet.mergeCells("A2:G2");
  auditSheet.getRange("A2").values = [["첨부 이미지와 active unified scope를 대조한 결과입니다. owner/pointer 계약이 없는 문구는 추측 번역으로 ROM에 삽입하지 않았습니다."]];
  auditSheet.getRange("A2:G2").format = { fill: "#EAF1F8", font: { color: "#1F2937", size: 10 }, wrapText: true };
  auditSheet.getRange("A6:G6").values = [auditColumns];
  header(auditSheet, "A6:G6");
  auditSheet.getRange(`A7:G${auditEnd}`).values = auditRows.map((row) => row.map(stringify));
  auditSheet.freezePanes.freezeRows(6);
  applyWidths(auditSheet, { A: 20, B: 42, C: 28, D: 54, E: 54, F: 28, G: 72 }, auditEnd);

  title(glyphSheet, "A1:H1", "GlyphEvidence · ボク/1인칭 판독 근거");
  glyphSheet.mergeCells("A2:H2");
  glyphSheet.getRange("A2").values = [[glyphAudit.semantic_result ?? ""]];
  glyphSheet.getRange("A2:H2").format = { fill: "#EAF1F8", font: { color: "#1F2937", size: 10 }, wrapText: true };
  glyphSheet.getRange("A6:H6").values = [glyphColumns];
  header(glyphSheet, "A6:H6");
  glyphSheet.getRange(`A7:H${glyphEnd}`).values = glyphRows.map((row) => row.map(stringify));
  glyphSheet.freezePanes.freezeRows(6);
  applyWidths(glyphSheet, { A: 16, B: 14, C: 18, D: 18, E: 20, F: 24, G: 20, H: 64 }, glyphEnd);

  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.mkdir(previewDir, { recursive: true });
  const summaryInspect = await wb.inspect({ kind: "table", range: "Summary!A1:C13", include: "values,formulas", tableMaxRows: 13, tableMaxCols: 3, tableMaxCellChars: 140 });
  console.log(summaryInspect.ndjson);
  const formulaErrors = await wb.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 300 },
    summary: "final formula error scan",
  });
  console.log(formulaErrors.ndjson);
  for (const [sheetName, range, fileName] of [
    ["Summary", "A1:H15", "summary_preview.png"],
    ["Corrections", "A1:J16", "corrections_preview.png"],
    ["JapaneseAudit", "A1:G18", "japanese_audit_preview.png"],
    ["GlyphEvidence", "A1:H10", "glyph_evidence_preview.png"],
  ]) {
    const preview = await wb.render({ sheetName, range, scale: 1, format: "png" });
    await fs.writeFile(path.join(previewDir, fileName), new Uint8Array(await preview.arrayBuffer()));
  }
  const xlsx = await SpreadsheetFile.exportXlsx(wb);
  await xlsx.save(outputPath);
  console.log(JSON.stringify({ outputPath, previewDir, mode: "followup", changes: changes.length, auditRows: auditRows.length, glyphRows: glyphRows.length }, null, 2));
}

if (mode === "followup") {
  await buildFollowupWorkbook();
  process.exit(0);
}

const rows = merged.records;
const owners = Array.isArray(merged.owners) ? merged.owners : [];
const exclusions = Array.isArray(merged.exclusions) ? merged.exclusions : [];
const scenarioRows = rows.filter((row) => row.source_scope === "scenario_main");
const overlayFiles = merged.merge?.overlay_files ?? [];

const wb = Workbook.create();
const summarySheet = wb.worksheets.add("Summary");
const translationSheet = wb.worksheets.add("TranslationMaster");
const ownerSheet = wb.worksheets.add("OwnerIndex");
const excludedSheet = wb.worksheets.add("Excluded");
const controlSheet = wb.worksheets.add("ControlSpec");
const batchSheet = wb.worksheets.add("BatchLog");
for (const sheet of [summarySheet, translationSheet, ownerSheet, excludedSheet, controlSheet, batchSheet]) {
  sheet.showGridLines = false;
}

// Summary
title(summarySheet, "A1:H1", "G Generation Advance · 통합 번역 정본");
summarySheet.mergeCells("A2:H2");
summarySheet.getRange("A2").values = [[
  "이 통합 workbook은 integrated/translation의 병합 JSON을 단일 편집·검토 기준으로 표시합니다. outputs/ 날짜별 XLSX는 역사 산출물입니다.",
]];
summarySheet.mergeCells("A3:H3");
summarySheet.getRange("A3").values = [[
  `원본 ROM SHA-256 ${merged.source?.sha256 ?? ""} · record identity ${merged.identity?.record_identity_sha256 ?? ""} · overlay identity ${merged.identity?.translation_overlay_identity_sha256 ?? ""}`,
]];
summarySheet.getRange("A2:H3").format = {
  fill: "#EAF1F8",
  font: { color: "#1F2937", size: 10 },
  wrapText: true,
  verticalAlignment: "center",
};
summarySheet.getRange("A2:H3").format.rowHeight = 26;
summarySheet.getRange("A5:C5").values = [["항목", "값", "근거 / 사용 방법"]];
header(summarySheet, "A5:C5");
const summaryRows = [
  ["원본 ROM", merged.source?.file ?? "", "원본 identity gate"],
  ["병합 JSON", path.relative(advanceRoot, inputPath).replaceAll(path.sep, "/"), "이 workbook의 단일 입력"],
  ["정본 workbook", path.relative(advanceRoot, outputPath).replaceAll(path.sep, "/"), "후속 번역 편집·검토 위치"],
  ["승인 main TIP", "SD Gundam GGeneration Advance (Korean).gba", "POC 승인 후 고정 출력명"],
  ["전체 레코드", `=COUNTA('TranslationMaster'!$A$7:$A$${6 + rows.length})`, "formula"],
  ["translated", `=COUNTIF('TranslationMaster'!$Q$7:$Q$${6 + rows.length},"translated")`, "formula"],
  ["pending", `=COUNTIF('TranslationMaster'!$Q$7:$Q$${6 + rows.length},"pending")`, "formula"],
  ["needs_review", `=COUNTIF('TranslationMaster'!$Q$7:$Q$${6 + rows.length},"needs_review")`, "formula"],
  ["preserve", `=COUNTIF('TranslationMaster'!$Q$7:$Q$${6 + rows.length},"preserve")`, "formula"],
  ["alias", `=COUNTIF('TranslationMaster'!$C$7:$C$${6 + rows.length},"alias")`, "formula"],
  ["owner entries", `=COUNTA('OwnerIndex'!$A$7:$A$${6 + owners.length})`, "formula"],
  ["excluded entries", `=COUNTA('Excluded'!$A$7:$A$${6 + exclusions.length})`, "formula"],
  ["scenario_main rows", `=COUNTIF('TranslationMaster'!$B$7:$B$${6 + rows.length},"scenario_main")`, "formula"],
  ["battle_event rows", `=COUNTIF('TranslationMaster'!$B$7:$B$${6 + rows.length},"battle_event_dialogue")`, "formula"],
  ["overlay batches", `=COUNTA('BatchLog'!$A$7:$A$${6 + overlayFiles.length})`, "formula"],
  ["ROM write in merge", merged.merge?.rom_write_performed ?? "", "반드시 false"],
];
const summaryValues = summaryRows.map(([label, value, note]) => [label, typeof value === "string" && value.startsWith("=") ? null : value, note]);
summarySheet.getRange(`A6:C${5 + summaryRows.length}`).values = summaryValues;
summaryRows.forEach(([, value], index) => {
  if (typeof value === "string" && value.startsWith("=")) {
    summarySheet.getRange(`B${6 + index}`).formulas = [[value]];
  }
});
dataStyle(summarySheet, `A6:C${5 + summaryRows.length}`);
summarySheet.mergeCells("A24:H24");
summarySheet.getRange("A24").values = [["운영 규칙: 새 merge는 중앙 JSON에 기록하고, XLSX는 이 builder로 같은 integrated/translation 위치에 재생성합니다. 날짜별 outputs/analysis 파일은 forensic/legacy 참고용이며 승인 main TIP을 대체하지 않습니다."]];
summarySheet.getRange("A24:H24").format = { fill: "#FFF2CC", font: { color: "#7F6000", size: 10 }, wrapText: true, verticalAlignment: "center" };
summarySheet.getRange("A24:H24").format.rowHeight = 32;
summarySheet.freezePanes.freezeRows(5);
applyWidths(summarySheet, { A: 28, B: 58, C: 66, D: 14, E: 14, F: 14, G: 14, H: 14 }, 24);

// Translation master
const lastColumn = columnLetter(columns.length);
title(translationSheet, `A1:${lastColumn}1`, "TranslationMaster · 전체 canonical/alias record");
translationSheet.mergeCells(`A2:${lastColumn}2`);
translationSheet.getRange("A2").values = [["배열·control signature·raw bytes는 JSON 문자열로 보존합니다. 번역 상태와 검토 상태를 필터링해 후속 작업을 이어갑니다."]];
translationSheet.mergeCells(`A3:${lastColumn}3`);
translationSheet.getRange("A3").values = [["translation_ko가 비어 있거나 pending인 행은 추정 번역으로 채우지 않고 source/provenance를 기준으로 검토합니다."]];
translationSheet.getRange(`A2:${lastColumn}3`).format = { fill: "#EAF1F8", font: { color: "#1F2937", size: 10 }, wrapText: true, verticalAlignment: "center" };
translationSheet.getRange(`A2:${lastColumn}3`).format.rowHeight = 24;
const translationHeaderRow = 6;
const translationStart = 7;
const translationEnd = translationStart + rows.length - 1;
translationSheet.getRange(`A${translationHeaderRow}:${lastColumn}${translationHeaderRow}`).values = [columns];
header(translationSheet, `A${translationHeaderRow}:${lastColumn}${translationHeaderRow}`);
translationSheet.getRange(`A${translationStart}:${lastColumn}${translationEnd}`).values = matrix(rows, columns);
dataStyle(translationSheet, `A${translationStart}:${lastColumn}${translationEnd}`);
translationSheet.freezePanes.freezeRows(translationHeaderRow);
translationSheet.freezePanes.freezeColumns(2);
applyWidths(translationSheet, {
  A: 24, B: 18, C: 14, D: 20, E: 22, F: 17, G: 17, H: 28, I: 30, J: 28,
  K: 25, L: 24, M: 22, N: 42, O: 34, P: 34, Q: 18, R: 24, S: 16, T: 20,
  U: 24, V: 14, W: 18, X: 16, Y: 18, Z: 25, AA: 56, AB: 48, AC: 68, AD: 28,
  AE: 28, AF: 56, AG: 56, AH: 72, AI: 72,
}, translationEnd);

// Owner index
const ownerColumns = ["owner_id", "owner_kind", "source_file_offset", "pointer_width", "target_record_ids", "target_container_ids", "relocation_schemas", "source_types", "families", "synthetic"];
title(ownerSheet, "A1:J1", "OwnerIndex · pointer / relocation provenance");
ownerSheet.mergeCells("A2:J2");
ownerSheet.getRange("A2").values = [["번역 record와 pointer owner를 분리해 보존합니다. 이 표는 대상 범위와 재계산 계약을 추적하는 감사용 인덱스입니다."]];
ownerSheet.getRange("A2:J2").format = { fill: "#EAF1F8", font: { color: "#1F2937", size: 10 }, wrapText: true };
ownerSheet.getRange("A2:J2").format.rowHeight = 24;
const ownerEnd = 6 + owners.length;
ownerSheet.getRange("A6:J6").values = [ownerColumns];
header(ownerSheet, "A6:J6");
ownerSheet.getRange(`A7:J${ownerEnd}`).values = matrix(owners, ownerColumns);
dataStyle(ownerSheet, `A7:J${ownerEnd}`);
ownerSheet.freezePanes.freezeRows(6);
ownerSheet.freezePanes.freezeColumns(2);
applyWidths(ownerSheet, { A: 24, B: 24, C: 20, D: 14, E: 54, F: 32, G: 32, H: 34, I: 38, J: 12 }, ownerEnd);

// Exclusions
const exclusionColumns = ["exclusion_id", "source_scope", "scope_status", "reason", "record_id", "alias_of", "target_file_offset", "target_address", "original_raw_sha256", "raw_hex", "source_text", "unresolved_slots", "region", "pointer_xref_count", "aligned_u32_xref_count", "pointer_source_count", "pointer_sources_digest"];
title(excludedSheet, "A1:Q1", "Excluded · unproven / review-only targets");
excludedSheet.mergeCells("A2:Q2");
excludedSheet.getRange("A2").values = [["owner-proven canonical record가 아닌 전역 후보·review-only 항목은 번역/ROM 적용에서 제외하되, 누락 방지를 위해 provenance를 보존합니다."]];
excludedSheet.getRange("A2:Q2").format = { fill: "#EAF1F8", font: { color: "#1F2937", size: 10 }, wrapText: true };
excludedSheet.getRange("A2:Q2").format.rowHeight = 28;
const exclusionEnd = 6 + exclusions.length;
excludedSheet.getRange("A6:Q6").values = [exclusionColumns];
header(excludedSheet, "A6:Q6");
excludedSheet.getRange(`A7:Q${exclusionEnd}`).values = matrix(exclusions, exclusionColumns);
dataStyle(excludedSheet, `A7:Q${exclusionEnd}`);
excludedSheet.freezePanes.freezeRows(6);
excludedSheet.freezePanes.freezeColumns(2);
applyWidths(excludedSheet, { A: 24, B: 22, C: 22, D: 54, E: 24, F: 20, G: 18, H: 18, I: 68, J: 42, K: 48, L: 28, M: 24, N: 16, O: 20, P: 20, Q: 68 }, exclusionEnd);

// Control spec
const controlColumns = ["record_id", "target_file_offset", "source_text", "translation_ko", "translation_status", "storage_contract", "control_signature", "translation_segments"];
title(controlSheet, "A1:H1", "ControlSpec · scenario control stream");
controlSheet.mergeCells("A2:H2");
controlSheet.getRange("A2").values = [["scenario_main의 제어 framing과 번역 세그먼트를 한눈에 확인하는 보조 시트입니다. 0x03/0x04/0x05/0x06 argument는 원문 계약으로 보존합니다."]];
controlSheet.getRange("A2:H2").format = { fill: "#EAF1F8", font: { color: "#1F2937", size: 10 }, wrapText: true };
controlSheet.getRange("A2:H2").format.rowHeight = 28;
const controlEnd = 6 + scenarioRows.length;
controlSheet.getRange("A6:H6").values = [controlColumns];
header(controlSheet, "A6:H6");
controlSheet.getRange(`A7:H${controlEnd}`).values = matrix(scenarioRows, controlColumns);
dataStyle(controlSheet, `A7:H${controlEnd}`);
controlSheet.freezePanes.freezeRows(6);
applyWidths(controlSheet, { A: 26, B: 18, C: 58, D: 42, E: 18, F: 28, G: 72, H: 72 }, controlEnd);

// Batch log
const batchColumns = ["batch_id", "file", "file_sha256", "record_count", "mode", "source_rom_sha256", "manifest_identity_sha256", "accepted_record_count"];
title(batchSheet, "A1:H1", "BatchLog · translation overlay provenance");
batchSheet.mergeCells("A2:H2");
batchSheet.getRange("A2").values = [["병합에 참여한 overlay batch만 기록합니다. 번역 JSON의 identity와 함께 배치 provenance를 추적합니다."]];
batchSheet.getRange("A2:H2").format = { fill: "#EAF1F8", font: { color: "#1F2937", size: 10 }, wrapText: true };
batchSheet.getRange("A2:H2").format.rowHeight = 24;
const batchEnd = 6 + overlayFiles.length;
batchSheet.getRange("A6:H6").values = [batchColumns];
header(batchSheet, "A6:H6");
const batchRows = overlayFiles.map((item) => [
  item.batch_id ?? "", item.file ?? "", item.file_sha256 ?? "", item.record_count ?? 0,
  merged.merge?.mode ?? "", merged.merge?.source_rom_sha256 ?? "", merged.merge?.source_manifest_identity_sha256 ?? "",
  merged.merge?.accepted_record_count ?? 0,
]);
batchSheet.getRange(`A7:H${batchEnd}`).values = batchRows;
dataStyle(batchSheet, `A7:H${batchEnd}`);
batchSheet.freezePanes.freezeRows(6);
applyWidths(batchSheet, { A: 34, B: 48, C: 68, D: 16, E: 14, F: 68, G: 68, H: 22 }, batchEnd);

await fs.mkdir(path.dirname(outputPath), { recursive: true });
await fs.mkdir(previewDir, { recursive: true });

const summaryInspect = await wb.inspect({ kind: "table", range: "Summary!A1:C23", include: "values,formulas", tableMaxRows: 23, tableMaxCols: 3, tableMaxCellChars: 140 });
console.log(summaryInspect.ndjson);

const previewSpecs = [
  ["Summary", "A1:H24", "summary_preview.png"],
  ["TranslationMaster", `A1:${lastColumn}12`, "translationmaster_preview.png"],
  ["OwnerIndex", "A1:J12", "ownerindex_preview.png"],
  ["Excluded", "A1:Q12", "excluded_preview.png"],
  ["ControlSpec", "A1:H12", "controlspec_preview.png"],
  ["BatchLog", "A1:H20", "batchlog_preview.png"],
];
for (const [sheetName, range, fileName] of previewSpecs) {
  const preview = await wb.render({ sheetName, range, scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, fileName), new Uint8Array(await preview.arrayBuffer()));
}

const xlsx = await SpreadsheetFile.exportXlsx(wb);
await xlsx.save(outputPath);
console.log(JSON.stringify({
  outputPath,
  previewDir,
  records: rows.length,
  owners: owners.length,
  exclusions: exclusions.length,
  scenarioRows: scenarioRows.length,
  overlayBatches: overlayFiles.length,
}, null, 2));
