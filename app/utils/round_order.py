INTERNAL_ROUND_ORDER = ("L1", "L2", "L3", "L3A", "L4", "L5", "L6")


def round_sort_key(round_key: str):
    value = str(round_key or "").upper()
    if value.startswith("L") and value[1:].isdigit():
        return (0, int(value[1:]), value)
    return (1, 999, value)


def ordered_present_round_keys(keys_or_mapping):
    if isinstance(keys_or_mapping, dict):
        keys = [str(k) for k in keys_or_mapping.keys()]
    else:
        keys = [str(k) for k in (keys_or_mapping or [])]

    ordered = [rk for rk in INTERNAL_ROUND_ORDER if rk in keys]
    remaining = [rk for rk in sorted(keys, key=round_sort_key) if rk not in ordered]
    return ordered + remaining


def round_number_map(keys_or_mapping):
    ordered = ordered_present_round_keys(keys_or_mapping)
    return {rk: idx + 1 for idx, rk in enumerate(ordered)}
