"""Immutable compressed snapshots and finite decompression for every CSV entry."""
from dataclasses import dataclass
import hashlib
import io
from pathlib import Path
import zipfile


@dataclass(frozen=True)
class ArchiveLimits:
    archive_bytes: int = 12_000_000
    member_bytes: int = 60_000_000
    total_bytes: int = 150_000_000
    member_count: int = 10_000

    def __post_init__(self):
        if any(type(v) is not int or v < 1 for v in vars(self).values()):
            raise ValueError('Archive bounds must be positive integers')


DEFAULT_LIMITS = ArchiveLimits()


class BoundedArchive(zipfile.ZipFile):
    """Validate all members before the first read, including unsupported files.

    One bounded compressed snapshot supplies both hashes and decompression; path
    replacement cannot substitute different bytes between validation and reading.
    """
    def __init__(self, path_or_bytes, *, limits=None):
        self.limits = limits if limits is not None else DEFAULT_LIMITS
        if isinstance(path_or_bytes, bytes):
            raw = path_or_bytes
        else:
            with Path(path_or_bytes).open('rb') as source:
                raw = source.read(self.limits.archive_bytes + 1)
        if len(raw) > self.limits.archive_bytes:
            raise ValueError('COMPRESSED_SIZE_LIMIT')
        self.snapshot_sha256 = hashlib.sha256(raw).hexdigest()
        self.snapshot_bytes = raw
        self.compressed_bytes = len(raw)
        super().__init__(io.BytesIO(raw))
        try:
            members = self.infolist()
            if len(members) > self.limits.member_count:
                raise ValueError('MEMBER_COUNT_LIMIT')
            if any(m.file_size > self.limits.member_bytes for m in members):
                raise ValueError('MEMBER_SIZE_LIMIT')
            if sum(m.file_size for m in members) > self.limits.total_bytes:
                raise ValueError('TOTAL_SIZE_LIMIT')
        except BaseException:
            self.close()
            raise

    def read(self, name, pwd=None):
        info = name if isinstance(name, zipfile.ZipInfo) else self.getinfo(name)
        if info.file_size > self.limits.member_bytes:
            raise ValueError('MEMBER_SIZE_LIMIT')
        with super().open(info, pwd=pwd) as member:
            raw = member.read(min(info.file_size, self.limits.member_bytes) + 1)
        if len(raw) > self.limits.member_bytes:
            raise ValueError('MEMBER_SIZE_LIMIT')
        if len(raw) != info.file_size:
            raise ValueError('MEMBER_DECLARED_SIZE_MISMATCH')
        return raw
