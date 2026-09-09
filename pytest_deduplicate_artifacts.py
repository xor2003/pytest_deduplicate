"""Stable review identities, conservative baseline diffs and standalone HTML."""
import hashlib
import json
from pathlib import Path


def hash_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def decorate(report):
    root = Path(report['root'])
    paths = {f for test in report['tests'] for f in test['file_arcs']}
    paths.update(test['location']['file'] for test in report['tests'])
    hashes = {}
    for file in sorted(paths):
        try:
            hashes[file] = hashlib.sha256((root / file).read_bytes()).hexdigest()
        except OSError:
            hashes[file] = None
    scope = dict(report['scope'])
    scope['measurement'] = report.get('import', {}).get('phase_scope', 'live-per-test-protocol')
    scope['omit'] = [p for p in scope.get('omit', []) if not p.endswith('pytest_deduplicate*.py')]
    report['evidence'] = {'files': hashes, 'scope_sha256': hash_json(scope),
                          'inventory_sha256': hash_json(sorted(t['nodeid'] for t in report['tests']))}
    for finding in report['findings']:
        finding['id'] = hash_json([finding['kind'], sorted(finding['tests']), sorted(finding['other_tests'])])[:24]
        finding['evidence_sha256'] = hash_json([report['evidence'], finding['shared'], finding['unique'], finding['other_unique'], finding.get('assessment')])


def compare_reports(report, baseline):
    if baseline.get('schema_version') != report['schema_version'] or not baseline.get('evidence'):
        raise ValueError('baseline lacks compatible review evidence; regenerate it')
    healthy = all(not r['errors'] and not r['pytest_exit_code'] for r in [report, baseline])
    comparable = healthy and all(report['evidence'][k] == baseline['evidence'][k]
                                for k in ('scope_sha256', 'inventory_sha256'))
    old = {f['id']: f for f in baseline['findings']}
    new = {f['id']: f for f in report['findings']}
    changed = [key for key in new.keys() & old.keys()
               if any(new[key].get(field) != old[key].get(field)
                      for field in ('shared', 'unique', 'other_unique', 'assessment'))]
    return {'comparable': comparable, 'new': sorted(new.keys() - old.keys()),
            'resolved': sorted(old.keys() - new.keys()) if comparable else [],
            'unobserved': [] if comparable else sorted(old.keys() - new.keys()),
            'changed': sorted(changed),
            'unchanged': sorted(new.keys() & old.keys() - set(changed)),
            'note': 'Resolved requires successful runs with identical scope and collected inventory.'}


def apply_reviews(report, document):
    if document.get('schema_version') != 1 or not isinstance(document.get('reviews'), list):
        raise ValueError('invalid suppression document')
    entries = {}
    for review in document['reviews']:
        if not isinstance(review.get('reason'), str) or not review['reason'].strip():
            raise ValueError('every suppression needs a nonempty review reason')
        if not isinstance(review.get('reviewed_at'), str) or not review['reviewed_at'].strip():
            raise ValueError('every suppression needs reviewed_at')
        if review['id'] in entries:
            raise ValueError('duplicate suppression ID')
        entries[review['id']] = review
    used = set()
    complete = not report['errors'] and not report['pytest_exit_code'] and all(report['evidence']['files'].values())
    for finding in report['findings']:
        review = entries.get(finding['id'])
        if review:
            used.add(finding['id'])
            valid = complete and review.get('evidence_sha256') == finding['evidence_sha256']
            finding['review'] = dict(review, status='reviewed' if valid else 'needs_revalidation')
    report['reviews'] = {'unobserved_ids': sorted(set(entries) - used),
                         'note': 'Reviewed findings remain in JSON. Changed evidence invalidates suppression.'}


def review_template(report):
    return {'schema_version': 1, 'reviews': [
        {'id': f['id'], 'evidence_sha256': f['evidence_sha256'], 'reason': '', 'reviewed_at': ''}
        for f in report['findings']]}


def write_html(report, destination):
    # The viewer reads no files. Embed bounded snippets only when current bytes
    # match the report hash, so changed source cannot masquerade as measured code.
    sources = {}
    referenced = {}
    for finding in report['findings']:
        for field in ('shared', 'unique', 'other_unique'):
            for file, arcs in finding[field].items():
                referenced.setdefault(file, set()).update(abs(n) for arc in arcs for n in arc if n)
    for file, endpoints in referenced.items():
        try:
            raw = (Path(report['root']) / file).read_bytes()
            if hashlib.sha256(raw).hexdigest() != report.get('evidence', {}).get('files', {}).get(file):
                sources[file] = {'status': 'source changed or unavailable'}
                continue
            import io
            import tokenize
            encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
            lines = raw.decode(encoding).splitlines()
            wanted = sorted({n for end in endpoints for n in range(max(1, end - 1), min(len(lines), end + 1) + 1)})
            sources[file] = {'status': 'matches report hash', 'truncated': len(wanted) > 500,
                             'lines': [{'number': n, 'text': lines[n - 1]} for n in wanted[:500]]}
        except (OSError, UnicodeError, SyntaxError):
            sources[file] = {'status': 'source unavailable'}
    # Escaping < neutralizes </script> in source, parameter IDs and review reasons.
    payload = json.dumps(dict(report, html_sources=sources), ensure_ascii=True).replace('<', '\\u003c').replace('&', '\\u0026')
    template = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Coverage overlap review</title>
<style>body{font:16px system-ui;margin:2em;max-width:1100px;background:#f5f7fa;color:#18232f}
label{display:inline-block;margin:.5em}input,select{padding:.5em}article{background:white;padding:1em;margin:1em 0;border:1px solid #cbd5df;border-radius:8px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}summary{cursor:pointer}h2{font-size:18px}small{color:#465568}</style>
<h1>Coverage overlap review</h1><p id="warning"></p>
<label>Module or test <input id="query" type="search"></label>
<label>Conclusion <select id="status"><option value="">All</option></select></label>
<label>Minimum total seconds <input id="duration" type="number" min="0" step="0.01" value="0"></label>
<label><input id="hide" type="checkbox"> Hide reviewed unchanged findings</label>
<p id="count" aria-live="polite"></p><main id="findings"></main>
<script id="data" type="application/json">PAYLOAD</script>
<script>
const report=JSON.parse(document.getElementById('data').textContent);
const get=id=>document.getElementById(id), tests=new Map(report.tests.map(t=>[t.nodeid,t]));
get('warning').textContent=report.warning;
for(const status of [...new Set(report.findings.map(f=>f.assessment.status))].sort()) {
 const option=document.createElement('option');option.value=status;option.textContent=status.replaceAll('_',' ');get('status').append(option);
}
function node(tag,text){const n=document.createElement(tag);n.textContent=text;return n;}
function render(){
 const query=get('query').value.toLowerCase(),status=get('status').value;
 const minimum=Number(get('duration').value)||0, hide=get('hide').checked;
 get('findings').replaceChildren();let count=0;
 for(const f of report.findings){
  const ids=[...new Set([...f.tests,...f.other_tests])];
  const seconds=ids.reduce((s,id)=>s+(tests.get(id)?.duration||0),0);
  if(status&&f.assessment.status!==status||seconds<minimum)continue;
  if(hide&&f.review?.status==='reviewed')continue;
  if(query&&!JSON.stringify([ids,Object.keys(f.shared),Object.keys(f.unique),Object.keys(f.other_unique)]).toLowerCase().includes(query))continue;
  count++; const card=node('article','');
  card.append(node('h2',f.kind+' · '+f.assessment.status.replaceAll('_',' ')),node('pre',ids.join('\\n')),
   node('small',seconds.toFixed(6)+' total seconds · '+f.shared_arc_count+' shared arcs · '+f.unique_arc_count+' unique arcs'));
  if(f.review)card.append(node('p',f.review.status+': '+f.review.reason));
  const details=node('details','');details.append(node('summary','Exact files, arcs, phases and check evidence'));
  details.append(node('pre',JSON.stringify({shared:f.shared,unique:f.unique,other_unique:f.other_unique,assessment:f.assessment,
   tests:ids.map(id=>tests.get(id)),id:f.id,evidence_sha256:f.evidence_sha256},null,2)));
  card.append(details);
  const source=node('details','');source.append(node('summary','Source excerpts (up to 500 lines per file)'));
  for(const file of new Set([...Object.keys(f.shared),...Object.keys(f.unique),...Object.keys(f.other_unique)])){
   const excerpt=report.html_sources[file];source.append(node('h3',file));
   source.append(node('small',excerpt.status+(excerpt.truncated?' · truncated':'')));
   if(excerpt.lines)source.append(node('pre',excerpt.lines.map(line=>line.number+': '+line.text).join('\\n')));
  }
  card.append(source);get('findings').append(card);
 }
 get('count').textContent=count+' of '+report.findings.length+' findings';
}
for(const id of ['query','status','duration','hide'])get(id).addEventListener('input',render);
render();
</script></html>'''
    Path(destination).write_text(template.replace('PAYLOAD', payload), encoding='utf-8')
