#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
compare_csv_keys.py

Порівнює ключі (колонка 'key') у двох CSV-файлах, згенерованих скриптом парсингу,
та виводить відмінності:
 - ключі, що є лише у A
 - ключі, що є лише у B
 - перетин (спільні ключі) — опційно

Використання:
  python compare_csv_keys.py fileA.csv fileB.csv
  або з іменованими аргументами:
  python compare_csv_keys.py --a fileA.csv --b fileB.csv
"""

import argparse
import csv
import os
import sys
from typing import Set, Tuple, List, Optional, Dict

# Optional GUI for file selection
try:
    import tkinter as tk
    from tkinter import filedialog
except Exception:
    tk = None
    filedialog = None


def read_csv_entries(csv_path: str) -> Tuple[Optional[List[str]], List[Tuple[str, List[str]]]]:
    """Зчитує CSV і повертає (header, entries), де entries — список (key, full_row) у вихідному порядку.
    Header може бути None, якщо заголовка немає.
    """
    header: Optional[List[str]] = None
    entries: List[Tuple[str, List[str]]] = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        first_row = True
        for row in reader:
            if not row:
                continue
            if first_row:
                first_row = False
                if row[0].strip().lower() == "key":
                    header = row
                    continue
            key_val = row[0].strip()
            entries.append((key_val, row))
    return header, entries


def split_key(key: str) -> Tuple[str, str]:
    """Повертає (prefix, suffix). Якщо немає '::', prefix="", suffix=key."""
    if "::" in key:
        p, s = key.split("::", 1)
        return p, s
    return "", key


def main():
    parser = argparse.ArgumentParser(description="Порівняння ключів двох CSV-файлів (колонка 'key').")
    parser.add_argument("a", nargs="?", help="Шлях до першого CSV-файлу")
    parser.add_argument("b", nargs="?", help="Шлях до другого CSV-файлу")
    parser.add_argument("--a", dest="a_named", help="Шлях до першого CSV-файлу (іменований)")
    parser.add_argument("--b", dest="b_named", help="Шлях до другого CSV-файлу (іменований)")
    args = parser.parse_args()

    path_a = args.a_named or args.a
    path_b = args.b_named or args.b

    # If not provided, open GUI dialogs to select files
    if (not path_a or not path_b) and filedialog is not None:
        start_dir = os.path.dirname(os.path.abspath(__file__))
        # Init tk root invisibly
        try:
            root = tk.Tk()
            root.withdraw()
        except Exception:
            root = None
        if not path_a:
            path_a = filedialog.askopenfilename(
                title="Оберіть перший CSV (A)",
                initialdir=start_dir,
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            ) or None
        if not path_b:
            path_b = filedialog.askopenfilename(
                title="Оберіть другий CSV (B)",
                initialdir=start_dir,
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            ) or None
        if root is not None:
            try:
                root.destroy()
            except Exception:
                pass

    if not path_a or not path_b:
        print("ERROR: Вкажіть два шляхи до CSV-файлів: fileA.csv fileB.csv (або скористайтесь діалогом)", file=sys.stderr)
        try:
            input("\nНатисніть Enter, щоб вийти...")
        except EOFError:
            pass
        sys.exit(2)

    path_a = os.path.abspath(path_a)
    path_b = os.path.abspath(path_b)

    if not os.path.isfile(path_a):
        print(f"ERROR: Файл не знайдено: {path_a}", file=sys.stderr)
        try:
            input("\nНатисніть Enter, щоб вийти...")
        except EOFError:
            pass
        sys.exit(2)
    if not os.path.isfile(path_b):
        print(f"ERROR: Файл не знайдено: {path_b}", file=sys.stderr)
        try:
            input("\nНатисніть Enter, щоб вийти...")
        except EOFError:
            pass
        sys.exit(2)

    header_a, entries_a = read_csv_entries(path_a)
    header_b, entries_b = read_csv_entries(path_b)
    keys_a: Set[str] = {k for k, _ in entries_a if k}
    keys_b: Set[str] = {k for k, _ in entries_b if k}
    rows_a = len([1 for k, _ in entries_a if k])
    rows_b = len([1 for k, _ in entries_b if k])

    # Побудувати мапи за суфіксом ключа (частина після '::')
    a_by_suffix: Dict[str, Tuple[str, List[str]]] = {}
    for k, row in entries_a:
        if not k:
            continue
        _, s = split_key(k)
        if s not in a_by_suffix:
            a_by_suffix[s] = (k, row)
    b_by_suffix: Dict[str, Tuple[str, List[str]]] = {}
    for k, row in entries_b:
        if not k:
            continue
        _, s = split_key(k)
        if s not in b_by_suffix:
            b_by_suffix[s] = (k, row)

    # Порівнювати за суфіксами: збіг — якщо суфікс однаковий, навіть якщо префікси різні
    suffixes_a = set(a_by_suffix.keys())
    suffixes_b = set(b_by_suffix.keys())
    common_suffixes = sorted(suffixes_a & suffixes_b)
    only_suffix_in_a = sorted(suffixes_a - suffixes_b)
    only_suffix_in_b = sorted(suffixes_b - suffixes_a)

    print("=== Порівняння ключів CSV ===")
    print(f"A: {path_a}")
    print(f"B: {path_b}")
    print(f"Рядків (A): {rows_a}, унікальних ключів (A): {len(keys_a)}")
    print(f"Рядків (B): {rows_b}, унікальних ключів (B): {len(keys_b)}")
    print("")

    print(f"Ключі лише у A (за суфіксами) ({len(only_suffix_in_a)}):")
    for s in only_suffix_in_a:
        print(a_by_suffix[s][0])
    print("")

    print(f"Ключі лише у B (за суфіксами) ({len(only_suffix_in_b)}):")
    for s in only_suffix_in_b:
        print(b_by_suffix[s][0])
    print("")

    print(f"Спільні ключі (перетин за суфіксами) — довідково ({len(common_suffixes)}):")
    # За замовчуванням не друкуємо весь перелік, щоб не засмічувати вивід.
    # Розкоментуйте, щоб побачити всі спільні ключі:
    # for k in in_both:
    #     print(k)

    # Записати рядки у окремі файли
    a_base = os.path.splitext(os.path.basename(path_a))[0]
    b_base = os.path.splitext(os.path.basename(path_b))[0]
    out_dir = os.path.dirname(os.path.abspath(__file__))
    out_common = os.path.join(out_dir, f"Common {a_base} {b_base}.csv")
    out_a_only = os.path.join(out_dir, f"Only {a_base}.csv")
    out_b_only = os.path.join(out_dir, f"Only {b_base}.csv")

    def write_only(path_out: str, header: Optional[List[str]], entries: List[Tuple[str, List[str]]], allowed_suffixes: Set[str]):
        with open(path_out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if header is not None:
                w.writerow(header)
            for key, row in entries:
                if not key:
                    continue
                _, s = split_key(key)
                if s in allowed_suffixes:
                    w.writerow(row)

    def write_common_with_b_prefix(path_out: str, header: Optional[List[str]]):
        with open(path_out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if header is not None:
                w.writerow(header)
            # Порядок як у A; ключ беремо ПОВНІСТЮ з B (і префікс, і суфікс від другого файлу)
            for key_a, row_a in entries_a:
                if not key_a:
                    continue
                _, s = split_key(key_a)
                if s in b_by_suffix:
                    key_b, _ = b_by_suffix[s]
                    new_key = key_b
                    # замінити першу колонку у рядку A на new_key
                    out_row = list(row_a)
                    if out_row:
                        out_row[0] = new_key
                    w.writerow(out_row)

    # 1) Спільні рядки (порядок як у A), ключ береться з префіксом із B при наявності
    write_common_with_b_prefix(out_common, header_a)
    # 2) Лише у A (за суфіксами)
    write_only(out_a_only, header_a, entries_a, set(only_suffix_in_a))
    # 3) Лише у B (за суфіксами)
    write_only(out_b_only, header_b, entries_b, set(only_suffix_in_b))

    print("")
    print("Створені файли:")
    print(f"  1) Спільні (за порядком A) -> {out_common}")
    print(f"  2) Лише у A               -> {out_a_only}")
    print(f"  3) Лише у B               -> {out_b_only}")

    # Pause at the end so the window doesn't close immediately
    try:
        input("\nГотово. Натисніть Enter, щоб закрити...")
    except EOFError:
        pass


if __name__ == "__main__":
    main()


