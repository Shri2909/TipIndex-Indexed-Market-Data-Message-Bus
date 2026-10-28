"""Owned sibling staging files for source-preserving multi-output commands."""
from pathlib import Path
import os
import tempfile


def validate_outputs(source, outputs):
    """Check both resolved paths and existing inode aliases before any writes."""
    paths = [Path(source), *(Path(path) for path in outputs)]
    lexical = [Path(os.path.abspath(path)) for path in paths]
    resolved = [path.resolve() for path in paths]
    identities = []
    for path in paths:
        try:
            stat = path.stat()
            identities.append((stat.st_dev, stat.st_ino))
        except FileNotFoundError:
            identities.append(None)
    for index in range(1, len(paths)):
        if any(resolved[index] == resolved[other] or
               (identities[index] is not None and identities[index] == identities[other]) or
               lexical[index].is_relative_to(lexical[other]) or
               lexical[other].is_relative_to(lexical[index]) or
               resolved[index].is_relative_to(resolved[other]) or
               resolved[other].is_relative_to(resolved[index])
               for other in range(index)):
            raise ValueError("outputs must be distinct and preserve the source input")


class OutputTransaction:
    """Prepare everything first; roll back handled publication failures.

    Each rename is atomic. A whole bundle is not crash-atomic across several
    renames, so callers must not treat interrupted publication as accepted data.
    No predictable temporary filename is opened or removed.
    """
    def __init__(self, source, outputs):
        self.outputs = [Path(path) for path in outputs]
        validate_outputs(source, self.outputs)
        self.staged = {}
        self.backups = {}
        self.published = []

    @staticmethod
    def _reserve(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=f'.{path.name}.', suffix='.partial', dir=path.parent)
        os.close(fd)
        return Path(name)

    def __enter__(self):
        try:
            for path in self.outputs:
                self.staged[path] = self._reserve(path)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def path(self, final):
        return self.staged[Path(final)]

    def commit(self):
        try:
            for path in self.outputs:
                if path.exists() or path.is_symlink():
                    backup = self._reserve(path)
                    try:
                        os.replace(path, backup)
                    except BaseException:
                        backup.unlink(missing_ok=True)
                        raise
                    self.backups[path] = backup
            for path in self.outputs:
                os.replace(self.staged[path], path)
                self.published.append(path)
        except BaseException:
            for path in reversed(self.published):
                path.unlink(missing_ok=True)
            for path, backup in self.backups.items():
                if backup.exists() or backup.is_symlink():
                    os.replace(backup, path)
            raise
        for backup in self.backups.values():
            backup.unlink(missing_ok=True)
        self.backups.clear()

    def __exit__(self, *_):
        for path in self.staged.values():
            path.unlink(missing_ok=True)
        # Retain a backup if rollback itself failed: never discard old evidence.
