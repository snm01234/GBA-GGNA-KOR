import fs from 'node:fs/promises';
import { FileBlob, SpreadsheetFile } from 'file:///C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs';
const root = 'D:/monoeye/advance';
const dir = `${root}/outputs/20260909_ggen_advance_creuset_names`;
const workbookPath = `${root}/integrated/translation/ggen_advance_translation_master.xlsx`;
const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(workbookPath));
const sheet = wb.worksheets.getItem('TranslationMaster');
const previewOnly = process.argv.includes('--preview');
if (previewOnly) {
  const png = await wb.render({sheetName:'TranslationMaster', range:'N19065:P19068',scale:1,format:'png'});
  await fs.writeFile(`${dir}/workbook_before.png`,new Uint8Array(await png.arrayBuffer()));
  console.log('Preview saved');
} else {
  const data = JSON.parse(await fs.readFile(`${root}/integrated/translation/ggen_advance_translation_merged.json`,'utf8'));
  const before = JSON.parse(await fs.readFile(`${dir}/before_ggen_advance_translation_merged.json`,'utf8'));
  const report = JSON.parse(await fs.readFile(`${dir}/manifest.json`,'utf8'));
  const fields = {P:'translation_ko',Q:'translation_status',R:'translation_source',S:'review_status',Y:'qa_status',Z:'overlay_batch_id',AA:'translator_notes',AC:'translation_payload_sha256',AH:'translation_segments'};
  for (const job of report.jobs) {
    const index = data.records.findIndex(r=>r.record_id===job.record_id);
    const row = data.records[index];
    const n=index+7;
    if(sheet.getRange(`A${n}`).values[0][0]!==job.record_id || sheet.getRange(`P${n}`).values[0][0]!==before.records[index].translation_ko) throw Error(`Workbook drift ${job.record_id}`);
    for(const [col,key] of Object.entries(fields)) {
      const value=row[key];
      sheet.getRange(`${col}${n}`).values=[[Array.isArray(value)?JSON.stringify(value):value??'']];
    }
  }
  const summary=wb.worksheets.getItem('Summary');
  const prevIdentity=before.identity.translation_overlay_identity_sha256;
  for(let n=1;n<=6;n++) {
    const cell=summary.getRange(`A${n}`);
    const text=cell.values[0]?.[0];
    if(typeof text==='string' && text.includes(prevIdentity)) cell.values=[[text.replace(prevIdentity,data.identity.translation_overlay_identity_sha256)]];
  }
  wb.recalculate();
  const png=await wb.render({sheetName:'TranslationMaster',range:'N19065:P19068',scale:1,format:'png'});
  await fs.writeFile(`${dir}/workbook_after.png`,new Uint8Array(await png.arrayBuffer()));
  await (await SpreadsheetFile.exportXlsx(wb)).save(`${dir}/translation_master_updated.xlsx`);
  console.log(JSON.stringify({changedRecords:report.jobs.length,output:`${dir}/translation_master_updated.xlsx`}));
}
