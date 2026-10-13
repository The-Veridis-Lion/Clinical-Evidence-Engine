"""Original ACI-BENCH train inputs, isolated from reference notes and metadata."""
import csv
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.request import urlopen

from ..clinical_notes.dataset import sha, write_json

REVISION = "b909b2bb9cf1d19de08df15cddde7bd0179665e4"
SOURCE_PATH = "data/challenge_data/train.csv"
REPOSITORY = "https://github.com/wyim/aci-bench"
SELECTION = {
    "aci": ["D2N033", "D2N034", "D2N035", "D2N036"],
    "virtassist": ["D2N001", "D2N002", "D2N003"],
    "virtscribe": ["D2N021", "D2N022", "D2N023"],
}
SOURCE_HASHES = {"train.csv": "6c778d4ac5e6cc6f1964786f9286e8d765c210f22ed6b57f83aff8497409cea4",
    "train_metadata.csv": "7da650e223f04ff6bf1666cb62d52ebd83ce71ecfc4b2311cbe64d9f3ab19d83"}


@dataclass(frozen=True)
class Document:
    document_id: str
    encounter_id: str
    subset: str
    text: str
    note_sha256: str  # Existing provider interface: hash of input, NEVER a reference note.
    source_sha256: str
    row_index: int
    input_kind: str = "dialogue"

    def verify(self):
        if sha(self.text) != self.note_sha256:
            raise ValueError("Input transcript hash mismatch")


def download(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("train.csv", "train_metadata.csv", "README.md"):
        relative = "README.md" if name == "README.md" else "data/challenge_data/" + name
        path = folder / name
        if not path.exists():
            with urlopen(f"https://raw.githubusercontent.com/wyim/aci-bench/{REVISION}/{relative}", timeout=30) as response:
                path.write_bytes(response.read())
        if name in SOURCE_HASHES and sha(path.read_bytes()) != SOURCE_HASHES[name]:
            raise ValueError("Original dataset checksum mismatch: " + name)


def training_documents(path: Path):
    checksum = sha(path.read_bytes())
    if checksum != SOURCE_HASHES["train.csv"]:
        raise ValueError("Original ACI-BENCH training file checksum mismatch")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 67 or len({r["encounter_id"] for r in rows}) != 67:
        raise ValueError("Expected original 67 unique training encounters")
    wanted = {(subset, identity) for subset, ids in SELECTION.items() for identity in ids}
    documents = []
    for i, row in enumerate(rows):
        if (row["dataset"], row["encounter_id"]) in wanted:
            # Explicit whitelist. The 'note' and metadata columns never leave this function.
            text = row["dialogue"]
            documents.append(Document("aci-bench:train:" + row["encounter_id"],
                row["encounter_id"], row["dataset"], text, sha(text), checksum, i))
    if len(documents) != 10:
        raise ValueError("Frozen training encounter missing")
    return sorted(documents, key=lambda d: d.document_id)


def note_document(path: Path):
    text = path.read_text(encoding="utf-8")
    return Document("note:" + sha(text)[:16], path.stem, "clinical-note", text,
                    sha(text), sha(path.read_bytes()), 0, "note")


def source_index(doc):
    """Exact code-point slices; source labels never corrected or treated as verified roles."""
    doc.verify()
    tags = list(re.finditer(r"\[(doctor|patient|nurse|clinician|physician|provider)\]", doc.text, re.I)) if doc.input_kind == "dialogue" else []
    boundaries = [m.start() for m in tags]
    if not boundaries or boundaries[0] != 0:
        boundaries.insert(0, 0)
    boundaries.append(len(doc.text))
    turns, catalogue = [], []
    for number, (start, end) in enumerate(zip(boundaries, boundaries[1:]), 1):
        if start == end:
            continue
        turn_id = f"t{number:04d}"
        label = next((m.group(0) for m in tags if m.start() == start), None)
        turns.append({"turn_id": turn_id, "speaker_label": label, "start": start,
                      "end": end, "quote": doc.text[start:end]})
        body_start = start + len(label or "")
        stops = [body_start] + [body_start + m.end() for m in re.finditer(
            r"\n|(?<=[.!?])\s+(?=[A-Za-z])", doc.text[body_start:end])] + [end]
        for a, b in zip(stops, stops[1:]):
            while a < b and doc.text[a].isspace():
                a += 1
            while b > a and doc.text[b - 1].isspace():
                b -= 1
            if a < b:
                catalogue.append({"source_id": f"{turn_id}:{a}:{b}", "turn_id": turn_id,
                    "speaker_label": label, "start": a, "end": b, "quote": doc.text[a:b]})
    if not catalogue:
        raise ValueError("Empty source input")
    return {"turns": turns, "source_catalogue": catalogue}


def freeze_inputs(root: Path, documents, *, checkpoint):
    manifest = {"version": "aci-bench-dialogue-selection-v1", "repository": REPOSITORY,
        "revision": REVISION if documents[0].input_kind == "dialogue" else None,
        "source_path": SOURCE_PATH if documents[0].input_kind == "dialogue" else None,
        "split": "train" if documents[0].input_kind == "dialogue" else None,
        "checkpoint": checkpoint, "selection_rule": "first IDs lexicographically within each subset: aci=4, virtassist=3, virtscribe=3; chosen before inference",
        "offset_unit": "zero-based Python Unicode code points, end exclusive",
        "encounters": [{k: v for k, v in asdict(d).items() if k != "text"} for d in documents]}
    write_json(root / "selection.json", manifest, immutable=True)
    write_json(root / "inputs.json", [asdict(d) for d in documents], immutable=True)
    for d in documents:
        write_json(root / "sources" / (d.encounter_id + ".json"), source_index(d), immutable=True)
    return manifest


def load_inputs(root: Path):
    docs = [Document(**d) for d in json.loads((root / "inputs.json").read_text(encoding="utf-8"))]
    manifest = json.loads((root / "selection.json").read_text(encoding="utf-8"))
    if not docs or len({d.document_id for d in docs}) != len(docs):
        raise ValueError("Empty or duplicate frozen inputs")
    if manifest["encounters"] != [{k: v for k, v in asdict(d).items() if k != "text"} for d in docs]:
        raise ValueError("Inputs differ from frozen selection")
    for d in docs:
        d.verify()
        if source_index(d) != json.loads((root / "sources" / (d.encounter_id + ".json")).read_text(encoding="utf-8")):
            raise ValueError("Frozen source index changed")
    return docs
