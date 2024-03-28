#!/usr/bin/env python3

"""
Simple Patch Manager main program
"""

import sys
import argparse
import re
import os
import subprocess
from collections import namedtuple
from os import path

DEFAULT_BRANCH = "patched"
PATCH_DEF_FILE = "patches.list"

def printerr(*args, **kwargs):
    kwargs['file'] = sys.stderr
    print(*args, **kwargs)

def main():
    parser = argparse.ArgumentParser(description='Simple patch manager')

    parser.add_argument("-b", "--branchname", default=DEFAULT_BRANCH,
        help="Specify the branch name for the resulting patch "
            f"(default: {DEFAULT_BRANCH})")
    parser.add_argument("-c", "--checkpatches", action="store_true",
        help="Only check if the patch files and descriptions are valid.")
    parser.add_argument('patchdir', type=str,
        help='Folder containing the patch files.')
    parser.add_argument('repo', type=str,
        help='The git repository to be patched.', nargs="?")

    args = parser.parse_args()
    patchdir = path.realpath(args.patchdir)

    patches = get_patches(patchdir)
    if patches is None:
        return 1
    _, patchlist = patches

    patchinfos = get_patch_infos(patchdir, patchlist)
    if patchinfos is None:
        printerr("No patches found")
        return 1

    if args.checkpatches:
        print("All patches appears to be in correct format")
        return 0

    if args.repo is None:
        printerr("Please specify repository to be patched!")
        return 1

    try:
        apply_patches(args.repo, patchdir, patches, patchinfos, args.branchname)
    except OSError as ex:
        printerr(f"Error opening repository: {ex.strerror}")
        return 1
    except (RuntimeError, ValueError) as ex:
        printerr(str(ex))
        return 1

    print("All patches applied cleanly!")
    return 0

def get_patches(patchdir):
    """
    Returns:
        a tuple of:
        - {"base-commit": (base commit hash), "final-commit": (target commit hash)}
        - list of patch files relative to patchdir
    """
    re_info_matcher = re.compile(r"([a-z\-]+):\s*([\w\-\.]+)")

    settings = {k:None for k in ["base-commit", "final-commit"]}
    patches = []
    patch_set = set()
    available_settings_count = 0

    try:
        with open(path.join(patchdir, PATCH_DEF_FILE), "r", encoding='utf8') as f:
            for l in f:
                l = l.strip()

                # skip comments and empty lines
                if not l:
                    continue
                if l.startswith("#"):
                    continue

                # match with settings
                m = re_info_matcher.match(l)
                if m:
                    settingkey = m.group(1)
                    if settingkey not in settings:
                        raise ValueError(f"Unknown setting: {settingkey}")
                    if settings.get(settingkey) is not None:
                        raise ValueError(f"Duplicate setting for {settingkey}")
                    settings[settingkey] = m.group(2)
                    available_settings_count += 1
                    continue

                # must be a file name for the patch
                # ensure we already have ALL the settings
                if available_settings_count != len(settings):
                    unavail_keys = [k for k, v in settings.items() if v is None]
                    raise ValueError(
                        f"Please fill these settings: {', '.join(unavail_keys)}")

                # let's match the rule
                # rule 1: must be relative location
                dirpath, filename = path.split(l)
                if dirpath.startswith('/'):
                    raise ValueError("Patch file location must be relative")

                # rule 2: filename must end with '.patch'
                if not filename.endswith('.patch'):
                    raise ValueError("Patches must end with '.patch'")

                # rule 3:
                #  - all path components must not be '.' or '..', or starts with '.'
                if not all(not comp.startswith('.') for comp in l.split('/')):
                    raise ValueError(
                        "All path components must not contain leading dots")

                # ensure no duplicates
                if l in patch_set:
                    raise ValueError(f"Duplicate instances of patch '{l}'!")
                patch_set.add(l)

                # all good
                patches.append(l)

        return settings, patches

    except OSError as ex:
        printerr(f"Cannot open '{PATCH_DEF_FILE}' file: {ex.strerror}")
        return None
    except ValueError as ex:
        printerr(f"Error in '{PATCH_DEF_FILE}' file: {str(ex)}")
        return None

PatchInfo = namedtuple('PatchInfo', ['name', 'email', 'subject', 'date'])

def get_patch_infos(patchdir, patchlist):
    """
    Returns:
        A list of PatchInfo. The list is in the same
        order as 'patchlist'
    """
    re_header = re.compile(r"^From [a-f0-9]+ Mon Sep 17 00:00:00 2001$")
    re_author = re.compile(r'^From: (.*) <(.*)>$')
    re_subject = re.compile(r'^Subject: (.*)$')
    re_date = re.compile(r'^Date: (.*)$')

    ret = [None] * len(patchlist)

    for patchidx, patchfn in enumerate(patchlist):
        patchfn = path.join(patchdir, patchfn)

        author, email, subject, date = None, None, None, None
        try:
            with open(patchfn, "r", encoding='utf8') as f:
                for i, l in enumerate(f):
                    l = l.rstrip()
                    if i == 0:
                        # header
                        if not re_header.match(l):
                            raise ValueError("Invalid header")
                        continue
                    if i == 1:
                        mtch = re_author.match(l)
                        if not mtch:
                            raise ValueError('Commit author not found')
                        author, email = mtch.group(1), mtch.group(2)
                    if i >= 1:
                        if all((date, subject)):
                            # all fields have been found
                            break
                        if not date:
                            mtch = re_date.match(l)
                            if mtch:
                                date = mtch.group(1)
                                continue
                        if not subject:
                            mtch = re_subject.match(l)
                            if mtch:
                                subject = mtch.group(1)
                                continue
            if not all((author, email, subject, date)):
                raise ValueError("Incomplete information")
            ret[patchidx] = PatchInfo(name=author, email=email, subject=subject, date=date)

        except OSError as ex:
            printerr(f"Cannot open '{patchfn}': {ex.strerror}")
            return None
        except (ValueError, RuntimeError) as ex:
            printerr(f"Error in '{patchfn}': {str(ex)}")
            return None

    return ret

def apply_patches(repodir, patchdir, patches, patchinfos, branchname):
    os.chdir(repodir)
    patchsettings, patchlist = patches
    assert len(patchlist) == len(patchinfos)
    base_commit_hash = patchsettings['base-commit']
    target_commit_hash = patchsettings['final-commit']

    print(f"Creating branch '{branchname}' from commit '{base_commit_hash}'")
    sp = subprocess.run(["git", "checkout", "-b", branchname, base_commit_hash])
    if sp.returncode:
        raise RuntimeError("Error creating branch")

    # this is to make sure committer's name/email is the same as patch author,
    # so that the end commit hash is the same
    committer_env = dict(os.environ)
    for i, patchname in enumerate(patchlist):
        patchinfo: PatchInfo = patchinfos[i]
        print(f"Applying patch {patchname} ...")

        # apply using 'patch'
        patch_fullpath = path.join(patchdir, patchname)
        with open(patch_fullpath, "rb") as f:
           if subprocess.run(["patch", "-p1", "--no-backup-if-mismatch"], stdin=f).returncode:
                raise RuntimeError(f"Error applying patch '{patchname}' cleanly.")

        # git stage changed files
        if subprocess.run(["git", "add", "."]).returncode:
            raise RuntimeError("Error staging updated files.")

        # git commit
        committer_env["GIT_AUTHOR_NAME"] = patchinfo.name
        committer_env["GIT_AUTHOR_EMAIL"] = patchinfo.email
        committer_env["GIT_AUTHOR_DATE"] = patchinfo.date
        committer_env["GIT_COMMITTER_NAME"] = patchinfo.name
        committer_env["GIT_COMMITTER_EMAIL"] = patchinfo.email
        committer_env["GIT_COMMITTER_DATE"] = patchinfo.date
        if subprocess.run(["git", "commit", "--no-verify", "-m", patchinfo.subject], env=committer_env).returncode:
            raise RuntimeError(f"Error committing changes.")

        print()

    # check the resulting commit hash
    if target_commit_hash == 'ignore':
        print("Ignoring target commit hash as instructed")
    else:
        sp = subprocess.run(["git", "rev-parse", "HEAD"], stdout=subprocess.PIPE)
        resulting_commit_hash = sp.stdout.decode('ascii').strip()
        if resulting_commit_hash != target_commit_hash:
            raise ValueError(f"Resulting commit hash '{resulting_commit_hash}' differs "
                f"from the expected hash '{target_commit_hash}'")

if __name__ == "__main__":
    sys.exit(main())
