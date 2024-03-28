# Simple Patch Manager

This Python script manages patches in a a reproducible way: the end result of every run will have the same commit hash. This is useful for projects which uses commit hashes as their versioning methodology.

## Usage

```
python3 spm.py [--branchname (branchname)] (patchdir) (repo)
python3 spm.py [--checkpatches] (patchdir)
```

This script will apply patches in the order specified in `$patchdir/patches.list`. All patches will be applied from top to bottom of that list. The `patches.list` must begin with the following line:

```
base-commit: (commit hash)
final-commit: (commit hash)
```

The `base-commit` specifies which commit to begin from, and the `final-commit` is the target commit hash after applying all the patches. When the final commit hash after applying all the patches does not match with with the `final-commit`, this script will emit a warning and return a nonzero exit code (put `ignore` as the value for `final-commit` to supress this check).

### Patches list

The `patches.list` is then followed by list of patches. Lines beginning with `#` will be treated as comments (ignored). The patch files must be generated from `git format-patch`. The following criteria also applies:

- Can be inside the same directory or any subdirectory of the `$patchdir`.
  - Path components must not contain `.` or `..`.
  - Path components must not begin with `.`.
- Patch file name must end with `.patch`.
- All path must be relative to `$patchdir`.
- Name can only contain these characters:
  - Lowercase alphabets (`a-z`).
  - Uppercase alphabets (`A-Z`).
  - Numbers (`0-9`).
  - Dash (`-`).

By default, a new branch named `patched` will be created on the repo. This can be overriden using the `--branchname` option.

The `--checkpatches` option can be used to see if the patches follows the above criteria.

## Working Principles

This script will apply the given patches using the system's built-in `patch` command. The previous version of this script uses `git am`, but `git am` does not work on shallow clones, thus we switched over to use the `patch` command. After the `patch`, this script will then perform a Git commit to all unstaged changes made. This script will stop on a `patch` failure.
