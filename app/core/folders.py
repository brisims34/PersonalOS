"""Project and workstream folders on disk.

Creating a project creates `projects/<Portfolio>/<project-slug>/`. Creating a
workstream creates a subfolder inside it. Renaming **moves** the folder and
preserves its contents — it never creates a second one and orphans the first.

Every path goes through `paths.confine()` before any filesystem call
(CLAUDE.md rule 7). Nothing here ever deletes a folder: archiving a project
leaves the files exactly where they are (P5).
"""
import shutil

from app.core import paths
from app.core.paths import PathConfinementError, confine, safe_slug


class FolderError(RuntimeError):
    pass


def _vault_root():
    return paths.VAULT_ROOT


def siblings(parent):
    """Slugs already in use inside `parent`, so a new one cannot collide."""
    if not parent.exists():
        return set()
    return {child.name.lower() for child in parent.iterdir() if child.is_dir()}


def project_folder(portfolio_folder_slug, project_slug):
    """Absolute path for a project, confined to the vault root."""
    return confine(_vault_root(), f"{portfolio_folder_slug}/{project_slug}")


def provision_project(portfolio_folder_slug, project_name, existing_slug=None):
    """Create the project folder. Returns (relative_path, absolute_path).

    Idempotent: an existing folder is adopted rather than duplicated, which is
    what makes re-provisioning after a manual copy safe.
    """
    portfolio_dir = confine(_vault_root(), portfolio_folder_slug)
    portfolio_dir.mkdir(parents=True, exist_ok=True)

    slug = existing_slug or safe_slug(project_name, taken=siblings(portfolio_dir))
    target = confine(_vault_root(), f"{portfolio_folder_slug}/{slug}")
    target.mkdir(parents=True, exist_ok=True)

    # Conventional subfolders. Cheap to create, awkward to add consistently
    # later once people have started filing things by hand.
    for sub in ("meetings", "attachments", "status"):
        (target / sub).mkdir(exist_ok=True)

    return f"{portfolio_folder_slug}/{slug}", target


def provision_workstream(project_rel_path, workstream_name, existing_slug=None):
    project_dir = confine(_vault_root(), project_rel_path)
    if not project_dir.exists():
        raise FolderError(
            f"the project folder {project_rel_path} does not exist — "
            "re-provision the project first"
        )

    reserved = {"meetings", "attachments", "status"}
    slug = existing_slug or safe_slug(
        workstream_name, taken=siblings(project_dir) | reserved
    )
    target = confine(_vault_root(), f"{project_rel_path}/{slug}")
    target.mkdir(parents=True, exist_ok=True)
    return f"{project_rel_path}/{slug}", target


def rename_folder(old_rel_path, new_name):
    """Move a folder to a new slug, keeping its contents. Returns the new path.

    A rename that copied instead of moved would leave notes behind under a
    stale name, and the index would keep finding both.
    """
    if not old_rel_path:
        raise FolderError("no existing folder path recorded — nothing to rename")

    source = confine(_vault_root(), old_rel_path)
    parent_rel = "/".join(old_rel_path.strip("/").split("/")[:-1])
    parent = confine(_vault_root(), parent_rel) if parent_rel else _vault_root()

    taken = siblings(parent) - {source.name.lower()}
    slug = safe_slug(new_name, taken=taken)
    if slug == source.name:
        return old_rel_path, source

    target = confine(_vault_root(), f"{parent_rel}/{slug}" if parent_rel else slug)
    if not source.exists():
        target.mkdir(parents=True, exist_ok=True)
        return (f"{parent_rel}/{slug}" if parent_rel else slug), target
    if target.exists():
        raise FolderError(f"{target.name} already exists in {parent_rel or 'the vault root'}")

    shutil.move(str(source), str(target))
    return (f"{parent_rel}/{slug}" if parent_rel else slug), target


def open_in_explorer(rel_path):
    """Open the folder in Windows Explorer. No-op elsewhere.

    Returns the command that was run, or None, so the caller can report
    honestly instead of claiming success on a platform that cannot do it.
    """
    import subprocess
    import sys

    target = confine(_vault_root(), rel_path)
    if not target.exists():
        raise FolderError(f"{rel_path} does not exist on disk")
    if sys.platform != "win32":
        return None
    subprocess.Popen(["explorer", str(target)])
    return str(target)


def folder_summary(rel_path):
    """What is actually on disk, for the project page. Never reads contents."""
    if not rel_path:
        return None
    try:
        target = confine(_vault_root(), rel_path)
    except PathConfinementError:
        return {"exists": False, "error": "path escapes the vault root"}
    if not target.exists():
        return {"exists": False, "path": str(target)}

    files = notes = 0
    for child in target.rglob("*"):
        if child.is_file():
            files += 1
            if child.suffix.lower() == ".md":
                notes += 1
    return {
        "exists": True,
        "path": str(target),
        "file_count": files,
        "note_count": notes,
        "subfolders": sorted(c.name for c in target.iterdir() if c.is_dir()),
    }
