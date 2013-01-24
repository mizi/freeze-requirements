from __future__ import print_function

import os
import sys
import atexit
import os.path as op
import subprocess
import argparse
import tempfile
import shutil
import functools
import uuid

from setuptools.package_index import distros_for_filename
try:
    from fabric.api import env, run, put
    from fabric.contrib.files import exists
    fabric_present = True
except ImportError:
    fabric_present = False


TEMPFILES_PREFIX = 'freeze-requirements-'
SEPARATOR = '-' * 78


def main():
    # Parse arguments
    parser = argparse.ArgumentParser(description='Download dependencies '
        'from requirements file(s) and upload them to your private pypi '
        'repository')
    parser.add_argument('requirements', nargs='+', 
            help='a pip requirements file, you can specify multiple '
            'requirements files if needed')
    parser.add_argument('--output', '-o', help='put downloaded files here')
    parser.add_argument('--remote-pip', '-r', action='store_true', 
            help='run pip on the destination host')
    parser.add_argument('--upload', '-u', help='upload files here; use '
            'user@host:/remote/dir syntax')
    parser.add_argument('--cache', '-c', help='make pip use this directory '
            'as a cache for downloaded packages')
    options = parser.parse_args()

    # Verify options
    if not options.output and not options.upload:
        print('You must specify either --upload or --output', file=sys.stderr)
        sys.exit(1)
    if options.output and options.remote_pip:
        print("You can't use --output with --remote-pip", file=sys.stderr)
        sys.exit(1)
    if options.output:
        if not op.isdir(options.output):
            print('Output directory does not exist: %s' % options.output, 
                    file=sys.stderr)
            sys.exit(1)
        output_dir = options.output
    else:
        output_dir = tempfile.mkdtemp(prefix=TEMPFILES_PREFIX)
        atexit.register(shutil.rmtree, output_dir)

    if options.upload:
        if not fabric_present:
            print('You need to install fabric to use --upload', 
                    file=sys.stderr)
            sys.exit(1)
        try:
            env.host_string, remote_dir = options.upload.split(':', 1)
        except ValueError:
            print('Invalid upload destination: %s' % options.upload, 
                    file=sys.stderr)
            sys.exit(1)

    original_requirements = options.requirements

    # Alias functions to run pip locally or on the remote host
    if options.remote_pip:
        run_cmd = functools.partial(run, stdout=sys.stderr)
        mkdtemp = remote_mkdtemp
        listdir = remote_listdir
        rmtree = remote_rmtree
        put_package = remote_move
        move = remote_move
        # Upload requirements files to a temp directory
        print(SEPARATOR, file=sys.stderr)
        print('Uploading requirements...', file=sys.stderr)
        temp_dir = remote_mkdtemp(prefix=TEMPFILES_PREFIX)
        atexit.register(run, 'rm -rf %s' % temp_dir, stdout=sys.stderr)
        remote_requirements = []
        for i, requirement in enumerate(options.requirements):
            req_dir = op.join(temp_dir, str(i))
            run('mkdir %s' % req_dir, stdout=sys.stderr)
            remote_requirements.extend(put(requirement, req_dir))
        options.requirements = remote_requirements
        output_dir = op.join(temp_dir, 'packages')
        run('mkdir %s' % output_dir, stdout=sys.stderr)
        print(file=sys.stderr)
    else:
        run_cmd = functools.partial(subprocess.check_call, shell=True,
                stdout=sys.stderr)
        mkdtemp = tempfile.mkdtemp
        listdir = os.listdir
        rmtree = shutil.rmtree
        put_package = put
        move = local_move

    # Download packages
    print(SEPARATOR, file=sys.stderr)
    print('Downloading packages...', file=sys.stderr)
    requirements_packages = []
    for original_requirement, requirement in zip(
            original_requirements, options.requirements):
        temp_dir = mkdtemp(prefix=TEMPFILES_PREFIX)
        atexit.register(rmtree, temp_dir)
        pip_cmd = 'pip install -r %s --download %s' % (requirement, temp_dir)
        if options.cache:
            run_cmd('mkdir -p %s' % options.cache)
            pip_cmd += ' --download-cache %s' % options.cache
        run_cmd(pip_cmd)
        requirements_packages.append((original_requirement, listdir(temp_dir)))
        move(op.join(temp_dir, '*'), output_dir)
    print(file=sys.stderr)

    # Upload or move packages to their final destination
    if options.upload:
        print(SEPARATOR, file=sys.stderr)
        if options.remote_pip:
            print('Moving packages to their final destination...', 
                    file=sys.stderr)
        else:
            print('Uploading packages...', file=sys.stderr)
        packages = [op.join(output_dir, p) for p in listdir(output_dir)]
        created_dirs = set()
        for package in packages:
            distro = list(distros_for_filename(package))[0]
            dst_dir = op.join(remote_dir, distro.key)
            if dst_dir not in created_dirs:
                run('mkdir -p %s' % dst_dir, stdout=sys.stderr)
                created_dirs.add(dst_dir)
            put_package(package, dst_dir)
    print(file=sys.stderr)

    # Print frozen requirements for each input requirements file
    print(SEPARATOR, file=sys.stderr)
    for requirements_file, packages in requirements_packages:
        print('# Frozen requirements for "%s":' % requirements_file)
        print()
        for package in packages:
            distro = list(distros_for_filename(package))[0]
            print('%s==%s' % (distro.key, distro.version))
        print()


def remote_move(src, dst):
    """
    Move a file on a remote host.
    """
    run('mv -fv %s %s' % (src, dst), stdout=sys.stderr)


def local_move(src, dst):
    """
    Move a file on local host.
    """
    subprocess.check_call('mv -fv %s %s' % (src, dst), shell=True,
            stdout=sys.stderr)


def remote_mkdtemp(prefix='', dir='/tmp'):
    """
    Create a remote temporary directory.
    """
    while True:
        temp_dir = op.join(dir, '%s%s' % (prefix, uuid.uuid4().hex))
        if not exists(temp_dir):
            run('mkdir %s' % temp_dir, stdout=sys.stderr)
            break
    return temp_dir


def remote_listdir(location):
    return run('ls %s' % location, stdout=sys.stderr).split()


def remote_rmtree(location):
    run('rm -rf %s' % location, stdout=sys.stderr)
