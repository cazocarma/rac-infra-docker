"""Read application copy from the frontend revision used by browser tests."""
import json
from pathlib import Path


def app_label(root, key, locale):
    if locale not in ('es', 'es-CL', 'en', 'en-US') or not isinstance(key, str) or not key or key.startswith('@'):
        raise ValueError('Explicit supported app locale and message key required')
    language = locale.split('-')[0]
    path = Path(root).resolve().parent / 'rac-frontend-flutter' / 'lib/l10n' / ('app_' + language + '.arb')
    messages = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(messages, dict):
        raise ValueError('App label catalogue must be an object')
    value = messages.get(key)
    metadata = messages.get('@' + key, {})
    if not isinstance(value, str) or not value or not isinstance(metadata, dict) or metadata.get('legal_review') not in ('pending', 'approved'):
        raise ValueError('App label must have content and review metadata: ' + key)
    return value
