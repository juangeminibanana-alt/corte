"""Explicit Google deployment actions; never run automatically by tests or Terraform.

Run from any directory with Python 3.10+, Terraform and gcloud on PATH.
Every action uses the project from this module's Terraform state explicitly.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def run(arguments: list[str], *, data: bytes | None = None, cwd: Path = ROOT) -> str:
    executable = shutil.which(arguments[0])
    if not executable:
        raise RuntimeError(arguments[0] + ' is not installed or is not on PATH.')
    # Secret material is passed only on stdin, never in arguments or output.
    result = subprocess.run([executable, *arguments[1:]], cwd=cwd, input=data,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise RuntimeError(arguments[0] + ' failed. Review the authenticated account, permissions and project configuration.')
    return result.stdout.decode('utf-8', errors='replace').strip()


def deployment() -> dict:
    return json.loads(run(['terraform', 'output', '-json', 'deployment'], cwd=HERE))


def main() -> int:
    parser = argparse.ArgumentParser(description='Reviewed Google-only deployment actions for Corte.')
    parser.add_argument('action', choices=['secrets', 'build', 'restart', 'status'])
    parser.add_argument('--tag', help='Immutable build label, usually the reviewed Git commit SHA.')
    args = parser.parse_args()
    try:
        config = deployment()
        project = ['--project', config['project_id']]
        if args.action == 'secrets':
            for name in (config['session_secret_id'], config['encryption_secret_id']):
                existing = run(['gcloud', 'secrets', 'versions', 'list', name, *project, '--limit', '1', '--format=value(name)'])
                if existing:
                    print(name + ': already initialized; keeping its existing key.')
                    continue
                value = secrets.token_urlsafe(48).encode('ascii')
                run(['gcloud', 'secrets', 'versions', 'add', name, *project, '--data-file=-', '--quiet'], data=value)
                print(name + ': created privately in Secret Manager; value was not printed.')
        elif args.action == 'build':
            if not args.tag or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', args.tag):
                raise ValueError('Pass --tag with the reviewed commit SHA or a unique build label.')
            image = config['image_repository'] + ':' + args.tag
            print('Building the reviewed source in Google Cloud Build. This action can incur costs.', flush=True)
            result = json.loads(run(['gcloud', 'builds', 'submit', str(ROOT), *project,
                                     '--config', str(HERE / 'cloudbuild.yaml'),
                                     '--service-account', config['build_service_account'],
                                     '--gcs-source-staging-dir', 'gs://' + config['build_source_bucket'] + '/source',
                                     '--substitutions', '_IMAGE_URI=' + image, '--format=json', '--suppress-logs', '--quiet']))
            digest = result['results']['images'][0]['digest']
            if not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
                raise RuntimeError('Cloud Build did not return a verified image digest.')
            print('container_image = ' + json.dumps(config['image_repository'] + '@' + digest))
            print('Review this digest in deployment.tfvars before enabling runtime or updating the VM.')
        elif args.action == 'restart':
            if not config['runtime_enabled'] or not config['instance_name']:
                raise ValueError('The runtime has not been created.')
            vm = config['instance_name']
            location = ['--zone', config['zone']]
            print('Stopping Corte cleanly, then starting with reviewed metadata. A brief outage is expected.', flush=True)
            run(['gcloud', 'compute', 'instances', 'stop', vm, *project, *location, '--quiet'])
            run(['gcloud', 'compute', 'instances', 'start', vm, *project, *location, '--quiet'])
            print('VM start accepted. Check gateway, Hosting and login before claiming deployment success.')
        elif args.action == 'status':
            if not config['runtime_enabled']:
                print('Foundation only; no runtime or live URL has been created.')
                return 0
            print(run(['gcloud', 'compute', 'instances', 'describe', config['instance_name'], *project,
                       '--zone', config['zone'], '--format=value(status)']))
            print(run(['gcloud', 'run', 'services', 'describe', config['gateway_service'], *project,
                       '--region', config['region'], '--format=value(status.url)']))
            print('Hosting target: ' + config['hosting_site_id'])
            print('Expected URL (verify separately): ' + config['expected_url'])
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
