def calculate_average(numbers):
    total = 0
    for n in numbers:
        total += n
    average = total / len(numbers)
    return average


def process_data(data):
    results = []
    for label, values in data.items():
        avg = calculate_average(values)
        results.append({"label": label, "average": avg})
    return results


if __name__ == "__main__":
    dataset = {
        "group_a": [10, 20, 30, 40],
        "group_b": [5, 15, 25],
        "group_c": [],          # bug: will cause ZeroDivisionError
    }

    results = process_data(dataset)
    for r in results:
        print(f"{r['label']}: {r['average']}")
