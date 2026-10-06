"""All intervaltree objects are confined here; callers use application intervals."""
from intervaltree import IntervalTree
from .domain import TimeInterval


def treatment_minutes(intervals: list[TimeInterval], breaks: list[TimeInterval]) -> int:
    tree = IntervalTree.from_tuples((i.start, i.end) for i in intervals)
    tree.merge_overlaps(strict=False)
    for interval in breaks:
        tree.chop(interval.start, interval.end)
    return sum(i.end - i.begin for i in tree)
