import {readFileSync, writeFileSync, mkdirSync, readdirSync, lstatSync} from 'node:fs';
import {resolve, dirname, join} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';

export const FIELDS = ['id','project','episode','shot','filename','display_name','category','content_version','storage_version','storage_status','content_origin','recorded_location','location_basis','retrieval_link','retrieval_kind','sha256','hash_basis','size_bytes','evidence_basis','evidence_date','evidence_link','file_open','picture','audio','performed_checks','reported_checks','limitations','recovery_option','parent_record','attachment_label','parent_content_sha256','derivation_method'];
export const POLICY_KEYS = ['independent','author_reported','picture_audio','hashes','persistence','mixed_audio','missing'];

// Reject URLs outside the documented retrieval surfaces, including credentials,
// signed URLs, arbitrary query values, and fragments. Never rewrite an unsafe URL.
export function safeURL(value) {
  if (typeof value !== 'string' || !value) return null;
  try {
    const u = new URL(value);
    if (u.protocol !== 'https:' || u.username || u.password || u.port || u.hash) return null;
    if (u.hostname === 'github.com') {
      if (u.search || !/^\/[\w.-]+\/[\w.-]+(?:\/[\w./%+-]*)?$/.test(u.pathname)) return null;
    } else if (u.hostname === 'chatgpt.com') {
      if (/^\/space\/page_[\w-]+$/.test(u.pathname)) { if (u.search) return null; }
      else if (u.pathname === '/library') {
        if ([...u.searchParams.keys()].length !== 2 || u.searchParams.getAll('file_id').length !== 1 || u.searchParams.getAll('account_id').length !== 1 || u.searchParams.get('account_id') !== 'personal' || !/^libfile_[\w-]+$/.test(u.searchParams.get('file_id') || '')) return null;
      } else return null;
    } else return null;
    return u.href;
  } catch { return null; }
}

export function exportRows(rows, scope) {
  return rows.filter(r => scope.includes(r.project)).map(r => Object.fromEntries(FIELDS.map(key => [key, key.endsWith('_link') ? safeURL(r[key]) : r[key] ?? null])));
}

export function csvCell(value) {
  let s = Array.isArray(value) ? value.join(' | ') : value == null ? '' : String(value);
  if (/^[\s]*[=+@-]/.test(s)) s = "'" + s;
  return '"' + s.replaceAll('"', '""') + '"';
}

export function csvText(rows) {
  return [FIELDS.map(csvCell).join(','), ...rows.map(r => FIELDS.map(k => csvCell(r[k])).join(','))].join('\r\n');
}

export function scriptJSON(data) {
  return JSON.stringify(data).replaceAll('<', '\\u003c').replaceAll('\u2028','\\u2028').replaceAll('\u2029','\\u2029');
}

function fail(path, reason) { throw new Error(`Invalid inventory at ${path}: ${reason}`); }

// Implements the JSON Schema keywords used by inventory.schema.json. No external
// schema resolvers, network calls, dynamic code, or provider plugins are loaded.
export function validate(value, schema, path = '$') {
  if (schema.type) {
    const types = Array.isArray(schema.type) ? schema.type : [schema.type];
    const matches = types.some(t => t === 'null' ? value === null : t === 'array' ? Array.isArray(value) : t === 'object' ? value !== null && typeof value === 'object' && !Array.isArray(value) : t === 'integer' ? Number.isSafeInteger(value) : typeof value === t);
    if (!matches) fail(path, 'wrong value type');
  }
  if (schema.enum && !schema.enum.includes(value)) fail(path, 'value outside allowed vocabulary');
  if (value === null) return;
  if (typeof value === 'string') {
    if (schema.maxLength != null && value.length > schema.maxLength) fail(path,'text too long');
    if (schema.minLength != null && value.length < schema.minLength) fail(path,'text required');
    if (schema.pattern && !new RegExp(schema.pattern).test(value)) fail(path,'pattern mismatch');
  }
  if (typeof value === 'number' && schema.minimum != null && value < schema.minimum) fail(path,'below minimum');
  if (Array.isArray(value)) {
    if (schema.minItems != null && value.length < schema.minItems) fail(path,'too few items');
    if (schema.maxItems != null && value.length > schema.maxItems) fail(path,'too many items');
    if (schema.uniqueItems && new Set(value.map(v=>JSON.stringify(v))).size !== value.length) fail(path,'duplicate items');
    if (schema.items) value.forEach((v,i) => validate(v,schema.items,`${path}[${i}]`));
  } else if (value && typeof value === 'object') {
    for (const key of schema.required || []) if (!Object.hasOwn(value,key)) fail(path+'.'+key,'missing field');
    for (const [key,v] of Object.entries(value)) {
      if (schema.properties && Object.hasOwn(schema.properties,key)) validate(v,schema.properties[key],path+'.'+key);
      else if (schema.additionalProperties === false) fail(path,'unexpected field');
    }
  }
}

export function normalize(input, projects, schema) {
  if (!Array.isArray(projects) || projects.length === 0 || projects.length > 20 || projects.some(p => typeof p !== 'string' || !p.trim()) || new Set(projects).size !== projects.length) throw new Error('Supply a distinct, explicit project allowlist.');
  if (!input || !Array.isArray(input.records) || input.records.length > 10000) throw new Error('Expected at most 10,000 inventory records.');
  const records = input.records.filter(r => r && projects.includes(r.project)).map(r => {
    const copy = Object.fromEntries(FIELDS.map(k => [k,r[k] ?? null]));
    copy.performed_checks = r.performed_checks ?? r.checks_today ?? [];
    copy.reported_checks ??= []; copy.limitations ??= [];
    for (const k of ['retrieval_link','evidence_link']) {
      if (copy[k] && !safeURL(copy[k])) fail('records','unsafe retrieval or evidence URL');
      copy[k] = safeURL(copy[k]);
    }
    return copy;
  });
  const data = {
    schema_version:'2.0', title:input.title || 'Production recovery inventory',
    snapshot_date:input.snapshot_date, checked_at_utc:input.checked_at_utc,
    review_date:input.review_date || input.snapshot_date,
    status:'Read-only evidence snapshot', scope:[...projects],
    scope_limits:input.scope_limits || [],
    verification_policy:Object.fromEntries(POLICY_KEYS.map(k=>[k,input.verification_policy?.[k] || 'Not established.'])),
    lineage_notes:(input.lineage_notes || []).filter(n=>n && projects.includes(n.project)).map(n=>({project:n.project,version:n.version,description:n.description})),
    records
  };
  validate(data,schema);
  if (new Set(records.map(r=>r.id)).size !== records.length) fail('records','duplicate identities');
  for (const r of records) {
    if (r.parent_record && !records.some(p => p.id === r.parent_record && p.project === r.project)) fail('records','missing or cross-project parent');
    if (r.content_origin === 'Unresolved requirement' && r.filename !== null) fail('records','requirements must not invent filenames');
    if (/mixed.*extract|extract.*mix/i.test(r.content_origin) && (!r.parent_content_sha256 || !r.derivation_method)) fail('records','mixed extraction requires parent hash and method');
    if (/Temporary/.test(r.storage_status) && r.evidence_basis === 'Independently verified') fail('records','temporary evidence cannot be promoted to a verified backup');
  }
  // A supplemental screening check, not a claim to detect every kind of private
  // content. Review allowed free text before publication, even in a private Site.
  const serialized=JSON.stringify(data);
  if (/(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{24,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|Bearer\s+[A-Za-z0-9._-]{20,}|(?:api[_-]?key|access[_-]?token|password)\s*[:=]\s*[^\s"\\]{8,})/i.test(serialized)) throw new Error('Possible credential content detected; review the input privately.');
  return data;
}

export function build({inputPath, outputPath, projects, sourceDirectory = dirname(fileURLToPath(import.meta.url))}) {
  const schema = JSON.parse(readFileSync(join(sourceDirectory,'inventory.schema.json'),'utf8'));
  const data = normalize(JSON.parse(readFileSync(inputPath,'utf8')),projects,schema);
  const template = readFileSync(join(sourceDirectory,'dashboard.template.html'),'utf8');
  const core = 'const FIELDS='+JSON.stringify(FIELDS)+';\n'+[safeURL,exportRows,csvCell,csvText].map(f=>f.toString()).join('\n');
  if (template.split('__INVENTORY_JSON__').length !== 2 || template.split('/*__EXPORT_CORE__*/').length !== 2) throw new Error('Template placeholders must occur exactly once.');
  const html = template.replace('__INVENTORY_JSON__',scriptJSON(data)).replace('/*__EXPORT_CORE__*/',core);
  const out=resolve(outputPath);
  try { if (lstatSync(out).isSymbolicLink() || readdirSync(out).length) throw new Error('Output must be an empty non-symlink directory.'); }
  catch(e) { if (e.code === 'ENOENT') mkdirSync(out,{recursive:true}); else throw e; }
  const files = {'index.html':html,'inventory.json':JSON.stringify(data,null,2)+'\n','inventory.csv':csvText(exportRows(data.records,data.scope))};
  for(const [name,text] of Object.entries(files)) writeFileSync(join(out,name),text,{flag:'wx'});
  const manifest={schema_version:'1.0',snapshot_date:data.snapshot_date,files:Object.entries(files).map(([name,text])=>({filename:name,size_bytes:Buffer.byteLength(text),sha256:createHash('sha256').update(text).digest('hex')}))};
  writeFileSync(join(out,'snapshot-manifest.json'),JSON.stringify(manifest,null,2)+'\n',{flag:'wx'});
  return {record_count:data.records.length,requirement_count:data.records.filter(r=>r.content_origin==='Unresolved requirement').length,output_directory:out};
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const args=process.argv.slice(2);const values={};
  try {
    for(let i=0;i<args.length;i+=2){if(!['--input','--output','--projects'].includes(args[i]) || !args[i+1] || Object.hasOwn(values,args[i])) throw new Error('Usage: node build.mjs --input inventory.json --output EMPTY_DIRECTORY --projects "Project A,Project B"'); values[args[i]]=args[i+1];}
    if(Object.keys(values).length!==3) throw new Error('All three flags are required.');
    console.log(JSON.stringify(build({inputPath:values['--input'],outputPath:values['--output'],projects:values['--projects'].split(',').map(s=>s.trim())})));
  } catch(e) { console.error(e.message); process.exitCode=1; }
}
