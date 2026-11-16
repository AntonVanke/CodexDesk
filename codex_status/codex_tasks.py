import json
from pathlib import Path
import sqlite3

import psutil
from account import CODEX_HOME, read_account


def activity_for(name):
    if 'apply_patch' in name or 'fileChange' in name:
        return '修改文件'
    if 'exec_command' in name or 'commandExecution' in name:
        return '执行命令'
    if 'web' in name.lower() or 'search' in name.lower():
        return '检索资料'
    if 'wait' in name or 'sleep' in name:
        return '等待结果'
    return '执行工具'


class Rollout:
    def __init__(self, path, offset):
        self.path = Path(path)
        self.offset = offset
        if offset:
            with self.path.open('rb') as stream:
                stream.seek(offset-1)
                if stream.read(1) != b'\n':
                    stream.readline()
                    self.offset = stream.tell()
        self.questions = {}
        self.calls = {}
        self.activity = '处理中'

    def consume(self, event):
        payload = event.get('payload', {})
        kind = payload.get('type')
        if event['type'] == 'event_msg':
            if kind == 'task_started':
                self.calls.clear()
                self.questions.clear()
                self.activity = '思考中'
            elif kind == 'item_started':
                item = payload['item']
                self.activity = activity_for(item['type'])
            return
        if event['type'] != 'response_item':
            return
        if kind == 'reasoning':
            self.activity = '思考中'
        elif kind in ('function_call', 'custom_tool_call'):
            name = payload['name']
            call_id = payload['call_id']
            self.calls[call_id] = name
            if name.rsplit('.', 1)[-1] in ('request_user_input', 'request_user_input_async'):
                arguments = json.loads(payload['arguments'])
                for index, question in enumerate(arguments['questions']):
                    options = [option if isinstance(option, str) else option['label']
                               for option in question.get('options', [])]
                    self.questions[(call_id, index)] = {
                        'id': f'{call_id}:{index}',
                        'text': question.get('title') or question['question'],
                        'options': options,
                    }
            else:
                self.activity = activity_for(name + ' ' + payload.get('input', ''))
        elif kind in ('function_call_output', 'custom_tool_call_output'):
            name = self.calls.pop(payload.get('call_id'), '')
            if name.rsplit('.', 1)[-1] == 'request_user_input':
                self.questions = {key: value for key, value in self.questions.items()
                                  if key[0] != payload['call_id']}
            self.activity = '处理中'
        elif kind == 'message':
            if payload['role'] == 'assistant':
                self.activity = '整理结果' if payload.get('phase') in ('final', 'final_answer') else '正在回复'
            elif payload['role'] == 'user':
                for part in payload.get('content', []):
                    text = part.get('text', '')
                    if text.startswith('<send_user_message_question_reply>'):
                        replies = json.loads(text.split('>', 1)[1].split('</', 1)[0])
                        for reply in replies:
                            _, call_id, index = json.loads(reply['questionItemId'])
                            self.questions.pop((call_id, index), None)
                    elif text and not text.startswith(('<environment_context>', '# AGENTS.md')):
                        self.questions.clear()

    def read(self):
        with self.path.open('rb') as stream:
            stream.seek(self.offset)
            while line := stream.readline():
                if not line.endswith(b'\n'):
                    break
                self.consume(json.loads(line))
                self.offset = stream.tell()


class CodexTasks:
    def __init__(self):
        self.home = CODEX_HOME
        self.rollouts = {}
        self.epoch = None

    def snapshot(self, account=None):
        account = account or read_account()
        empty = {'tasks': [], 'running': 0, 'waiting': 0, 'unread': 0}
        if not account or not (self.home/'thread_history_1.sqlite').exists():
            return empty
        servers = [process.create_time() for process in psutil.process_iter(['name'])
            if process.info['name'] == 'codex.exe'
            and 'app-server' in process.cmdline()]
        epoch = min(servers) if servers else float('inf')
        if epoch != self.epoch:
            self.rollouts.clear()
            self.epoch = epoch
        with sqlite3.connect((self.home / 'thread_history_1.sqlite').as_uri() + '?mode=ro', uri=True) as db:
            db.row_factory = sqlite3.Row
            db.execute('ATTACH DATABASE ? AS meta', ((self.home / 'state_5.sqlite').as_uri() + '?mode=ro',))
            rows = db.execute('''
                SELECT m.id, COALESCE(NULLIF(m.name,''), NULLIF(m.title,''),'新任务') AS title,
                       m.rollout_path, t.turn_id, t.status, COALESCE(t.started_at,0) AS started_at,
                       t.rollout_byte_offset AS start_offset, r.first_unread_turn IS NOT NULL AS unread
                FROM meta.threads m LEFT JOIN thread_turns t ON t.thread_id=m.id
                LEFT JOIN meta.thread_read_receipts r ON r.thread_id=m.id
                WHERE m.archived=0 AND (t.started_at>=? OR r.first_unread_turn IS NOT NULL)
                  AND (m.creator_account_id=? OR (m.creator_account_id IS NULL AND t.started_at>=? AND t.status='inProgress'))
                  AND (t.turn_id IS NULL OR t.rollout_ordinal=(SELECT MAX(x.rollout_ordinal) FROM thread_turns x WHERE x.thread_id=m.id))
                  AND m.attached_thread_parent_id IS NULL
                ORDER BY t.started_at DESC
            ''', (epoch, account['id'], epoch)).fetchall()
        tasks = []
        for row in rows:
            active = row['status'] == 'inProgress' and row['started_at']>=epoch
            questions = []
            activity = '有新消息'
            if row['started_at']>=epoch:
                key = (row['id'], row['turn_id'])
                if key not in self.rollouts:
                    self.rollouts[key] = Rollout(row['rollout_path'], row['start_offset'] or 0)
                rollout = self.rollouts[key]
                rollout.read()
                questions = list(rollout.questions.values())
                if active:
                    activity = rollout.activity
            if active or questions or row['unread']:
                tasks.append({'id': row['id'], 'title': row['title'].splitlines()[0],
                              'activity': '待回答' if questions else activity,
                              'active': active, 'unread': row['unread'], 'questions': questions})
        tasks.sort(key=lambda t: (not bool(t['questions']), not t['active']))
        return {'tasks': tasks, 'running': sum(t['active'] and not t['questions'] for t in tasks),
                'waiting': sum(len(t['questions']) for t in tasks), 'unread': sum(t['unread'] for t in tasks)}
