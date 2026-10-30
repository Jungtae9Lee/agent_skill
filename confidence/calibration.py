"""확신도 기록(CSV)에서 보정 상태를 측정한다.

사용법: python calibration.py calibration-log.csv
CSV 헤더: date,claim,p_yes,basis,correct  (correct 1/0, 미정이면 빈칸)
"""
import csv
import sys

BINS = [(0.0, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 0.95), (0.95, 1.0001)]


def load(path):
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if (r.get("correct") or "").strip() == "":
                continue  # 아직 정답을 모르는 항목은 제외
            rows.append((float(r["p_yes"]), int(r["correct"]), (r.get("basis") or "").strip()))
    return rows


def report(rows):
    n = len(rows)
    if n == 0:
        print("채점된 기록이 없습니다.")
        return
    print(f"채점된 기록: {n}건\n")
    print(f"{'구간':<12}{'건수':>6}{'평균 P(Y)':>12}{'실제 정답률':>12}{'차이':>8}")
    ece = 0.0
    for lo, hi in BINS:
        b = [(p, c) for p, c, _ in rows if lo <= p < hi]
        if not b:
            continue
        conf = sum(p for p, _ in b) / len(b)
        acc = sum(c for _, c in b) / len(b)
        ece += len(b) / n * abs(acc - conf)
        label = f"{lo:.2f}-{min(hi, 1.0):.2f}"
        print(f"{label:<12}{len(b):>6}{conf:>12.2f}{acc:>12.2f}{acc - conf:>+8.2f}")
    brier = sum((p - c) ** 2 for p, c, _ in rows) / n
    print(f"\nECE   = {ece:.3f}  (0에 가까울수록 보정이 잘 됨)")
    print(f"Brier = {brier:.3f}  (낮을수록 좋음)")

    print("\n근거 종류별:")
    for basis in sorted({b for _, _, b in rows}):
        b = [(p, c) for p, c, bb in rows if bb == basis]
        conf = sum(p for p, _ in b) / len(b)
        acc = sum(c for _, c in b) / len(b)
        print(f"  {basis or '(없음)'}: {len(b)}건, 평균 P(Y) {conf:.2f}, 실제 {acc:.2f}")

    if n < 30:
        print("\n※ 30건 미만이라 통계적으로 불안정합니다.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 기본 cp949 대신 UTF-8로 출력
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    report(load(sys.argv[1]))
