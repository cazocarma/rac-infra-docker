"""Compare browser expectations with labels emitted by the pinned Flutter SDK."""
import json
from pathlib import Path
import sys
from flutter_material_labels import FlutterMaterialLabels


def check(output):
    records = {}
    for line in output.splitlines():
        if not line.startswith('MATERIAL_LABELS_JSON:'):
            continue
        item = json.loads(line.removeprefix('MATERIAL_LABELS_JSON:'))
        language = item.get('locale')
        if language not in ('es', 'en') or language in records:
            raise ValueError('Missing, unsupported or duplicate Material contract locale')
        labels = FlutterMaterialLabels(language)
        expected = {'locale': language, 'back': labels.back,
                    'open_navigation': labels.open_navigation,
                    'remaining': {str(n): labels.remaining(n) for n in (0, 1, 1995, 2000)}}
        if item != expected:
            raise ValueError('Material accessibility contract drift for ' + language)
        records[language] = item
    if set(records) != {'es', 'en'}:
        raise ValueError('Material contract requires both explicit locales')


if __name__ == '__main__':
    check(Path(sys.argv[1]).read_text(encoding='utf-8'))
    print('PASS: browser labels match actual pinned Flutter Material semantics in es/en')
