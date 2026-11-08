"""Train the review-sentiment classifier and evaluate held-out text.

From the repository root:

    python -m services.ai.train
"""
import csv
from pathlib import Path

from services.ai.model import ARTIFACT, TRAINING, Classifier, artifact_state, save_artifact

EVAL = Path(__file__).with_name("eval.csv")


def evaluate(model, dataset=EVAL):
    results = []
    with Path(dataset).open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            actual = model.predict(row["text"])["category"]
            results.append({
                "text": row["text"],
                "expected": row["category"],
                "actual": actual,
                "kind": row.get("kind", "clear"),
                "correct": actual == row["category"],
            })
    return results


def main():
    state = artifact_state(TRAINING)
    save_artifact(state, ARTIFACT)
    model = Classifier()
    results = evaluate(model)
    correct = sum(item["correct"] for item in results)
    clear = [item for item in results if item["kind"] == "clear"]
    clear_correct = sum(item["correct"] for item in clear)
    print(f"artifact: {ARTIFACT}")
    print(f"version: {model.version}")
    print(f"trained_rows: {sum(state['documents'].values())}")
    print(f"eval_correct: {correct}/{len(results)}")
    print(f"clear_correct: {clear_correct}/{len(clear)}")
    for item in results:
        mark = "ok" if item["correct"] else "MISS"
        print(f"{mark}\t{item['kind']}\t{item['expected']}\t{item['actual']}\t{item['text']}")


if __name__ == "__main__":
    main()
