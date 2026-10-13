"""Pinned original CSV; only note text and source identity leave this boundary."""
import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen

SOURCE_COMMIT = "b1f27e11ec1e00908b7d2f1cab1e5b8c9b68e28b"
SOURCE_FILES = {
    "SimSUM.csv": "64e58b9724b23ce502343f7006513e6cc36c2a9e28c306c41aedd6b8b4c0816b",
    "data/spans/normal_span_annotations.json": "3e759ce97bb74f608e851b55d791b04462572abd09badc5f410b612ba50767a2",
    "data/spans/adv_span_annotations.json": "49ea81ee514cef689df8e26d7f89bc867e5e2ac8ff8d1ede2734e788c51b6d7c",
}
SPLIT_VERSION = "simsum-patient-sha256-v1"


def sha(value: bytes | str):
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def write_json(path: Path, value, *, immutable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if immutable:
        if path.exists():
            if path.read_text(encoding="utf-8") != content:
                raise ValueError(f"Frozen artifact differs: {path}")
            return
        with path.open("x", encoding="utf-8", newline="\n") as f:
            f.write(content)
    else:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8", newline="\n")
        tmp.replace(path)


def download(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    for relative, checksum in SOURCE_FILES.items():
        dest = folder / Path(relative).name
        if not dest.exists():
            with urlopen(f"https://raw.githubusercontent.com/prabaey/SimSUM/{SOURCE_COMMIT}/{relative}") as r:
                content = r.read()
            if sha(content) != checksum:
                raise ValueError(f"Downloaded checksum mismatch: {relative}")
            dest.write_bytes(content)
    verify_sources(folder)


def verify_sources(folder: Path):
    for relative, checksum in SOURCE_FILES.items():
        if sha((folder / Path(relative).name).read_bytes()) != checksum:
            raise ValueError(f"Source checksum mismatch: {relative}")


@dataclass(frozen=True)
class Document:
    row_id: str
    row_index: int
    variant: str
    text: str
    source_sha256: str
    note_sha256: str

    @property
    def document_id(self):
        return f"simsum:{self.row_id}:{self.variant}"

    def verify(self):
        if sha(self.text) != self.note_sha256:
            raise ValueError("Note hash differs from source identity")


def load_notes(csv_path: Path, *, expected_sha=SOURCE_FILES["SimSUM.csv"]):
    source_hash = sha(csv_path.read_bytes())
    if expected_sha is not None and source_hash != expected_sha:
        raise ValueError("CSV source checksum mismatch")
    result = {}
    with csv_path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        if not {"", "text", "advanced_text"} <= set(reader.fieldnames or []):
            raise ValueError("Original CSV identity/note columns missing")
        for index, row in enumerate(reader):
            row_id = row[""]
            if row_id in result or not row_id:
                raise ValueError("Duplicate or empty CSV row identity")
            result[row_id] = {v: Document(row_id, index, v, row[v], source_hash, sha(row[v]))
                              for v in ("text", "advanced_text")}
    return result


def build_partition(notes, *, development_count=8000, batch_size=300):
    if len(notes) != 10000 or development_count != 8000 or batch_size != 300:
        raise ValueError("Batch 1 requires the original 10,000 records and 8,000/2,000 split")
    ranked = sorted(notes, key=lambda i: sha(f"{SPLIT_VERSION}:partition:{i}"))
    development = set(ranked[:development_count])
    selected = sorted(development, key=lambda i: sha(f"{SPLIT_VERSION}:batch1:{i}"))[:batch_size]
    selection = {i: "text" if j < 150 else "advanced_text" for j, i in enumerate(selected)}
    records = [{"row_id": i, "row_index": notes[i]["text"].row_index,
                "partition": "development" if i in development else "final_test",
                "note_sha256": {v: d.note_sha256 for v, d in notes[i].items()},
                "batch1_variant": selection.get(i)} for i in notes]
    return {"split_version": SPLIT_VERSION, "source_commit": SOURCE_COMMIT,
            "source_files": SOURCE_FILES, "records": records,
            "batch1": [notes[i][selection[i]].document_id for i in selected]}


def selected_documents(notes, partition):
    # Recompute all identities and selections, never trust an edited manifest.
    if build_partition(notes) != partition:
        raise ValueError("Frozen partition/source identity mismatch")
    return [notes[r["row_id"]][r["batch1_variant"]] for r in partition["records"]
            if r["batch1_variant"] is not None]


def build_batch2(notes, partition, partition_sha256):
    selected_documents(notes, partition)  # Validate the complete existing split, without editing it.
    used = {r["row_id"] for r in partition["records"] if r["batch1_variant"] is not None}
    eligible = [r["row_id"] for r in partition["records"]
                if r["partition"] == "development" and r["row_id"] not in used]
    selected = sorted(eligible, key=lambda i: sha(f"{SPLIT_VERSION}:batch2:{i}"))[:300]
    return {"batch": 2, "selection_version": "simsum-new-patients-batch2-v1",
            "partition_sha256": partition_sha256, "source_commit": SOURCE_COMMIT,
            "documents": [{"document_id": notes[i][v].document_id, "row_id": i,
                           "row_index": notes[i][v].row_index, "variant": v,
                           "note_sha256": notes[i][v].note_sha256,
                           "source_sha256": notes[i][v].source_sha256}
                          for j, i in enumerate(selected)
                          for v in ["text" if j < 150 else "advanced_text"]]}


def selected_batch2(notes, partition, partition_sha256, manifest):
    if build_batch2(notes, partition, partition_sha256) != manifest:
        raise ValueError("Frozen Batch 2 selection/source identity mismatch")
    return [notes[r["row_id"]][r["variant"]] for r in manifest["documents"]]
