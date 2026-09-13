import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const sourcePath = process.argv[2] ?? "analysis/scenario_event_translation_source_20260827.json";
const existingPath = process.argv[3] ?? "analysis/stage2_translation_sheet_rows_20260827.json";
const alignmentPath = process.argv[4] ?? "analysis/scenario_event_12x12_alignment_20260827.json";
const outputDir = process.argv[5] ?? "outputs/20260827_scenario_event_translation";
const outputPath = `${outputDir}/ggen_advance_scenario_event_translation_20260827.xlsx`;

const sourceReport = JSON.parse(await fs.readFile(sourcePath, "utf8"));
const existingPayload = JSON.parse(await fs.readFile(existingPath, "utf8"));
const alignment = JSON.parse(await fs.readFile(alignmentPath, "utf8"));
const existingRows = existingPayload.records ?? existingPayload;
const mainRecords = [...(sourceReport.main.records ?? [])].sort((a, b) =>
  parseHex(a.target_file_offset) - parseHex(b.target_file_offset),
);
const dynamicRecords = [...(sourceReport.dynamic.records ?? [])].sort((a, b) =>
  parseHex(a.target_file_offset) - parseHex(b.target_file_offset),
);
const weaponRows = existingRows
  .filter((row) => row.semantic_category === "weapon_name")
  .sort((a, b) => parseHex(a.target_file_offset) - parseHex(b.target_file_offset));
const fullyAligned = new Set((alignment.fully_aligned_indices ?? []).map(Number));

function parseHex(value) {
  if (typeof value === "number") return value;
  return Number.parseInt(String(value ?? "0").replace(/^0x/i, ""), 16);
}

function ownerText(fields, family) {
  return (fields ?? [])
    .map((owner) => {
      if (family === "main_scenario_event") {
        return `r${String(owner.row).padStart(3, "0")}/s${String(owner.slot).padStart(2, "0")}@${owner.pointer_file_offset}`;
      }
      return `c${String(owner.context_index).padStart(3, "0")}/col${String(owner.column)}@${owner.pointer_file_offset}`;
    })
    .join("; ");
}

function slotsText(record) {
  if (record.segments) {
    return record.segments
      .map((segment, index) => `seg${index + 1}:${(segment.slots ?? []).join(",")}`)
      .join(" | ");
  }
  return (record.slots ?? []).join(",");
}

function controlText(record) {
  return (record.controls ?? [])
    .map((control) => control.argument === undefined ? control.code : `${control.code}(${control.argument})`)
    .join(" → ");
}

// These are intentionally exact-line overrides.  They cover short, visually
// verified barks/names without pretending that an unresolved or grammatically
// suspicious main-bank sentence has been reconstructed.
const exactLineTranslations = new Map([
  ["アンディー……！", "앤디……!"],
  ["アンディー……", "앤디……"],
  ["……アンディ！", "……앤디!"],
  ["アナタ……", "당신……"],
  ["イキマス……！", "가겠습니다……!"],
  ["ウカツナヤツメ……", "어리석은 녀석……"],
  ["ウゴキガミエル……", "움직임이 보여……"],
  ["オトサレルワケニハイカナイ…", "격추당할 수는 없어…"],
  ["…………ソコォ！", "……거기다!"],
  ["ガロード……", "가로드……"],
  ["ガロード……！", "가로드……!"],
  ["クククク……", "크크크크……"],
  ["クッ！", "큭!"],
  ["クッ……！？", "큭……!?"],
  ["コイツ！", "이 녀석!"],
  ["コイツ！！", "이 녀석!!"],
  ["コイツ……", "이 녀석……"],
  ["コザカシイトオモウ……", "잔꾀를 부리는군……"],
  ["ジーク・ジオン！！", "지크 지온!!"],
  ["ジーク…ジオン……", "지크… 지온……"],
  ["ゼロ……", "제로……"],
  ["ターゲットカクニン……", "표적 확인……"],
  ["ダメ……！", "안 돼……!"],
  ["チィィ……ッ！", "쳇……!"],
  ["チィィッ！", "쳇!"],
  ["チクショウ……！", "젠장……!"],
  ["チクショウッ！", "젠장!"],
  ["チッ、チクショウ……", "쳇, 젠장……"],
  ["ドモン……！！", "도몬……!!"],
  ["ニンムシッパイ……", "임무 실패……"],
  ["ハイジョスル！", "제거한다!"],
  ["ブッタネ……？", "때렸지……?"],
  ["フン……！", "흥……!"],
  ["マ、マルガリータ……", "마, 마르가리타……"],
  ["ミエル……", "보여……"],
  ["ムッ……！", "흠……!"],
  ["ユ…！", "유…!"],
  ["ユウ……！！", "유우……!!"],
  ["ララァ……", "라라아……"],
  ["クッ……！", "큭……!"],
  ["クッ……", "큭……"],
  ["チッ……！", "쳇……!"],
  ["チッ……", "쳇……"],
  ["チィィッ！", "쳇……!"],
  ["チ、チクショウ……！", "치, 젠장……!"],
  ["クソッ！", "젠장!"],
  ["バカ！", "바보!"],
  ["オマエ", "너"],
  ["アンディー", "앤디"],
  ["アプサラス", "앱사라스"],
  ["ジャブロー", "자브로"],
  ["サハリン", "사할린"],
  ["キラ", "키라"],
  ["メチャクチャ", "엉망진창"],
  ["パワーダウン", "출력 저하"],
  ["ダメージセリフ", "피격 대사"],
  ["セリフ", "대사"],
  ["アークエンジェル", "아크엔젤"],
  ["グワジン", "구와진"],
  ["マッシュ", "맛슈"],
  ["プレッシャー", "프레셔"],
  ["ナンセンス", "난센스"],
  ["コイツ", "이 녀석"],
  ["ドジ", "얼간이"],
  ["ヤツ", "녀석"],
  ["戦", "전투"],
  ["機", "기체"],
  ["砲", "포"],
  ["粒", "입자"],
  ["改", "개량"],
  ["型", "형"],
  ["子", "자"],
]);

function punctuationOnly(line) {
  return line.length > 0 && /^[…！？ーッ。、・「」\s]+$/u.test(line);
}

function translateExactLines(text) {
  if (!text) {
    return {
      translation: "",
      status: "preserve",
      confidence: "high",
      note: "빈 표시 stream 또는 terminator-only record",
    };
  }
  const lines = text.split("\\n");
  const output = [];
  let translatedLineCount = 0;
  for (const line of lines) {
    if (line === "") {
      output.push("");
      continue;
    }
    const exact = exactLineTranslations.get(line);
    if (exact !== undefined) {
      output.push(exact);
      translatedLineCount += 1;
      continue;
    }
    if (punctuationOnly(line)) {
      output.push(line);
      continue;
    }
    return {
      translation: "",
      status: "needs_review",
      confidence: "pending",
      note: "12×12 seed 기준으로 glyph는 이어지지만, 문장 전체의 원문/문맥을 안전하게 확정하지 못해 의역 보류",
    };
  }
  if (translatedLineCount > 0) {
    return {
      translation: output.join("\\n"),
      status: "translated",
      confidence: "medium",
      note: "짧은 검증 대사/고유명사에 자연스러운 한국어 의역 적용; \\n 표식과 record 순서는 보존",
    };
  }
  return {
    translation: output.join("\\n"),
    status: "translated_same",
    confidence: "high",
    note: "말줄임표·감탄부호 등 비언어 표시만 포함되어 원문 표시를 보존",
  };
}

function mainTranslation(record) {
  const unresolved = record.unresolved_slots ?? [];
  if (unresolved.length > 0) {
    return {
      translation: "",
      status: "needs_charmap_resolution",
      confidence: "pending",
      note: "미확정 12×12 glyph를 <slot> 표식으로 보존; 일본어를 추측해 번역하지 않음",
    };
  }
  return translateExactLines(String(record.source_text_seed ?? ""));
}

function decodeStatus(record) {
  return (record.unresolved_slots ?? []).length > 0 ? "partial" : "complete_by_12x12_seed";
}

const sourceTextSet = new Set(
  existingRows
    .map((row) => row.source_text ?? row.decoded_text_seed ?? "")
    .filter(Boolean),
);
const mainExactSourceOverlap = mainRecords.filter((record) =>
  sourceTextSet.has(record.source_text_seed ?? ""),
).length;

const translationColumns = [
  "record_id",
  "family",
  "context_group",
  "logical_row_or_context",
  "slot_or_column",
  "target_file_offset",
  "pointer_value",
  "pointer_owner_count",
  "pointer_owner_fields",
  "source_text",
  "translation_ko",
  "translation_status",
  "translation_confidence",
  "source_decode_status",
  "source_unresolved_slots",
  "source_slots",
  "control_frame",
  "line_break_count",
  "dynamic_control_count",
  "final_control",
  "original_byte_length",
  "translated_byte_length",
  "byte_delta",
  "pointer_recalc_required",
  "raw_hex",
  "translated_raw_hex",
  "previous_record_id",
  "next_record_id",
  "translator_notes",
];

const mainRows = mainRecords.map((record, index) => {
  const result = mainTranslation(record);
  const unresolved = (record.unresolved_slots ?? []).join(", ");
  const family = "main_scenario_event";
  const previous = index > 0 ? mainRecords[index - 1].record_id : "";
  const next = index + 1 < mainRecords.length ? mainRecords[index + 1].record_id : "";
  let note = result.note;
  if (record.dynamic_control_count > 0) {
    note += "; ⟦DYNAMIC⟧ 자리표시는 dynamic fragment pool과 연결되며, 해당 pool은 기존 weapon_name과 내용 중복으로 제외됨";
  }
  if (record.line_break_count > 0) {
    note += `; 표시 줄바꿈 ${record.line_break_count}회와 전후 record 순서를 보존`;
  }
  return {
    record_id: record.record_id,
    family,
    context_group: `scenario_row_${String(record.first_directory_row).padStart(3, "0")}`,
    logical_row_or_context: record.first_directory_row,
    slot_or_column: record.first_directory_slot,
    target_file_offset: record.target_file_offset,
    pointer_value: record.pointer_value,
    pointer_owner_count: record.pointer_owner_count,
    pointer_owner_fields: ownerText(record.owner_fields, family),
    source_text: record.source_text_seed ?? "",
    translation_ko: result.translation,
    translation_status: result.status,
    translation_confidence: result.confidence,
    source_decode_status: decodeStatus(record),
    source_unresolved_slots: unresolved,
    source_slots: slotsText(record),
    control_frame: controlText(record),
    line_break_count: record.line_break_count,
    dynamic_control_count: record.dynamic_control_count,
    final_control: record.final_control,
    original_byte_length: record.byte_length,
    translated_byte_length: "",
    byte_delta: "",
    pointer_recalc_required: result.status === "translated" ? "pending_encoding" : "no",
    raw_hex: record.raw_hex,
    translated_raw_hex: "",
    previous_record_id: previous,
    next_record_id: next,
    translator_notes: note,
  };
});

const excludedColumns = [
  "record_id",
  "family",
  "context_group",
  "target_file_offset",
  "source_text",
  "source_unresolved_slots",
  "alignment_expected_source",
  "alignment_status",
  "existing_record_id",
  "existing_target_file_offset",
  "existing_source_text",
  "existing_translation_ko",
  "pointer_owner_count",
  "pointer_owner_fields",
  "raw_hex",
  "exclusion_reason",
];

const excludedRows = dynamicRecords.map((record, index) => {
  const existing = weaponRows[index] ?? {};
  const sample = (alignment.samples ?? []).find((item) => Number(item.index) === index) ?? {};
  return {
    record_id: record.record_id,
    family: "dynamic_fragment_pool",
    context_group: `dynamic_context_${String(index).padStart(3, "0")}`,
    target_file_offset: record.target_file_offset,
    source_text: record.source_text_seed ?? "",
    source_unresolved_slots: (record.unresolved_slots ?? []).join(", "),
    alignment_expected_source: sample.expected ?? "",
    alignment_status: fullyAligned.has(index) ? "fully_aligned" : "skipped_or_unresolved",
    existing_record_id: existing.record_id ?? "",
    existing_target_file_offset: existing.target_file_offset ?? "",
    existing_source_text: existing.source_text ?? existing.decoded_text_seed ?? "",
    existing_translation_ko: existing.translation_ko ?? "",
    pointer_owner_count: record.pointer_owner_count,
    pointer_owner_fields: ownerText(record.owner_fields, "dynamic_fragment_pool"),
    raw_hex: record.raw_hex,
    exclusion_reason: "content_duplicate_of_existing_4,069_weapon_name",
  };
});

const ownerColumns = [
  "owner_id",
  "scope_status",
  "family",
  "record_id",
  "context_group",
  "logical_row_or_context",
  "slot_or_column",
  "pointer_file_offset",
  "target_file_offset",
  "pointer_value",
  "owner_note",
];

const ownerRows = [];
let ownerNumber = 1;
for (const record of mainRecords) {
  for (const owner of record.owner_fields ?? []) {
    ownerRows.push({
      owner_id: `OWNER-${String(ownerNumber++).padStart(4, "0")}`,
      scope_status: "included",
      family: "main_scenario_event",
      record_id: record.record_id,
      context_group: `scenario_row_${String(record.first_directory_row).padStart(3, "0")}`,
      logical_row_or_context: owner.row,
      slot_or_column: owner.slot,
      pointer_file_offset: owner.pointer_file_offset,
      target_file_offset: record.target_file_offset,
      pointer_value: record.pointer_value,
      owner_note: "main directory u32 pointer owner",
    });
  }
}
for (const [index, record] of dynamicRecords.entries()) {
  for (const owner of record.owner_fields ?? []) {
    ownerRows.push({
      owner_id: `OWNER-${String(ownerNumber++).padStart(4, "0")}`,
      scope_status: "excluded_duplicate",
      family: "dynamic_fragment_pool",
      record_id: record.record_id,
      context_group: `dynamic_context_${String(index).padStart(3, "0")}`,
      logical_row_or_context: owner.context_index,
      slot_or_column: owner.column,
      pointer_file_offset: owner.pointer_file_offset,
      target_file_offset: record.target_file_offset,
      pointer_value: record.pointer_value,
      owner_note: "dynamic pointer matrix u32 owner; content is duplicated by existing weapon_name",
    });
  }
}

const controlCounts = new Map();
for (const record of mainRecords) {
  for (const control of record.controls ?? []) {
    controlCounts.set(control.code, (controlCounts.get(control.code) ?? 0) + 1);
  }
}
const controlRows = [
  {
    code: "0x01",
    framing: "terminal A",
    argument_bytes: 0,
    translation_action: "보존",
    observed_count: controlCounts.get("0x01") ?? 0,
    notes: "main record 표시 stream의 종료 제어. 번역 대상 텍스트와 분리해서 유지",
  },
  {
    code: "0x02",
    framing: "terminal B",
    argument_bytes: 0,
    translation_action: "보존",
    observed_count: controlCounts.get("0x02") ?? 0,
    notes: "main record의 두 번째 종료 변형. 정확한 분기 의미는 runtime 관측 전까지 보류",
  },
  {
    code: "0x03",
    framing: "line break / next segment",
    argument_bytes: 0,
    translation_action: "줄바꿈 보존",
    observed_count: controlCounts.get("0x03") ?? 0,
    notes: "TranslationMaster의 source_text에서 \\n 표식으로 표시",
  },
  {
    code: "0x04",
    framing: "dynamic fragment insertion",
    argument_bytes: 0,
    translation_action: "⟦DYNAMIC⟧ 보존",
    observed_count: controlCounts.get("0x04") ?? 0,
    notes: "삽입 fragment는 dynamic pool에서 resolve되며, 이번 scope에서는 기존 weapon_name 중복으로 제외",
  },
  {
    code: "0x05",
    framing: "display/object argument",
    argument_bytes: 1,
    translation_action: "argument 보존",
    observed_count: controlCounts.get("0x05") ?? 0,
    notes: "정적 parser가 뒤따르는 1-byte argument를 확인. 숫자 자체는 번역하지 않음",
  },
  {
    code: "0x06",
    framing: "display/object argument",
    argument_bytes: 1,
    translation_action: "argument 보존",
    observed_count: controlCounts.get("0x06") ?? 0,
    notes: "정적 parser가 뒤따르는 1-byte argument를 확인. 정확한 runtime 의미는 추가 추적 대상",
  },
].map((row) => [row.code, row.framing, row.argument_bytes, row.translation_action, row.observed_count, row.notes]);

function asMatrix(rows, columns) {
  return rows.map((row) => columns.map((column) => row[column] ?? ""));
}

function setTitle(sheet, range, textValue) {
  sheet.mergeCells(range);
  const firstCell = range.split(":")[0];
  sheet.getRange(firstCell).values = [[textValue]];
  sheet.getRange(range).format = {
    fill: "#17365D",
    font: { bold: true, color: "#FFFFFF", size: 14 },
    horizontalAlignment: "left",
    verticalAlignment: "center",
  };
  sheet.getRange(range).format.rowHeight = 28;
}

function styleHeader(sheet, range) {
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

function styleData(sheet, range) {
  sheet.getRange(range).format = {
    font: { color: "#1F2937", size: 9 },
    verticalAlignment: "top",
    wrapText: true,
    borders: {
      insideHorizontal: { style: "hair", color: "#D9E2F3" },
      bottom: { style: "hair", color: "#D9E2F3" },
    },
  };
}

function columnLetter(number) {
  let n = number;
  let result = "";
  while (n > 0) {
    const remainder = (n - 1) % 26;
    result = String.fromCharCode(65 + remainder) + result;
    n = Math.floor((n - 1) / 26);
  }
  return result;
}

const wb = Workbook.create();
const summarySheet = wb.worksheets.add("Summary");
const translationSheet = wb.worksheets.add("TranslationMaster");
const ownerSheet = wb.worksheets.add("OwnerIndex");
const excludedSheet = wb.worksheets.add("ExcludedOverlap");
const controlSheet = wb.worksheets.add("ControlSpec");
for (const sheet of [summarySheet, translationSheet, ownerSheet, excludedSheet, controlSheet]) {
  sheet.showGridLines = false;
}

// Summary sheet
setTitle(summarySheet, "A1:H1", "G Generation Advance · 시나리오/이벤트 신규 번역 통합시트");
summarySheet.mergeCells("A2:H2");
summarySheet.getRange("A2").values = [[
  "기존 4,069건 및 table_1C92E8과 내용/소유자 범위를 겹치지 않게 분리한 main scenario/event bank 번역 작업표",
]];
summarySheet.mergeCells("A3:H3");
summarySheet.getRange("A3").values = [[
  "동적 fragment 165개는 기존 weapon_name과 내용상 일대일 대응하여 번역 대상에서 제외하고 ExcludedOverlap에 대응만 기록했습니다.",
]];
summarySheet.getRange("A2:H3").format = {
  fill: "#EAF1F8",
  font: { color: "#1F2937", size: 10 },
  wrapText: true,
  verticalAlignment: "center",
};
summarySheet.getRange("A2:H3").format.rowHeight = 24;
summarySheet.getRange("A5:C5").values = [["항목", "값", "근거 / 사용 방법"]];
styleHeader(summarySheet, "A5:C5");
const summaryRows = [
  ["원본 ROM", sourceReport.source.path, "read-only 분석 원본"],
  ["원본 SHA-256", sourceReport.source.sha256, "원본 identity gate"],
  ["font / dictionary mode", `${sourceReport.charmap.font_mode} · ${sourceReport.charmap.dictionary_file_range}`, "시나리오 wrapper가 12×12 mode 선택"],
  ["검증된 12×12 slot", sourceReport.charmap.verified_slot_count, "미확정 slot은 source_text에 <slot> 표식 유지"],
  ["main unique records", mainRecords.length, "TranslationMaster에 포함"],
  ["TranslationMaster rows", `=COUNTA('TranslationMaster'!$A$7:$A$${6 + mainRows.length})`, "formula: 번역 대상 row 수"],
  ["natural translated rows", `=COUNTIF('TranslationMaster'!$L$7:$L$${6 + mainRows.length},"translated")`, "formula: 짧은 검증 대사/고유명사 의역"],
  ["preserve / translated_same", `=COUNTIF('TranslationMaster'!$L$7:$L$${6 + mainRows.length},"preserve")+COUNTIF('TranslationMaster'!$L$7:$L$${6 + mainRows.length},"translated_same")`, "formula: 비언어 표시/빈 stream"],
  ["needs_review rows", `=COUNTIF('TranslationMaster'!$L$7:$L$${6 + mainRows.length},"needs_review")`, "formula: seed는 이어지지만 문장/문맥 확정 보류"],
  ["needs_charmap_resolution rows", `=COUNTIF('TranslationMaster'!$L$7:$L$${6 + mainRows.length},"needs_charmap_resolution")`, "formula: 미확정 12×12 glyph 포함"],
  ["dynamic rows excluded", `=COUNTA('ExcludedOverlap'!$A$7:$A$${6 + excludedRows.length})`, "formula: 기존 4,069 weapon_name과 내용 중복"],
  ["pointer owners indexed", `=COUNTA('OwnerIndex'!$A$7:$A$${6 + ownerRows.length})`, "formula: main + excluded dynamic owner fields"],
  ["main pointer fields", sourceReport.main.summary.pointer_fields, "main directory u32 owner 수"],
  ["dynamic pointer fields", sourceReport.dynamic.summary.pointer_fields, "651×6 matrix의 populated owner 수"],
  ["target overlap: existing master", sourceReport.exclusion_check.existing_master_overlap, "file target range 교집합"],
  ["target overlap: table_1C92E8", sourceReport.exclusion_check.table_1C92E8_overlap, "file target range 교집합"],
  ["exact main source overlap: existing master", mainExactSourceOverlap, "decoded seed 전체 문자열 strict 비교"],
  ["dynamic content overlap", dynamicRecords.length, "weapon_name 165건과 sorted target 일대일 대응"],
  ["ROM patch bytes", "not emitted", "번역 텍스트/구조 통합시트이며 Korean encoding·relocation은 후속 단계"],
];
summarySheet.getRange(`A6:C${5 + summaryRows.length}`).values = summaryRows;
for (let index = 0; index < summaryRows.length; index += 1) {
  const value = summaryRows[index][1];
  if (typeof value === "string" && value.startsWith("=")) {
    summarySheet.getRange(`B${6 + index}`).formulas = [[value]];
  }
}
styleData(summarySheet, `A6:C${5 + summaryRows.length}`);
summarySheet.mergeCells("A28:H28");
summarySheet.getRange("A28").values = [[
  "번역 원칙: 직역을 피하고, 같은 record 안의 줄바꿈·제어 framing·전후 owner 순서를 보존합니다. 다만 현재 12×12 seed에서 확정되지 않은 glyph 또는 문장 전체가 비문으로 보이는 경우에는 의미를 추측하지 않고 검토 상태로 남겼습니다.",
]];
summarySheet.mergeCells("A29:H29");
summarySheet.getRange("A29").values = [[
  "Pointer/Control 구조: main directory는 row/slot owner를 OwnerIndex에 풀어 쓰고, 0x03 줄바꿈·0x04 dynamic insertion·0x05/0x06 1-byte argument는 번역문과 분리해 유지합니다.",
]];
summarySheet.mergeCells("A30:H30");
summarySheet.getRange("A30").values = [[
  "다음 작업: needs_charmap_resolution → glyph 검증, needs_review → 전후 scenario row 문맥 검토, translated → Korean encoder와 byte relocation 검증 순서입니다.",
]];
summarySheet.getRange("A28:H30").format = {
  fill: "#FFF2CC",
  font: { color: "#7F6000", size: 10 },
  wrapText: true,
  verticalAlignment: "center",
};
summarySheet.getRange("A28:H30").format.rowHeight = 32;
summarySheet.tables.add(`A5:C${5 + summaryRows.length}`, true, "ScenarioSummaryTable").style = "TableStyleMedium2";
summarySheet.freezePanes.freezeRows(5);
summarySheet.getRange("A1:A30").format.columnWidth = 36;
summarySheet.getRange("B1:B30").format.columnWidth = 34;
summarySheet.getRange("C1:C30").format.columnWidth = 78;
summarySheet.getRange("D1:H30").format.columnWidth = 14;

// Translation master: only the main bank, with context and owner adjacency.
setTitle(translationSheet, "A1:AC1", "TranslationMaster · 신규 main scenario/event bank");
translationSheet.mergeCells("A2:AC2");
translationSheet.getRange("A2").values = [[
  `원본 SHA-256 ${sourceReport.source.sha256} · mode ${sourceReport.charmap.font_mode} · main unique ${mainRows.length} · dynamic duplicate excluded ${excludedRows.length}`,
]];
translationSheet.mergeCells("A3:AC3");
translationSheet.getRange("A3").values = [[
  "source_text는 원본 control stream을 해석한 seed이며, 이전/다음 record와 scenario_row 그룹을 함께 사용해 문맥 단위로 검토합니다.",
]];
translationSheet.mergeCells("A4:AC4");
translationSheet.getRange("A4").values = [[
  "translation_ko는 검증된 짧은 대사/고유명사만 자연스럽게 의역해 채웠습니다. translated 행도 translated_raw_hex를 생성하지 않았으므로 pointer_recalc_required는 pending_encoding입니다.",
]];
translationSheet.getRange("A2:AC4").format = {
  fill: "#EAF1F8",
  font: { color: "#1F2937", size: 10 },
  wrapText: true,
  verticalAlignment: "center",
};
translationSheet.getRange("A2:AC4").format.rowHeight = 22;
const translationHeaderRow = 6;
const translationDataStart = 7;
const translationDataEnd = translationDataStart + mainRows.length - 1;
translationSheet.getRange(`A${translationHeaderRow}:AC${translationHeaderRow}`).values = [translationColumns];
styleHeader(translationSheet, `A${translationHeaderRow}:AC${translationHeaderRow}`);
translationSheet.getRange(`A${translationDataStart}:AC${translationDataEnd}`).values = asMatrix(mainRows, translationColumns);
styleData(translationSheet, `A${translationDataStart}:AC${translationDataEnd}`);
translationSheet.getRange(`D${translationDataStart}:E${translationDataEnd}`).format.numberFormat = "0";
translationSheet.getRange(`H${translationDataStart}:H${translationDataEnd}`).format.numberFormat = "0";
translationSheet.getRange(`R${translationDataStart}:S${translationDataEnd}`).format.numberFormat = "0";
translationSheet.getRange(`U${translationDataStart}:W${translationDataEnd}`).format.numberFormat = "0";
translationSheet.getRange(`F${translationDataStart}:G${translationDataEnd}`).format.numberFormat = "@";
translationSheet.getRange(`Y${translationDataStart}:Z${translationDataEnd}`).format.numberFormat = "@";
translationSheet.getRange(`L${translationDataStart}:M${translationDataEnd}`).format.horizontalAlignment = "center";
translationSheet.getRange(`X${translationDataStart}:X${translationDataEnd}`).format.horizontalAlignment = "center";
translationSheet.tables.add(`A${translationHeaderRow}:AC${translationDataEnd}`, true, "ScenarioTranslationMasterTable").style = "TableStyleMedium2";
translationSheet.freezePanes.freezeRows(translationHeaderRow);
translationSheet.freezePanes.freezeColumns(2);
const translationWidths = {
  A: 23, B: 22, C: 18, D: 12, E: 12, F: 16, G: 16, H: 12, I: 46,
  J: 34, K: 34, L: 23, M: 16, N: 22, O: 26, P: 58, Q: 30, R: 12,
  S: 14, T: 12, U: 14, V: 16, W: 12, X: 20, Y: 52, Z: 52, AA: 23,
  AB: 23, AC: 72,
};
for (const [column, width] of Object.entries(translationWidths)) {
  translationSheet.getRange(`${column}1:${column}${translationDataEnd}`).format.columnWidth = width;
}
translationSheet.getRange(`L${translationDataStart}:L${translationDataEnd}`).conditionalFormats.add("containsText", {
  text: "translated",
  format: { fill: "#E2F0D9", font: { color: "#215E21" } },
});
translationSheet.getRange(`L${translationDataStart}:L${translationDataEnd}`).conditionalFormats.add("containsText", {
  text: "preserve",
  format: { fill: "#E7E6E6", font: { color: "#595959" } },
});
translationSheet.getRange(`L${translationDataStart}:L${translationDataEnd}`).conditionalFormats.add("containsText", {
  text: "needs_",
  format: { fill: "#FFF2CC", font: { color: "#7F6000" } },
});
translationSheet.getRange(`X${translationDataStart}:X${translationDataEnd}`).conditionalFormats.add("containsText", {
  text: "pending",
  format: { fill: "#FCE4D6", font: { bold: true, color: "#9C0006" } },
});
translationSheet.getRange(`L${translationDataStart}:L${translationDataEnd}`).dataValidation = {
  rule: { type: "list", values: ["translated", "translated_same", "needs_review", "needs_charmap_resolution", "preserve"] },
};

// Pointer ownership index includes both included main owners and excluded dynamic owners.
setTitle(ownerSheet, "A1:K1", "OwnerIndex · scenario/event pointer provenance");
ownerSheet.mergeCells("A2:K2");
ownerSheet.getRange("A2").values = [[
  "scope_status=included는 TranslationMaster 대상, excluded_duplicate는 기존 4,069 weapon_name과 내용 중복되어 번역에서 제외한 dynamic owner입니다.",
]];
ownerSheet.getRange("A2:K2").format = { fill: "#EAF1F8", font: { color: "#1F2937", size: 10 }, wrapText: true };
ownerSheet.getRange("A2:K2").format.rowHeight = 24;
const ownerHeaderRow = 6;
const ownerDataStart = 7;
const ownerDataEnd = ownerDataStart + ownerRows.length - 1;
ownerSheet.getRange(`A${ownerHeaderRow}:K${ownerHeaderRow}`).values = [ownerColumns];
styleHeader(ownerSheet, `A${ownerHeaderRow}:K${ownerHeaderRow}`);
ownerSheet.getRange(`A${ownerDataStart}:K${ownerDataEnd}`).values = asMatrix(ownerRows, ownerColumns);
styleData(ownerSheet, `A${ownerDataStart}:K${ownerDataEnd}`);
ownerSheet.getRange(`H${ownerDataStart}:J${ownerDataEnd}`).format.numberFormat = "@";
ownerSheet.tables.add(`A${ownerHeaderRow}:K${ownerDataEnd}`, true, "ScenarioOwnerIndexTable").style = "TableStyleMedium2";
ownerSheet.freezePanes.freezeRows(ownerHeaderRow);
ownerSheet.freezePanes.freezeColumns(2);
for (const [column, width] of Object.entries({ A: 16, B: 20, C: 24, D: 23, E: 20, F: 18, G: 14, H: 20, I: 18, J: 18, K: 56 })) {
  ownerSheet.getRange(`${column}1:${column}${ownerDataEnd}`).format.columnWidth = width;
}
ownerSheet.getRange(`B${ownerDataStart}:B${ownerDataEnd}`).conditionalFormats.add("containsText", {
  text: "excluded",
  format: { fill: "#FFF2CC", font: { color: "#7F6000" } },
});

// Excluded dynamic content is kept as an audit sheet, not as duplicate translation rows.
setTitle(excludedSheet, "A1:P1", "ExcludedOverlap · dynamic fragment ↔ existing 4,069 weapon_name");
excludedSheet.mergeCells("A2:P2");
excludedSheet.getRange("A2").values = [[
  "165 dynamic stream은 scenario main record의 0x04 insertion owner이지만, sorted target 기준 기존 weapon_name 165건과 내용상 대응합니다. 이 sheet는 재번역을 막기 위한 provenance입니다.",
]];
excludedSheet.getRange("A2:P2").format = { fill: "#EAF1F8", font: { color: "#1F2937", size: 10 }, wrapText: true };
excludedSheet.getRange("A2:P2").format.rowHeight = 28;
const excludedHeaderRow = 6;
const excludedDataStart = 7;
const excludedDataEnd = excludedDataStart + excludedRows.length - 1;
excludedSheet.getRange(`A${excludedHeaderRow}:P${excludedHeaderRow}`).values = [excludedColumns];
styleHeader(excludedSheet, `A${excludedHeaderRow}:P${excludedHeaderRow}`);
excludedSheet.getRange(`A${excludedDataStart}:P${excludedDataEnd}`).values = asMatrix(excludedRows, excludedColumns);
styleData(excludedSheet, `A${excludedDataStart}:P${excludedDataEnd}`);
excludedSheet.getRange(`D${excludedDataStart}:D${excludedDataEnd}`).format.numberFormat = "@";
excludedSheet.getRange(`I${excludedDataStart}:J${excludedDataEnd}`).format.numberFormat = "@";
excludedSheet.getRange(`O${excludedDataStart}:O${excludedDataEnd}`).format.numberFormat = "@";
excludedSheet.tables.add(`A${excludedHeaderRow}:P${excludedDataEnd}`, true, "ScenarioExcludedOverlapTable").style = "TableStyleMedium2";
excludedSheet.freezePanes.freezeRows(excludedHeaderRow);
excludedSheet.freezePanes.freezeColumns(2);
for (const [column, width] of Object.entries({ A: 23, B: 24, C: 20, D: 18, E: 34, F: 24, G: 34, H: 22, I: 23, J: 18, K: 34, L: 34, M: 14, N: 48, O: 48, P: 48 })) {
  excludedSheet.getRange(`${column}1:${column}${excludedDataEnd}`).format.columnWidth = width;
}
excludedSheet.getRange(`H${excludedDataStart}:H${excludedDataEnd}`).conditionalFormats.add("containsText", {
  text: "skipped",
  format: { fill: "#FFF2CC", font: { color: "#7F6000" } },
});

// Control specification keeps framing bytes outside the translation column.
setTitle(controlSheet, "A1:F1", "ControlSpec · main scenario/event framing");
controlSheet.mergeCells("A2:F2");
controlSheet.getRange("A2").values = [[
  "정적 추출에서 관측한 main record control. 0x05/0x06 argument는 숫자 parameter로 보존하며 번역문에 섞지 않습니다.",
]];
controlSheet.getRange("A2:F2").format = { fill: "#EAF1F8", font: { color: "#1F2937", size: 10 }, wrapText: true };
controlSheet.getRange("A2:F2").format.rowHeight = 24;
const controlColumns = ["code", "framing", "argument_bytes", "translation_action", "observed_count", "notes"];
controlSheet.getRange("A6:F6").values = [controlColumns];
styleHeader(controlSheet, "A6:F6");
controlSheet.getRange(`A7:F${6 + controlRows.length}`).values = controlRows;
styleData(controlSheet, `A7:F${6 + controlRows.length}`);
controlSheet.getRange(`C7:C${6 + controlRows.length}`).format.numberFormat = "0";
controlSheet.getRange(`E7:E${6 + controlRows.length}`).format.numberFormat = "0";
controlSheet.tables.add(`A6:F${6 + controlRows.length}`, true, "ScenarioControlSpecTable").style = "TableStyleMedium2";
controlSheet.freezePanes.freezeRows(6);
for (const [column, width] of Object.entries({ A: 12, B: 30, C: 15, D: 24, E: 16, F: 80 })) {
  controlSheet.getRange(`${column}1:${column}${6 + controlRows.length}`).format.columnWidth = width;
}

await fs.mkdir(outputDir, { recursive: true });

const summaryInspect = await wb.inspect({
  kind: "table",
  range: "Summary!A1:C25",
  include: "values,formulas",
  tableMaxRows: 25,
  tableMaxCols: 3,
  tableMaxCellChars: 160,
});
console.log(summaryInspect.ndjson);
const translationInspect = await wb.inspect({
  kind: "table",
  range: "TranslationMaster!A1:AC12",
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 29,
  tableMaxCellChars: 120,
});
console.log(translationInspect.ndjson);
const errors = await wb.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "scenario/event translation workbook formula error scan",
});
console.log(errors.ndjson);

const previewSpecs = [
  ["Summary", "A1:H30", "scenario_event_translation_summary_preview.png"],
  ["TranslationMaster", "A1:AC12", "scenario_event_translation_master_preview.png"],
  ["OwnerIndex", "A1:K12", "scenario_event_owner_index_preview.png"],
  ["ExcludedOverlap", "A1:P12", "scenario_event_excluded_overlap_preview.png"],
  ["ControlSpec", "A1:F12", "scenario_event_control_spec_preview.png"],
];
const previewPaths = [];
for (const [sheetName, range, fileName] of previewSpecs) {
  const preview = await wb.render({ sheetName, range, scale: 1, format: "png" });
  const previewPath = `${outputDir}/${fileName}`;
  await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
  previewPaths.push(previewPath);
}

const xlsx = await SpreadsheetFile.exportXlsx(wb);
await xlsx.save(outputPath);
console.log(JSON.stringify({
  outputPath,
  previewPaths,
  mainRows: mainRows.length,
  excludedRows: excludedRows.length,
  ownerRows: ownerRows.length,
  translatedRows: mainRows.filter((row) => row.translation_status === "translated").length,
  translatedSameRows: mainRows.filter((row) => row.translation_status === "translated_same").length,
  needsReviewRows: mainRows.filter((row) => row.translation_status === "needs_review").length,
  needsCharmapRows: mainRows.filter((row) => row.translation_status === "needs_charmap_resolution").length,
  mainExactSourceOverlap,
}, null, 2));
