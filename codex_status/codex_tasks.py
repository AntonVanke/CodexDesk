import json
import re
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
    def __init__(self, path, offset, speed_tiers=None):
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
        self.model = None
        self.effort = None
        self.mode = 'default'
        self.speed = None
        self.speed_tiers = speed_tiers or {}
        self.usage = None

    def consume(self, event):
        payload = event.get('payload', {})
        kind = payload.get('type')
        if event['type'] == 'turn_context':
            self.model = payload.get('model')
            self.effort = payload.get('effort')
            self.mode = (payload.get('collaboration_mode') or {}).get('mode', 'default')
            self.speed = self.speed_tiers.get((self.model,payload.get('service_tier')))
            return
        if event['type'] == 'event_msg':
            if kind == 'token_count' and payload.get('rate_limits'):
                self.usage = (event['timestamp'], payload['rate_limits'])
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
                for part in payload.get('content', []):
                    text = part.get('text', '')
                    if '<proposed_plan>' in text:
                        plan = text.split('<proposed_plan>',1)[1].split('</proposed_plan>',1)[0].strip()
                        title = plan.splitlines()[0].lstrip('# ').strip()
                        self.questions[('plan',0)] = {'id': 'plan:'+str(self.path),
                            'text': title, 'options': [], 'kind': 'plan'}
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
        self.speed_tiers = {}
        catalog = self.home/'models_cache.json'
        if catalog.exists():
            for model in json.loads(catalog.read_text(encoding='utf8'))['models']:
                for tier in model.get('service_tiers', []):
                    speed = re.search(r'(\d+(?:\.\d+)?)x speed',tier.get('description',''))
                    if speed:
                        self.speed_tiers[(model['slug'],tier['id'])] = float(speed[1])

    def snapshot(self, account=None):
        account = account or read_account()
        empty = {'tasks': [], 'running': 0, 'waiting': 0, 'unread': 0}
        if not account or not (self.home/'thread_history_1.sqlite').exists():
            return empty
        servers = [process.info['create_time'] for process in psutil.process_iter(['name','cmdline','create_time'])
            if process.info['name'] == 'codex.exe'
            and 'app-server' in (process.info['cmdline'] or [])]
        epoch = min(servers) if servers else float('inf')
        if epoch != self.epoch:
            self.rollouts.clear()
            self.epoch = epoch
        goals = {}
        if (self.home/'goals_1.sqlite').exists():
            with sqlite3.connect((self.home/'goals_1.sqlite').as_uri()+'?mode=ro', uri=True) as db:
                db.row_factory = sqlite3.Row
                goals = {row['thread_id']: dict(row) for row in db.execute("SELECT thread_id,status FROM thread_goals WHERE status!='complete'")}
        with sqlite3.connect((self.home / 'thread_history_1.sqlite').as_uri() + '?mode=ro', uri=True) as db:
            db.row_factory = sqlite3.Row
            db.execute('ATTACH DATABASE ? AS meta', ((self.home / 'state_5.sqlite').as_uri() + '?mode=ro',))
            rows = db.execute('''
                SELECT m.id, COALESCE(NULLIF(m.name,''), NULLIF(m.title,''),'新任务') AS title,
                       m.rollout_path, t.turn_id, t.status, COALESCE(t.started_at,0) AS started_at,
                       t.rollout_byte_offset AS start_offset, r.first_unread_turn IS NOT NULL AS unread,
                       m.model, m.reasoning_effort
                FROM meta.threads m LEFT JOIN thread_turns t ON t.thread_id=m.id
                LEFT JOIN meta.thread_read_receipts r ON r.thread_id=m.id
                WHERE m.archived=0 AND (t.started_at>=? OR r.first_unread_turn IS NOT NULL
                    OR m.id IN (SELECT value FROM json_each(?)))
                  AND (m.creator_account_id=? OR (m.creator_account_id IS NULL AND t.started_at>=? AND t.status='inProgress'))
                  AND (t.turn_id IS NULL OR t.rollout_ordinal=(SELECT MAX(x.rollout_ordinal) FROM thread_turns x WHERE x.thread_id=m.id))
                  AND m.attached_thread_parent_id IS NULL
                ORDER BY t.started_at DESC
            ''', (epoch, json.dumps(list(goals)), account['id'], epoch)).fetchall()
        tasks = []
        for row in rows:
            goal = goals.get(row['id'])
            active = row['status'] == 'inProgress' and row['started_at']>=epoch or bool(goal and goal['status']=='active' and servers)
            questions = []
            activity = '有新消息'
            rollout = None
            if row['turn_id']:
                key = (row['id'], row['turn_id'])
                if key not in self.rollouts:
                    self.rollouts[key] = Rollout(row['rollout_path'], row['start_offset'] or 0, self.speed_tiers)
                rollout = self.rollouts[key]
                rollout.read()
                questions = list(rollout.questions.values())
                if active:
                    activity = rollout.activity
            if active or questions or row['unread'] or goal:
                mode = 'goal' if goal and goal['status'] != 'complete' else rollout.mode if rollout else 'default'
                if goal and not active:
                    activity = {'paused': '目标暂停', 'blocked': '目标阻塞', 'budget_limited': '额度已用尽',
                                'usage_limited': '用量限制', 'active': '目标待继续'}.get(goal['status'], activity)
                tasks.append({'id': row['id'], 'title': row['title'].splitlines()[0],
                              'activity': ('待确认计划' if questions[0].get('kind')=='plan' else '待回答') if questions else activity,
                              'active': active, 'unread': row['unread'], 'questions': questions,
                              'completed_unread': row['status']=='completed' and row['unread'] and not questions and not goal,
                              'mode': mode, 'goal_status': goal['status'] if goal else None,
                              'model': (rollout.model if rollout else None) or row['model'],
                              'effort': (rollout.effort if rollout else None) or row['reasoning_effort'],
                              'speed': rollout.speed if rollout else None})
        tasks.sort(key=lambda t: (not bool(t['questions']), not t['active']))
        return {'tasks': tasks, 'running': sum(t['active'] and not t['questions'] for t in tasks),
                'waiting': sum(len(t['questions']) for t in tasks), 'unread': sum(t['unread'] for t in tasks)}

    def latest_usage(self):
        return max((r.usage for r in self.rollouts.values() if r.usage), key=lambda u:u[0], default=None)
