"""Read-only snapshot integrity and recognition inventory; outputs never edit source bytes."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from ctfm.measurement import analyze, parse_table
from ctfm.measurement.layouts import retention_dataset
from ctfm.measurement.recognition import recognize_source
from ctfm_api.contracts import AnalysisRequest


def verify(root):
    manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8-sig'))
    index = defaultdict(list)
    for entry in manifest['files']:
        data = (root/entry['path']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry['sha256'], entry['path']
        assert len(data) == entry['bytes'], entry['path']
        index[entry['sha256']].append(entry['path'])
    entries = []
    for entry in manifest['files']:
        category = entry['path'].split('/')[1]
        path = root/entry['path']
        if category not in ('LTD,LTP','IV Sweep','D2D','Retention','C2C') or path.suffix not in ('.csv','.xlsx'):
            continue
        data = path.read_bytes()
        source = recognize_source(data, path.name, str(uuid5(NAMESPACE_URL,entry['path'])), index[entry['sha256']])
        proposals = source.pop('proposals')
        for proposal in proposals:
            AnalysisRequest.model_validate(proposal)
        row = dict(path=entry['path'], sha256=entry['sha256'], kind=source['kind'], condition_id=source['condition_id'],
                   status=source['status'], issues=source['issues'], request_count=len(proposals), pulse=source['pulse'])
        layout = source['layout'] or {}
        if source['kind']=='iv':
            row.update(block_count=layout['block_count'], invalid_blocks=[b for b in layout['blocks'] if b['status']!='ok'],
                       segment_count=sum(len(b.get('segments',[])) for b in layout['blocks']))
        elif source['kind'] in ('pulse_states','retention') and proposals:
            item = proposals[0]['inputs'][0]
            if source['kind']=='pulse_states':
                table = parse_table(data,path.name)
                dataset = dict(item, filename=path.name, sha256=entry['sha256'], rows=table['rows'], source_rows=table['source_rows'])
            else:
                dataset = retention_dataset(data,path.name,columns=item['selection']['columns'],condition_id=item['condition_id'],device_id=item['device_id'],
                    file_id=item['file_id'],sha256=entry['sha256'],source_label=item['source_label'],units=item['units'],read_vgs_v=item['read_vgs_v'],header_read_vgs_v=item.get('header_read_vgs_v'))
                row.update(read_vgs_v=item['read_vgs_v'], source_label=item['source_label'], source_rows=dataset['source_rows'], skipped_blank_rows=dataset['skipped_blank_rows'])
            result = analyze(source['kind'], [dataset], {})
            row.update(summaries=result['summaries'], exclusions=result['exclusions'], raw_row_count=len(result['tables']['raw']))
        entries.append(row)
    return dict(integrity_files=len(manifest['files']), measurement_entries=len(entries), unique_measurement_hashes=len({e['sha256'] for e in entries}),
                categories=dict(Counter(e['path'].split('/')[1] for e in entries)), entries=entries)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('data/team-snapshot/2026-09-29'))
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    report=verify(args.root)
    args.out.write_text(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='entries'},ensure_ascii=False))
