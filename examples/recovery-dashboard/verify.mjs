import {strict as assert} from 'node:assert';
import {readFileSync,writeFileSync,mkdtempSync,rmSync,readdirSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {build,normalize,validate,safeURL,exportRows,csvCell,csvText,scriptJSON,FIELDS} from './build.mjs';
const root=dirname(fileURLToPath(import.meta.url));
const schema=JSON.parse(readFileSync(join(root,'inventory.schema.json'),'utf8'));
const fixture=JSON.parse(readFileSync(join(root,'inventory.example.json'),'utf8'));
const copy=()=>structuredClone(fixture);let passed=0;
function check(name,fn){fn();passed++;console.log('PASS '+name)}
check('synthetic input validates',()=>validate(fixture,schema));
check('scope filtering excludes unrelated project rows and unknown private fields',()=>{
 const x=copy();x.records.push({...x.records[0],id:'unrelated',project:'Unrelated personal project'});x.records[0].credential='must-not-export';x.raw_provider_response={password:'must-not-export'};
 const result=normalize(x,['Example film'],schema);assert.equal(result.records.length,3);assert(!JSON.stringify(result).includes('must-not-export'));assert(!JSON.stringify(result).includes('unrelated'));
});
check('runtime exports retain only fixed fields and selected projects',()=>{
 const rows=exportRows([{...fixture.records[0],secret:'hidden'}, {...fixture.records[0],id:'other',project:'Private other project'}],['Example film']);assert.equal(rows.length,1);assert.deepEqual(Object.keys(rows[0]),FIELDS);assert(!JSON.stringify(rows).includes('hidden'));
});
check('unsafe URLs rejected including encoded query credentials and lookalikes',()=>{
 for(const v of ['javascript:alert(1)','data:text/html,hello','http://chatgpt.com/space/page_test','https://u:p@github.com/example/repo','https://github.com.evil.test/example/repo','https://chatgpt.com/library?file_id=libfile_test&account_id=personal&token=secret','https://chatgpt.com/library?file_id=secret&account_id=personal','https://chatgpt.com/space/page_test#token','https://github.com/example/repo?X-Amz-Signature=secret','https://chatgpt.com/library?file_id=libfile_x&file_id=libfile_y&account_id=personal','https://chatgpt.com/?file_id=libfile_x&account_id=personal'])assert.equal(safeURL(v),null);
});
check('known stable retrieval URLs remain usable',()=>{
 for(const v of ['https://chatgpt.com/space/page_test','https://chatgpt.com/library?file_id=libfile_test&account_id=personal','https://github.com/example/repository/blob/main/README.md'])assert.equal(safeURL(v),v);
});
check('unsafe inventory link blocks build rather than leaking',()=>{const x=copy();x.records[0].retrieval_link='https://chatgpt.com/space/page_test?token=secret';assert.throws(()=>normalize(x,x.scope,schema),/unsafe/)});
check('CSV cells escape formulas, embedded quotes and line breaks',()=>{
 for(const s of ['=SUM(1)','+cmd','-1+2','@SUM(1)',' \t=1','\n+1'])assert(csvCell(s).startsWith('"\''));assert.equal(csvCell('a,"b"\nc'),'"a,""b""\nc"');assert(csvText([fixture.records[0]]).startsWith('"id","project"'));
});
check('HTML-closing content cannot escape the JSON script block',()=>{
 const s=scriptJSON({value:'</script><img src=x onerror=alert(1)>\u2028'});assert(!s.includes('<'));assert.deepEqual(JSON.parse(s),{value:'</script><img src=x onerror=alert(1)>\u2028'});
});
check('wrong types cannot smuggle nested provider data through text fields',()=>{const x=copy();x.records[0].filename={secret:'nested'};assert.throws(()=>normalize(x,x.scope,schema),/wrong value type/)});
check('record identifiers must be unique',()=>{const x=copy();x.records.push({...x.records[0]});assert.throws(()=>normalize(x,x.scope,schema),/duplicate identities/)});
check('invalid hashes rejected and commit IDs not accepted as SHA-256',()=>{const x=copy();x.records[0].sha256='a'.repeat(40);assert.throws(()=>normalize(x,x.scope,schema),/pattern mismatch/)});
check('cross-project lineage rejected',()=>{const x=copy();x.records[0].parent_record='example-source';assert.throws(()=>normalize(x,x.scope,schema),/cross-project parent/)});
check('mixed-track derivatives require parent hash and derivation method',()=>{
 const x=copy();x.records[0].content_origin='Mixed soundtrack extraction';assert.throws(()=>normalize(x,x.scope,schema),/parent hash and method/);x.records[0].parent_content_sha256='a'.repeat(64);x.records[0].derivation_method='Synthetic demux example';assert.equal(normalize(x,x.scope,schema).records[0].content_origin,'Mixed soundtrack extraction');
});
check('missing originals never receive invented filenames',()=>{const x=copy();x.records.at(-1).filename='made-up.wav';assert.throws(()=>normalize(x,x.scope,schema),/invent filenames/)});
check('temporary reported files cannot be promoted to verified backups',()=>{const x=copy();x.records[0].storage_status='Temporary / reported';x.records[0].evidence_basis='Independently verified';assert.throws(()=>normalize(x,x.scope,schema),/promoted/)});
check('legacy performed-check field keeps its evidence date',()=>{const x=copy();delete x.records[0].performed_checks;x.records[0].checks_today=['Historical parse'];const r=normalize(x,x.scope,schema).records[0];assert.deepEqual(r.performed_checks,['Historical parse']);assert.equal(r.evidence_date,'2000-01-01');assert(!Object.hasOwn(r,'checks_today'))});
check('credential-like free text blocks the build without printing the value',()=>{const x=copy();x.records[0].limitations=['password=synthetic-secret-value'];assert.throws(()=>normalize(x,x.scope,schema),e=>e.message.includes('Possible credential')&&!e.message.includes('synthetic-secret'))});
const tmp=mkdtempSync(join(tmpdir(),'recovery-viewer-test-'));
try {
 check('built HTML, JSON, CSV and manifest are consistent',()=>{
  const output=join(tmp,'output');const result=build({inputPath:join(root,'inventory.example.json'),outputPath:output,projects:fixture.scope});assert.equal(result.record_count,4);
  const html=readFileSync(join(output,'index.html'),'utf8'),data=JSON.parse(readFileSync(join(output,'inventory.json'),'utf8'));
  assert.deepEqual(JSON.parse(html.match(/<script id="inventory-data" type="application\/json">([\s\S]*?)<\/script>/)[1]),data);
  assert.equal(readFileSync(join(output,'inventory.csv'),'utf8'),csvText(exportRows(data.records,data.scope)));
  const manifest=JSON.parse(readFileSync(join(output,'snapshot-manifest.json'),'utf8'));
  for(const f of manifest.files){const b=readFileSync(join(output,f.filename));assert.equal(b.length,f.size_bytes);assert.equal(createHash('sha256').update(b).digest('hex'),f.sha256)}
  for(const s of [...html.matchAll(/<script(?: [^>]*)?>([\s\S]*?)<\/script>/g)].filter(m=>!m[0].includes('type="application/json"')))new Function(s[1]);
  assert(html.includes("connect-src 'none'"));assert(!/\b(fetch\s*\(|XMLHttpRequest|WebSocket\s*\(|localStorage|sessionStorage|\.innerHTML\s*=)/.test(html));
  assert(html.includes('id="version"'));assert(html.includes('Performed checks at evidence date'));
 });
 check('existing output and originals are preserved on a refused build',()=>{
  const output=join(tmp,'output');writeFileSync(join(output,'sentinel.txt'),'preserve me');const before=readFileSync(join(output,'index.html'));
  assert.throws(()=>build({inputPath:join(root,'inventory.example.json'),outputPath:output,projects:fixture.scope}),/empty non-symlink/);assert.equal(readFileSync(join(output,'sentinel.txt'),'utf8'),'preserve me');assert.deepEqual(readFileSync(join(output,'index.html')),before);
 });
 check('source directory contains only the approved eight files',()=>assert.deepEqual(readdirSync(root).sort(),['.gitignore','DESIGN.md','README.md','build.mjs','dashboard.template.html','inventory.example.json','inventory.schema.json','verify.mjs'].sort()));
} finally {rmSync(tmp,{recursive:true,force:true})}
console.log(`${passed} checks passed; no provider calls or production files used.`);
