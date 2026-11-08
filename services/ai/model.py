"""Multinomial Naive Bayes with Laplace smoothing.

`python -m services.ai.train` fits the labeled review text and writes
`artifact.json`. The service loads that file at startup.
"""
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import re

from project import CATEGORIES

ARTIFACT = Path(__file__).with_name("artifact.json")
TRAINING = Path(__file__).with_name("training.csv")


def tokens(text):
    return re.findall(r"[a-z]+", text.lower())


def version_for(dataset):
    # Hash LF text so a Windows CRLF checkout does not change the version.
    raw = Path(dataset).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    digest = hashlib.sha256(raw).hexdigest()[:12]
    return "nb-v2-" + digest


def read_rows(dataset):
    rows = []
    with Path(dataset).open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            rows.append((row["category"], row["text"]))
    return rows


def fit(rows):
    documents = Counter()
    words = {}
    vocabulary = set()
    for category, text in rows:
        observed = tokens(text)
        documents[category] += 1
        words.setdefault(category, Counter()).update(observed)
        vocabulary.update(observed)
    if set(documents) != set(CATEGORIES) or not vocabulary:
        raise ValueError("Training data must cover all three categories.")
    return documents, words, vocabulary


def artifact_state(dataset):
    dataset = Path(dataset)
    documents, words, vocabulary = fit(read_rows(dataset))
    return {
        "algorithm": "multinomial-naive-bayes",
        "version": version_for(dataset),
        "documents": dict(documents),
        "words": {category: dict(counts) for category, counts in words.items()},
        "vocabulary": sorted(vocabulary),
    }


def save_artifact(state, path=ARTIFACT):
    Path(path).write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class Classifier:
    def __init__(self, dataset=None, artifact=None):
        if dataset is not None:
            documents, words, vocabulary = fit(read_rows(dataset))
            version = version_for(dataset)
        else:
            path = Path(artifact) if artifact is not None else ARTIFACT
            state = json.loads(path.read_text(encoding="utf-8"))
            documents = Counter(state["documents"])
            words = {category: Counter(counts) for category, counts in state["words"].items()}
            vocabulary = set(state["vocabulary"])
            version = state["version"]
        self.version = version
        self.documents = documents
        self.words = words
        self.vocabulary = vocabulary

    def predict(self, text):
        observed = Counter(word for word in tokens(text) if word in self.vocabulary)
        scores = {}
        for category in sorted(self.documents):
            word_counts = self.words[category]
            denominator = sum(word_counts.values()) + len(self.vocabulary)
            scores[category] = math.log(self.documents[category] / self.documents.total())
            scores[category] += sum(
                count * math.log((word_counts[word] + 1) / denominator)
                for word, count in observed.items()
            )
        return {"category": max(scores, key=scores.get), "model_version": self.version}
