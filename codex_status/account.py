import base64
import json
import os
from pathlib import Path

CODEX_HOME = Path(os.environ.get('CODEX_HOME', Path.home()/'.codex'))


def read_account():
    path = CODEX_HOME/'auth.json'
    if not path.exists():
        return None
    auth = json.loads(path.read_text(encoding='utf-8'))
    if not auth.get('tokens'):
        return None
    encoded = auth['tokens']['id_token'].split('.')[1]
    payload = json.loads(base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)))
    identity = payload['https://api.openai.com/auth']
    return {'id': identity['chatgpt_account_id'], 'user_id': identity['chatgpt_user_id'],
            'name': payload['name'], 'email': payload['email']}
