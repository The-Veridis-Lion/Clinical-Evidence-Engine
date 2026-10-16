"""Start the two ordinary local products with separate imports and databases.

Launching performs local checks only. Luna is called only by an explicit Extract
operation. Ctrl+C stops only the child processes created by this launcher.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
APPS = {'copilot': 'clinical-evidence-copilot', 'careflow': 'careflow-readiness'}


def environment(app, data, provider='codex_cli'):
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join((str(ROOT / APPS[app] / 'src'),
                                      str(ROOT / 'packages/evidence-verifier/src')))
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    env['CLINICAL_LUNA_SLOTS'] = str(data / 'luna-slots.sqlite3')
    env['CLINICAL_PRODUCT_PROVIDER'] = provider
    return env


def local_check(app, env, live):
    code = f'import clinical_intelligence.{app}.cli'
    if live:
        code += ('; from clinical_intelligence.clinical_notes.runner import product_provider'
                 '; p=product_provider(); p.preflight()')
        if env['CLINICAL_PRODUCT_PROVIDER'] == 'codex_cli':
            code += ('; import subprocess'
                     '; r=subprocess.run([p.executable,"login","status"],capture_output=True,timeout=15)'
                     '; assert r.returncode==0,"Run codex login before starting live extraction"')
    result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env,
                            capture_output=True, text=True, encoding='utf-8', timeout=45)
    if result.returncode:
        raise RuntimeError(f'{app}: local startup check failed.\n{result.stderr[-4000:]}')


def available(port):
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', port))
        except OSError as exc:
            raise RuntimeError(f'Port {port} is unavailable; an existing service was not stopped.') from exc


def health(process, url):
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError(f'Product exited during startup ({process.returncode}); see its log.')
        try:
            with urlopen(url, timeout=1) as response:
                return json.load(response)
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f'Timed out waiting for {url}; see the product log.')


def main(argv=None):
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--offline', action='store_true', help='Browse saved cases without enabling model calls')
    saved = parser.add_mutually_exclusive_group()
    saved.add_argument('--saved-case', action='store_true',
                       help='Open the eight-file synthetic patient using its actual saved Luna responses; no new extraction')
    parser.add_argument('--check', action='store_true', help='Local dependency/authentication checks; no server or model call')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--provider', choices=('codex_cli', 'openai_api'), default='codex_cli',
                        help='Server-side model transport for explicit live operations')
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--copilot-port', type=int, default=8857)
    parser.add_argument('--careflow-port', type=int, default=8858)
    args = parser.parse_args(argv)
    if args.saved_case:
        args.offline = True
    workspace_name = 'showcase-saved' if args.saved_case else 'workspace'
    data = (args.data_dir or ROOT / 'artifacts/recovery-demo' / workspace_name).resolve()
    # A normal workspace must never write into immutable evaluation evidence.
    if data == ROOT or data.is_relative_to(ROOT / 'docs') or data.is_relative_to(ROOT / '.git'):
        parser.error('Use a dedicated working data directory, outside docs and .git.')
    envs = {app: environment(app, data, args.provider) for app in APPS}
    for app, env in envs.items():
        local_check(app, env, not args.offline)
    if args.check:
        print(json.dumps({'local_checks': 'passed', 'live': not args.offline, 'provider': args.provider, 'model_calls': 0,
                          'python': sys.executable, 'data_dir': str(data)}, ensure_ascii=False))
        return 0
    if args.saved_case:
        from restore_workbench_demo import restore_demo
        restored = restore_demo(data, evidence=ROOT / 'docs/showcase-case-20261016/evidence')
        print('Actual saved Luna extraction from synthetic source files: ' +
              ('reusing saved revisions.' if restored['reused'] else 'restored original responses and source links.'), flush=True)
        print('This launch replays the saved results. Start without --saved-case to extract new files with Luna.', flush=True)
    if args.copilot_port == args.careflow_port:
        parser.error('Products need different ports.')
    for port in (args.copilot_port, args.careflow_port):
        available(port)
    data.mkdir(parents=True, exist_ok=True)
    urls = {'copilot': f'http://127.0.0.1:{args.copilot_port}/',
            'careflow': f'http://127.0.0.1:{args.careflow_port}/'}
    envs['careflow']['CLINICAL_WORKBENCH_URL'] = urls['copilot'] + 'workbench/'
    started = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    children, handles, records = [], [], []
    try:
        for app, port in (('copilot', args.copilot_port), ('careflow', args.careflow_port)):
            app_data = data / app
            app_data.mkdir(exist_ok=True)
            command = [sys.executable, '-m', f'clinical_intelligence.{app}',
                       '--db', str(app_data / 'cases.sqlite3'), 'serve', '--port', str(port)]
            if app == 'copilot':
                command += ['--careflow-url', urls['careflow'].rstrip('/')]
            else:
                command += ['--shared-copilot-db', str(data / 'copilot' / 'cases.sqlite3')]
            if not args.offline:
                command += ['--live' if app == 'copilot' else '--enable-live-extraction']
            log = app_data / f'server-{started}.log'
            handle = log.open('xb')
            handles.append(handle)
            process = subprocess.Popen(command, cwd=ROOT, env=envs[app], stdout=handle,
                                       stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            children.append(process)
            state = health(process, urls[app] + ('api/config' if app == 'copilot' else 'health'))
            records.append({'app': app, 'pid': process.pid, 'url': urls[app], 'command': command,
                            'log': str(log), 'ready': bool(state)})
        receipt = {'started_at': started, 'launcher_pid': os.getpid(), 'live': not args.offline,
                   'runtime_model': 'gpt-6-luna', 'provider': args.provider, 'data_dir': str(data), 'services': records}
        (data / 'running.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        print('Patient workbench: ' + urls['copilot'] + 'workbench/', flush=True)
        print('Both products are ready. ' + ('Saved evidence only; model calls are disabled.' if args.offline else
              'Extraction and explicitly requested question interpretation/prose organization use Luna.'), flush=True)
        if not args.no_browser:
            webbrowser.open(urls['copilot'] + 'workbench/')
        for app, url in urls.items():
            print(f'{app}: {url}', flush=True)
        print('Keep this process open. Ctrl+C stops these two services. Data is retained.', flush=True)
        while all(process.poll() is None for process in children):
            time.sleep(0.5)
        raise RuntimeError('A product stopped. See the server logs; no automatic model retry was performed.')
    except KeyboardInterrupt:
        return 0
    finally:
        for process in children:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        for handle in handles:
            handle.close()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
