#!/usr/bin/env python3
"""Hermes Ops control-plane helpers.

Thin wrappers around native Hermes Kanban/MCP/Profile commands. No secrets are
printed; use this from cron/no-agent tasks and manual server ops.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

BOARDS_DIR = Path('/root/.hermes/kanban/boards')
PROFILES_DIR = Path('/root/.hermes/profiles')
DEFAULT_BOARDS = [
    'company-runtime',
    'it-devops',
    'engineering',
    'product',
    'smm-department',
    'marketing',
    'research',
    'support',
    'security',
    'finance',
    'qa-review',
    'system-changes',
    'projects-ideas',
    'sync-system',
]
ROOT_CONFIG = Path('/root/.hermes/config.yaml')


def hermes_cmd() -> str:
    """Return a Hermes CLI path that works from launchd/cron's minimal PATH."""
    candidates = [
        os.environ.get('HERMES_BIN'),
        shutil.which('hermes'),
        '/root/.local/bin/hermes',
        '/root/.hermes/hermes-agent/venv/bin/hermes',
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return 'hermes'


def hermes_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault('HERMES_ACCEPT_HOOKS', '1')
    env['LC_ALL'] = 'C'
    env['LANG'] = 'C'
    env['PATH'] = ':'.join([
        '/root/.local/bin',
        '/root/.hermes/hermes-agent/venv/bin',
        '/opt/homebrew/bin',
        '/opt/homebrew/sbin',
        '/usr/local/bin',
        '/usr/bin',
        '/bin',
        '/usr/sbin',
        '/sbin',
        env.get('PATH', ''),
    ])
    return env

THREAD_ROUTE = {
    '4': ('company-runtime', 'orchestrator'),
    '6': ('company-runtime', 'orchestrator'),
    '8': ('it-devops', 'itops'),
    '10': ('product', 'product'),
    '12': ('smm-department', 'smm'),
    '14': ('support', 'support'),
    '16': ('research', 'research'),
    '18': ('it-devops', 'itops'),
    '25': ('engineering', 'backend'),
}

ASSIGNEE_BOARD = {
    'orchestrator': 'company-runtime',
    'dispatcher': 'company-runtime',
    'curator': 'company-runtime',
    'itops': 'it-devops',
    'devops': 'it-devops',
    'backend': 'engineering',
    'frontend': 'engineering',
    'qa': 'qa-review',
    'reviewer': 'qa-review',
    'product': 'product',
    'analyst': 'product',
    'smm': 'smm-department',
    'content': 'smm-department',
    'marketing': 'marketing',
    'research': 'research',
    'researcher-public': 'research',
    'support': 'support',
    'security': 'security',
    'finance': 'finance',
    'ux': 'product',
}

BOARD_DEFAULT_ASSIGNEE = {
    'company-runtime': 'orchestrator',
    'it-devops': 'itops',
    'engineering': 'backend',
    'product': 'product',
    'smm-department': 'smm',
    'marketing': 'marketing',
    'research': 'research',
    'support': 'support',
    'security': 'security',
    'finance': 'finance',
    'qa-review': 'reviewer',
}

KEYWORD_ROUTE = [
    ('security', 'security', ['security', 'secops', 'security audit', 'risk gate', 'approval', 'approve', 'token', 'secret', 'auth', 'oauth', 'доступ', 'секрет', 'инфобез', 'секьюрити', 'апрув', 'риск']),
    ('finance', 'finance', ['finance', 'payment', 'invoice', 'budget', 'accounting', 'billing', 'финанс', 'счет', 'оплата', 'бюджет', 'бухгалтер']),
    ('it-devops', 'itops', ['server', 'docker', 'systemd', 'cron', 'mcp', 'n8n', 'deploy', 'infra', 'gateway', 'monitor', 'сервер', 'крон', 'инфра', 'деплой']),
    ('engineering', 'backend', ['backend', 'frontend', 'api', 'code', 'repo', 'github', 'bug', 'test', 'qa', 'integration', 'бэкенд', 'фронт', 'код', 'репоз', 'тест', 'интеграц']),
    ('product', 'product', ['product', 'prd', 'roadmap', 'feature', 'requirements', 'ux', 'целевая', 'продукт', 'роадмап', 'фича', 'требован', 'ценност']),
    ('smm-department', 'smm', ['smm', 'content', 'telegram channel', 'post', 'copy', 'youtube', 'shorts', 'контент', 'пост', 'канал', 'смм', 'рилс']),
    ('marketing', 'marketing', ['marketing', 'funnel', 'lead', 'offer', 'positioning', 'growth', 'маркетинг', 'воронк', 'лид', 'оффер', 'позиционир']),
    ('research', 'research', ['research', 'source', 'compare', 'benchmark', 'intelligence', 'reddit', 'twitter', 'x.com', 'instagram', 'threads', 'ресерч', 'исслед', 'источник', 'сравни']),
    ('support', 'support', ['support', 'ticket', 'helpdesk', 'customer', 'rutoll', 'саппорт', 'поддержк', 'тикет', 'клиент']),
    ('qa-review', 'reviewer', ['review', 'verify', 'proof', 'acceptance', 'checklist', 'провер', 'ревью', 'доказатель', 'приемк']),
]


def run(cmd: list[str], timeout: int = 180) -> subprocess.CompletedProcess[str]:
    env = hermes_env()
    if cmd and cmd[0] == 'hermes':
        cmd = [hermes_cmd(), *cmd[1:]]
    if cmd and cmd[0] == 'systemctl' and not shutil.which('systemctl'):
        return subprocess.CompletedProcess(cmd, 127, '', 'systemctl not available on this host')
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, env=env)


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def redact(text: str) -> str:
    text = re.sub(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', '<email>', text or '')
    text = re.sub(r'(?i)(api[_-]?key|token|secret|password|authorization|bearer)\s*[:=]\s*\S+', r'\1=<redacted>', text)
    return text[-4000:]


def extract_thread_id(*parts: str) -> str:
    text = '\n'.join([p for p in parts if p])
    patterns = [
        r'(?:message_thread_id|thread_id|topic_id)\s*[=:]\s*[\'"]?(\d{1,8})',
        r'telegram:[-0-9]+:(\d{1,8})',
    ]
    for pattern in patterns:
        m = re.search(pattern, text, flags=re.I)
        if m:
            return m.group(1)
    return ''


def route_task(title: str, body: str, source: str, board: str, assignee: str, thread_id: str = '') -> tuple[str, str, dict[str, Any]]:
    thread_id = thread_id or extract_thread_id(title, body, source)
    explicit_board = board and board not in {'auto', 'department-auto'}
    explicit_assignee = bool(assignee)
    reason = []
    if explicit_board:
        routed_board = board
        routed_assignee = assignee or BOARD_DEFAULT_ASSIGNEE.get(board, '')
        reason.append('explicit_board')
        return routed_board, routed_assignee, {'reason': reason, 'thread_id': thread_id}

    if explicit_assignee and assignee in ASSIGNEE_BOARD:
        routed_board = ASSIGNEE_BOARD[assignee]
        reason.append('assignee_board')
        return routed_board, assignee, {'reason': reason, 'thread_id': thread_id}

    if thread_id in THREAD_ROUTE and thread_id != '2':
        routed_board, default_assignee = THREAD_ROUTE[thread_id]
        reason.append('thread_route')
        return routed_board, assignee or default_assignee, {'reason': reason, 'thread_id': thread_id}

    haystack = f'{title}\n{body}\n{source}'.lower()
    for routed_board, default_assignee, needles in KEYWORD_ROUTE:
        if any(n.lower() in haystack for n in needles):
            reason.append('keyword_route')
            return routed_board, assignee or default_assignee, {'reason': reason, 'thread_id': thread_id}

    reason.append('fallback_company_runtime')
    return 'company-runtime', assignee or 'orchestrator', {'reason': reason, 'thread_id': thread_id}


def append_runtime_contract(body: str, routing: dict[str, Any]) -> str:
    contract = (
        '\n\nRuntime routing/proof contract:\n'
        '- User-facing summaries and final answers must be in Russian.\n'
        '- Inbox/topic 2 is intake only; Kanban lifecycle and final summaries go to topic 4.\n'
        '- Human blockers/rework go to topic 6; system failures go to topic 18.\n'
        '- Close Kanban only with --result, --summary and --metadata including artifact_path, proof_type, verified_by, verdict, next_owner.\n'
        '- If proof or required access is missing, block the task with a concrete Russian reason instead of claiming done.\n'
        f'- Routed board: {routing.get("board")}; routed assignee: {routing.get("assignee")}; route reason: {",".join(routing.get("reason") or [])}.\n'
    )
    return (body or '').rstrip() + contract


def board_db(board: str) -> Path:
    return BOARDS_DIR / board / 'kanban.db'


def list_boards() -> list[str]:
    found = [p.name for p in sorted(BOARDS_DIR.iterdir()) if (p / 'kanban.db').exists()] if BOARDS_DIR.exists() else []
    return found or DEFAULT_BOARDS


def query_board(board: str) -> dict[str, Any]:
    db = board_db(board)
    out: dict[str, Any] = {'board': board, 'exists': db.exists()}
    if not db.exists():
        return out
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    try:
        out['counts'] = {r['status']: r['n'] for r in con.execute('select status, count(*) n from tasks group by status')}
        out['assignees'] = {str(r['assignee'] or 'unassigned'): r['n'] for r in con.execute('select assignee, count(*) n from tasks group by assignee')}
        now = int(time.time())
        blocked = [dict(r) for r in con.execute('select id,title,assignee,status,priority,consecutive_failures,created_at from tasks where status in ("blocked","scheduled") order by priority desc, created_at limit 20')]
        running_stale = [dict(r) for r in con.execute('select id,title,assignee,status,claim_expires,started_at from tasks where status="running" and (claim_expires is null or claim_expires < ?) order by started_at limit 20', (now,))]
        ready_old = [dict(r) for r in con.execute('select id,title,assignee,status,priority,created_at from tasks where status in ("triage","todo","ready") order by created_at limit 20')]
        out['blocked_or_scheduled'] = blocked
        out['stale_running'] = running_stale
        out['old_waiting'] = ready_old
    finally:
        con.close()
    return out


def system_state(service: str) -> tuple[str, str]:
    active = run(['systemctl', 'is-active', service], timeout=30)
    enabled = run(['systemctl', 'is-enabled', service], timeout=30)
    return (active.stdout.strip() or active.stderr.strip(), enabled.stdout.strip() or enabled.stderr.strip())


def cmd_audit(args: argparse.Namespace) -> int:
    boards = args.boards or list_boards()
    profiles = sorted([p.name for p in PROFILES_DIR.iterdir() if p.is_dir()]) if PROFILES_DIR.exists() else []
    board_reports = [query_board(b) for b in boards]
    expected_dispatch_owner = 'orchestrator'
    expected_active_gateways = {'orchestrator', 'support', 'smm'}
    root_dispatch = None
    profile_dispatch_true: list[str] = []
    gateway_services: dict[str, dict[str, str]] = {}
    try:
        import yaml
        root = yaml.safe_load(ROOT_CONFIG.read_text()) or {}
        root_dispatch = bool((root.get('kanban') or {}).get('dispatch_in_gateway'))
        root_active, root_enabled = system_state('hermes-gateway.service')
        gateway_services['default'] = {'service': 'hermes-gateway.service', 'active': root_active, 'enabled': root_enabled}
        for name in profiles:
            cfgp = PROFILES_DIR / name / 'config.yaml'
            if cfgp.exists():
                cfg = yaml.safe_load(cfgp.read_text()) or {}
                if bool((cfg.get('kanban') or {}).get('dispatch_in_gateway')):
                    profile_dispatch_true.append(name)
            active, enabled = system_state(f'hermes-gateway-{name}.service')
            gateway_services[name] = {'service': f'hermes-gateway-{name}.service', 'active': active, 'enabled': enabled}
    except Exception as exc:
        profile_dispatch_true.append('audit_error:' + type(exc).__name__)
    findings = []
    expected_dispatch = [expected_dispatch_owner]
    if root_dispatch:
        findings.append('root_gateway_dispatch_enabled_unexpected')
    if profile_dispatch_true != expected_dispatch:
        findings.append('dispatch_owner_mismatch:expected=' + ','.join(expected_dispatch) + ';actual=' + ','.join(profile_dispatch_true))
    active_profiles = {name for name, row in gateway_services.items() if row.get('active') == 'active' and name != 'default'}
    enabled_profiles = {name for name, row in gateway_services.items() if row.get('enabled') == 'enabled' and name != 'default'}
    if active_profiles != expected_active_gateways:
        findings.append('active_gateway_mismatch:expected=' + ','.join(sorted(expected_active_gateways)) + ';actual=' + ','.join(sorted(active_profiles)))
    if enabled_profiles != expected_active_gateways:
        findings.append('enabled_gateway_mismatch:expected=' + ','.join(sorted(expected_active_gateways)) + ';actual=' + ','.join(sorted(enabled_profiles)))
    if gateway_services.get('default', {}).get('active') == 'active':
        findings.append('default_gateway_active_unexpected')
    for br in board_reports:
        counts = br.get('counts') or {}
        if counts.get('blocked'):
            findings.append(f"{br['board']}:blocked={counts.get('blocked')}")
        if br.get('stale_running'):
            findings.append(f"{br['board']}:stale_running={len(br.get('stale_running') or [])}")
    # Blocked cards are operational warnings unless the caller wants strict mode.
    hard_findings = [f for f in findings if ':blocked=' not in f]
    payload = {
        'ok': not hard_findings,
        'kind': 'orchestration-audit',
        'policy': {
            'dispatch_owner': expected_dispatch_owner,
            'active_gateways': sorted(expected_active_gateways),
            'default_gateway_expected': 'inactive_disabled',
        },
        'profiles': profiles,
        'boards': board_reports,
        'root_dispatch_in_gateway': root_dispatch,
        'profile_dispatch_enabled': profile_dispatch_true,
        'gateway_services': gateway_services,
        'findings': findings,
        'hard_findings': hard_findings,
    }
    emit(payload)
    return 0 if not hard_findings or args.warn_only else 2

def cmd_mcp_health(_args: argparse.Namespace) -> int:
    proc = run(['hermes', 'mcp', 'list'], timeout=60)
    list_text = redact(proc.stdout + proc.stderr)
    servers = []
    enabled_expected = [
        'n8n',
        'hermes-local-memory',
        'sequential-thinking',
        'web-fetch',
        'time',
        'filesystem-hermes',
        'git-hermes',
        'context7',
    ]
    for name in enabled_expected:
        test = run(['hermes', 'mcp', 'test', name], timeout=120)
        servers.append({'name': name, 'rc': test.returncode, 'tail': redact(test.stdout + test.stderr)[-1200:]})
    ok = proc.returncode == 0 and all(s['rc'] == 0 for s in servers)
    emit({'ok': ok, 'kind': 'mcp-health', 'list_rc': proc.returncode, 'servers': servers, 'list_tail': list_text[-2400:]})
    return 0 if ok else 2


def cmd_profile_health(_args: argparse.Namespace) -> int:
    expected = {'orchestrator','dispatcher','itops','devops','product','smm','support','backend','frontend','qa','reviewer','security','research','researcher-public','analyst','marketing','content','ux','curator'}
    found = {p.name for p in PROFILES_DIR.iterdir() if p.is_dir()} if PROFILES_DIR.exists() else set()
    missing = sorted(expected - found)
    profile_reports = []
    for name in sorted(found):
        path = PROFILES_DIR / name
        cfg = path / 'config.yaml'
        skill_count = 0
        skills_dir = path / 'skills'
        if skills_dir.exists():
            for _root, _dirs, files in os.walk(skills_dir):
                if 'SKILL.md' in files:
                    skill_count += 1
        profile_reports.append({
            'name': name,
            'config': cfg.exists(),
            'alias': (Path('/root/.local/bin') / name).exists(),
            'skills': skill_count,
        })
    ok = not missing and all(r['config'] for r in profile_reports if r['name'] in expected)
    emit({'ok': ok, 'kind': 'profile-health', 'profile_count': len(found), 'missing': missing, 'profiles': profile_reports})
    return 0 if ok else 2


def cmd_intake(args: argparse.Namespace) -> int:
    board, assignee, route_meta = route_task(
        args.title,
        args.body or '',
        args.source or '',
        args.board or 'auto',
        args.assignee or '',
        args.thread_id or '',
    )
    route_meta.update({'board': board, 'assignee': assignee})
    body = args.body or ''
    if args.source:
        body = (body + '\n\nSource: ' + args.source).strip()
    body = append_runtime_contract(body, route_meta)
    idem = args.idempotency_key or hashlib.sha256(f'{board}\0{args.title}\0{body}'.encode('utf-8', 'ignore')).hexdigest()[:24]
    cmd = ['hermes', 'kanban', '--board', board, 'create', args.title, '--body', body, '--priority', str(args.priority), '--created-by', args.created_by, '--idempotency-key', idem, '--json']
    if assignee:
        cmd += ['--assignee', assignee]
    if args.triage:
        cmd += ['--triage']
    if args.goal:
        cmd += ['--goal', '--goal-max-turns', str(args.goal_max_turns)]
    proc = run(cmd, timeout=120)
    payload: dict[str, Any] = {'kind': 'intake-task', 'ok': proc.returncode == 0, 'board': board, 'assignee': assignee, 'route': route_meta, 'rc': proc.returncode, 'stdout': redact(proc.stdout), 'stderr': redact(proc.stderr), 'idempotency_key': idem}
    emit(payload)
    if proc.returncode == 0 and args.decompose:
        # Decompose only this task when JSON output exposes an id; otherwise leave it to gateway auto_decompose.
        try:
            data = json.loads(proc.stdout)
            task_id = data.get('id') or data.get('task', {}).get('id')
        except Exception:
            task_id = None
        if task_id:
            dec = run(['hermes', 'kanban', '--board', board, 'decompose', task_id, '--json'], timeout=300)
            emit({'kind': 'intake-decompose', 'ok': dec.returncode == 0, 'board': board, 'task_id': task_id, 'rc': dec.returncode, 'stdout': redact(dec.stdout), 'stderr': redact(dec.stderr)})
            return dec.returncode
    return proc.returncode


def cmd_blocker_audit(args: argparse.Namespace) -> int:
    boards = args.boards or list_boards()
    reports = [query_board(b) for b in boards]
    actionable = []
    for br in reports:
        for row in br.get('blocked_or_scheduled') or []:
            actionable.append({'board': br['board'], **row})
        for row in br.get('stale_running') or []:
            actionable.append({'board': br['board'], **row, 'audit': 'stale_running'})
    emit({'ok': True, 'kind': 'blocker-audit', 'actionable_count': len(actionable), 'items': actionable[:50], 'boards': reports})
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='cmd', required=True)
    audit = sub.add_parser('orchestration-audit')
    audit.add_argument('--boards', nargs='*')
    audit.add_argument('--warn-only', action='store_true')
    audit.set_defaults(func=cmd_audit)
    sub.add_parser('mcp-health').set_defaults(func=cmd_mcp_health)
    sub.add_parser('profile-health').set_defaults(func=cmd_profile_health)
    blocker = sub.add_parser('blocker-audit')
    blocker.add_argument('--boards', nargs='*')
    blocker.set_defaults(func=cmd_blocker_audit)
    intake = sub.add_parser('intake')
    intake.add_argument('title')
    intake.add_argument('--body', default='')
    intake.add_argument('--board', default='auto')
    intake.add_argument('--assignee', default='')
    intake.add_argument('--thread-id', default='')
    intake.add_argument('--priority', type=int, default=0)
    intake.add_argument('--source', default='')
    intake.add_argument('--created-by', default='hermes-ops-intake')
    intake.add_argument('--idempotency-key', default='')
    intake.add_argument('--triage', action='store_true', default=True)
    intake.add_argument('--no-triage', action='store_false', dest='triage')
    intake.add_argument('--goal', action='store_true')
    intake.add_argument('--goal-max-turns', type=int, default=20)
    intake.add_argument('--decompose', action='store_true')
    intake.set_defaults(func=cmd_intake)
    return p


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args) or 0)


if __name__ == '__main__':
    raise SystemExit(main())
