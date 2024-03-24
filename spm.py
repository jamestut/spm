#!/usr/bin/env python3

"""
Simple Patch Manager main program
"""

import sys
import argparse
import re
import os
import subprocess
from os import path

DEFAULT_BRANCH = "patched"
PATCH_DEF_FILE = "patches.list"

def printerr(*args, **kwargs):
    kwargs['file'] = sys.stderr
    print(*args, **kwargs)

def main():
    parser = argparse.ArgumentParser(description='Simple patch manager')

    parser.add_argument("-a", "--abort-on-conflict", action="store_true",
        help="Stop patching on unclean patch apply instead of prompting user "
            "to do manual actions.")
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

    patchinfo = get_patch_info(patchdir)
    if patchinfo is None:
        return 1
    _, patchlist = patchinfo

    patchauthors = get_patch_authors(patchdir, patchlist)
    if patchauthors is None:
        return 1

    if args.checkpatches:
        print("All patches appears to be in correct format")
        return 0

    if args.repo is None:
        printerr("Please specify repository to be patched!")
        return 1

    try:
        apply_patches(args.repo, patchdir, patchinfo, patchauthors,
            args.branchname, args.abort_on_conflict)
    except OSError as ex:
        printerr(f"Error opening repository: {ex.strerror}")
        return 1
    except (RuntimeError, ValueError) as ex:
        printerr(str(ex))
        return 1

    print("All patches applied cleanly!")
    return 0

def get_patch_info(patchdir):
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

def get_patch_authors(patchdir, patchlist):
    """
    Returns:
        A list of tuples of (author name, author email). The list is in the same
        order as 'patchlist'
    """
    re_header = re.compile(r"^From [a-f0-9]+ Mon Sep 17 00:00:00 2001$")
    re_author = re.compile(r'^From: (.*) <(.*)>$')
    re_name_utf8_detect = re.compile(r'^=\?UTF-8\?q\?(.+)\?=$')
    re_name_utf8_sub = re.compile(rb'=([\da-fA-F]{2})')
    def re_name_utf8_sub_fn(m):
        return bytes.fromhex(m.group(1).decode('ascii'))

    ret = [None] * len(patchlist)

    for patchidx, patchfn in enumerate(patchlist):
        patchfn = path.join(patchdir, patchfn)

        try:
            authorlines = []
            with open(patchfn, "r", encoding='utf8') as f:
                for i, l in enumerate(f):
                    l = l.rstrip()
                    if i == 0:
                        # header
                        if not re_header.match(l):
                            raise ValueError("Invalid header")
                        continue
                    if i == 1:
                        if not l.startswith('From: '):
                            raise ValueError("'From' field not found")
                    if i >= 1:
                        # end of 'From' (author) lines
                        if l.startswith('Date: '):
                            break
                        authorlines.append(l)

            authormatch = re_author.match(''.join(authorlines))
            if not authormatch:
                raise ValueError("Error reading patch's author")

            authorname, authoremail = authormatch.group(1), authormatch.group(2)

            # git format-patch only encodes names to utf8 if necessary.
            # email is always verbatim, even if it contains emojis.
            authorname_utf8 = re_name_utf8_detect.match(authorname)
            if authorname_utf8:
                authorname_bin = authorname_utf8.group(1).encode('utf8')
                authorname_bin = re_name_utf8_sub.sub(re_name_utf8_sub_fn,
                    authorname_bin)
                authorname = authorname_bin.decode('utf8')

            ret[patchidx] = authorname, authoremail

        except OSError as ex:
            printerr(f"Cannot open '{patchfn}': {ex.strerror}")
            return None
        except (ValueError, RuntimeError) as ex:
            printerr(f"Error in '{patchfn}': {str(ex)}")
            return None

    return ret

def apply_patches(repodir, patchdir, patchinfo, patchauthors, branchname, abort_on_conflict):
    os.chdir(repodir)
    patchsettings, patchlist = patchinfo
    assert len(patchlist) == len(patchauthors)
    base_commit_hash = patchsettings['base-commit']
    target_commit_hash = patchsettings['final-commit']

    print(f"Creating branch '{branchname}' from commit '{base_commit_hash}'")
    sp = subprocess.run(["git", "checkout", "-b", branchname, base_commit_hash])
    if sp.returncode:
        raise RuntimeError("Error creating branch")

    # this is to make sure committer's name/email is the same as patch author,
    # so that the end commit hash is the same
    committer_env = dict(os.environ)
    git_apply_patch_args = ["git", "am", "--3way", "--committer-date-is-author-date", None]
    for i, patchname in enumerate(patchlist):
        print(f"Applying patch {patchname} ...")

        author_name, author_email = patchauthors[i]
        committer_env["GIT_COMMITTER_NAME"] = author_name
        committer_env["GIT_COMMITTER_EMAIL"] = author_email

        patch_fullpath = path.join(patchdir, patchname)
        git_apply_patch_args[-1] = patch_fullpath
        sp = subprocess.run(git_apply_patch_args, env=committer_env)

        if sp.returncode:
            errmsg = f"Error applying patch '{patchname}' cleanly."
            if abort_on_conflict:
                raise RuntimeError(errmsg)
            print(errmsg)
            # ask user what to do next
            while True:
                useript = input('(C) = continue, (A) = abort? ')
                if useript in ('A', 'a'):
                    raise RuntimeError('User aborted the conflict resolution operation')
                if useript in ('C', 'c'):
                    break

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
