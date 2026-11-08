"""Multinomial Naive Bayes with Laplace smoothing, trained on local examples."""
from collections import Counter
import csv
import hashlib
import math
from pathlib import Path
import re

from project import CATEGORIES


def tokens(text):
    return re.findall(r"[a-z]+", text.lower())


class Classifier:
    def __init__(self, dataset=None):
        dataset = dataset or Path(__file__).with_name("training.csv")
        self.version = "nb-v1-" + hashlib.sha256(dataset.read_bytes()).hexdigest()[:12]
        self.documents = Counter()
        self.words = {}
        self.vocabulary = set()
        with dataset.open(newline="", encoding="utf-8") as stream:
            for row in csv.DictReader(stream):
                category = row["category"]
                words = tokens(row["text"])
                self.documents[category] += 1
                self.words.setdefault(category, Counter()).update(words)
                self.vocabulary.update(words)
        if set(self.documents) != set(CATEGORIES) or not self.vocabulary:
            raise ValueError("Training data must cover all three categories.")

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
