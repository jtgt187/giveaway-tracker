def calculate_win_probability(your_entries, total_entries):
    if total_entries == 0:
        return 0.0
    return (your_entries / total_entries) * 100


def format_probability(prob):
    if prob is None or prob == 0.0:
        return "N/A"
    if prob >= 1.0:
        return f"{prob:.1f}%"
    elif prob >= 0.1:
        return f"{prob:.2f}%"
    else:
        return f"{prob:.4f}%"
