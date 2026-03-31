from __future__ import annotations


class FsAccessError(Exception):
    pass


class FsAccessDenied(FsAccessError):
    pass


class FsNotFound(FsAccessError):
    pass


class FsTooLarge(FsAccessError):
    pass

