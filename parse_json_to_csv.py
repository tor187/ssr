#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_json_to_csv.py
Парсить JSON-файли у вказаних теках, витягує SourceString з передбачених блоків
і записує CSV зі стовпчиками: key, source, Translation, context.

Останні зміни:
- прибрано обробку EmotionalState у рядках діалогу;
- адреса (шлях після UnleashedPrototype/Content або знайдений ObjectPath) переміщена
  на перше місце в context для всіх типів рядків.
- збережено попередній функціонал: StringTable-збір, DataTable, UserDefinedEnum,
  Script EX_TextConst, властивості на одному рівні, уникнення дублікатів, drag&drop, чекання Enter.
"""

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog
except Exception:
    tk = None
    filedialog = None

# ---------------- Утиліти ----------------
def sorted_walk(top):
    for root, dirs, files in os.walk(top):
        dirs.sort(key=lambda s: s.lower())
        files.sort(key=lambda s: s.lower())
        yield root, dirs, files

def find_source_nodes(obj, parent=None, parent_key=None, ancestry=None):
    if ancestry is None:
        ancestry = []
    if isinstance(obj, dict):
        # 1. Якщо є "Expression" з EX_TextConst, беремо всю "Value"
        expr = obj.get('Expression')
        if (
            isinstance(expr, dict) and expr.get('Inst') == 'EX_TextConst'
            and isinstance(expr.get('Value'), dict)
            and all(k in expr['Value'] for k in ("SourceString", "KeyString", "Namespace"))
        ):
            yield expr['Value'], expr, 'Value', ancestry.copy()
        # 2. EX_TextConst вузол безпосередньо
        elif (
            obj.get("Inst") == "EX_TextConst" and isinstance(obj.get("Value"), dict)
            and all(k in obj["Value"] for k in ("SourceString", "KeyString", "Namespace"))
        ):
            yield obj["Value"], obj, "Value", ancestry.copy()
        # !!! ОНОВЛЕНО: не yield окремо SourceString, якщо parent має KeyString і Namespace (це частина EX_TextConst)
        elif (
            "SourceString" in obj and parent
            and isinstance(parent, dict)
            and ("KeyString" in parent and "Namespace" in parent)
        ):
            pass
        # !!! Ще суворіше: не yield SourceString якщо ancestry (на всіх рівнях крім self) містить dict з KeyString і Namespace
        elif (
            "SourceString" in obj
            and any(
                isinstance(a_obj, dict)
                and "KeyString" in a_obj and "Namespace" in a_obj
                for a_obj, _ in ancestry[:-1]
            )
        ):
            pass  # Пропускаємо такі вузли!
        # !!! Абсолютний фільтр: не yield якщо parent EX_StringConst
        elif (
            "SourceString" in obj and parent
            and isinstance(parent, dict)
            and parent.get("Inst") == "EX_StringConst"
        ):
            pass
        # 3. SourceString+KeyString+Namespace одночасно (але це не Value EX_TextConst)
        elif (
            "SourceString" in obj and "KeyString" in obj and "Namespace" in obj
        ):
            yield obj, parent, parent_key, ancestry.copy()
        # 4. Просто SourceString як fallback
        elif "SourceString" in obj:
            yield obj, parent, parent_key, ancestry.copy()
        for k, v in obj.items():
            new_ancestry = ancestry.copy()
            new_ancestry.append((obj, k))
            yield from find_source_nodes(v, parent=obj, parent_key=k, ancestry=new_ancestry)
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            new_ancestry = ancestry.copy()
            new_ancestry.append((obj, idx))
            yield from find_source_nodes(item, parent=obj, parent_key=idx, ancestry=new_ancestry)

def find_line_number(original_text, value, start_pos=0):
    try:
        json_val = json.dumps(value)
    except Exception:
        json_val = '"' + str(value).replace('"', '\\"') + '"'
    pattern = re.escape('"SourceString"') + r'\s*:\s*' + re.escape(json_val)
    m = re.search(pattern, original_text[start_pos:], flags=re.MULTILINE)
    if not m:
        return None, None
    match_start = start_pos + m.start()
    line_no = original_text.count("\n", 0, match_start) + 1
    return line_no, match_start

def relative_after_markers(path, markers=("UnleashedPrototype", "Content")):
    parts = Path(path).as_posix().split("/")
    lower_parts = [p.lower() for p in parts]
    for marker in markers:
        marker_lower = marker.lower()
        if marker_lower in lower_parts:
            i = lower_parts.index(marker_lower)
            return "/".join(parts[i+1:]) if i+1 < len(parts) else ""
    return Path(path).as_posix()

def extract_table_short_from_tableid(tableid_value):
    if not tableid_value or not isinstance(tableid_value, str):
        return None
    if "." in tableid_value:
        return tableid_value.rsplit(".", 1)[-1]
    return None

def find_tableid_in_ancestry(node, ancestry):
    if isinstance(node, dict) and "TableId" in node and isinstance(node.get("TableId"), str):
        return node.get("TableId")
    for obj, _ in reversed(ancestry):
        if isinstance(obj, dict) and "TableId" in obj and isinstance(obj.get("TableId"), str):
            return obj.get("TableId")
    return None

def extract_string_from_maybe_obj(obj):
    # Рекурсивно/ітеративно занурюється по "Value", поки не string
    while isinstance(obj, dict) and "Value" in obj:
        obj = obj["Value"]
    return obj if isinstance(obj, str) else None

def find_property_name_in_ancestry(ancestry):
    for obj, _ in reversed(ancestry):
        if isinstance(obj, dict):
            prop = obj.get("Property")
            if isinstance(prop, dict) and "Name" in prop and isinstance(prop.get("Name"), str):
                return prop.get("Name")
    return None

def find_ancestor_value(ancestry, key_name):
    for obj, _ in reversed(ancestry):
        if isinstance(obj, dict) and key_name in obj:
            return obj.get(key_name)
    return None

# ключі: пріоритети — keystring -> selectedkeyname -> selectedkey -> key -> інші з 'key'
def find_key_candidate_in_dict(dct):
    if not isinstance(dct, dict):
        return None, None
    keys = list(dct.keys())
    lower_map = {k.lower(): k for k in keys}
    if "keystring" in lower_map:
        realk = lower_map["keystring"]
        return realk, dct.get(realk)
    if "selectedkeyname" in lower_map:
        realk = lower_map["selectedkeyname"]
        return realk, dct.get(realk)
    if "selectedkey" in lower_map:
        realk = lower_map["selectedkey"]
        return realk, dct.get(realk)
    if "key" in lower_map:
        realk = lower_map["key"]
        return realk, dct.get(realk)
    for lk, orig in lower_map.items():
        if "key" in lk:
            return orig, dct.get(orig)
    return None, None

def get_key_from_context(node, parent, ancestry):
    if isinstance(node, dict):
        fname, val = find_key_candidate_in_dict(node)
        if fname and val is not None:
            sval = extract_string_from_maybe_obj(val)
            if sval:
                return sval
    if isinstance(parent, dict):
        fname, val = find_key_candidate_in_dict(parent)
        if fname and val is not None:
            sval = extract_string_from_maybe_obj(val)
            if sval:
                return sval
    for anc_obj, _ in reversed(ancestry):
        if isinstance(anc_obj, dict):
            fname, val = find_key_candidate_in_dict(anc_obj)
            if fname and val is not None:
                sval = extract_string_from_maybe_obj(val)
                if sval:
                    return sval
    return None

# знаходимо ObjectPath у предках (наприклад у MissionTree або Template.Owner...)
def find_objectpath_in_ancestry(ancestry):
    for obj, _ in reversed(ancestry):
        if not isinstance(obj, dict):
            continue
        for candidate in ("ObjectPath", "Owner", "ObjectName"):
            val = obj.get(candidate)
            if isinstance(val, str) and "UnleashedPrototype" in val:
                return format_objectpath(val)
        for v in obj.values():
            if isinstance(v, dict) and "ObjectPath" in v and isinstance(v.get("ObjectPath"), str) and "UnleashedPrototype" in v.get("ObjectPath"):
                return format_objectpath(v.get("ObjectPath"))
    return None

def format_objectpath(raw):
    p = str(raw).replace("\\", "/")
    parts = p.split("/")
    lower = [x.lower() for x in parts]
    if "unleashedprototype" in lower:
        i = lower.index("unleashedprototype")
        rel = "/".join(parts[i+1:])
    else:
        rel = "/".join(parts)
    rel = re.sub(r'\.\d+$', '.json', rel)
    return rel

def extract_speaker_name(speaker_obj):
    if isinstance(speaker_obj, str):
        s = speaker_obj
    elif isinstance(speaker_obj, dict):
        s = speaker_obj.get("AssetPathName") or speaker_obj.get("ObjectPath") or ""
    else:
        s = ""
    if not s:
        return None
    last = s.replace("\\", "/").split("/")[-1]
    if "." in last:
        return last.rsplit(".", 1)[-1]
    return last

# ---------------- StringTable збір ----------------
def collect_stringtables(roots):
    map_key_to_ns = {}
    for root in roots:
        for dirpath, dirs, files in sorted_walk(root):
            for fname in files:
                if not fname.lower().endswith(".json"):
                    continue
                file_path = os.path.join(dirpath, fname)
                try:
                    with open(file_path, "r", encoding="utf-8-sig") as f:
                        txt = f.read()
                        data = json.loads(txt)
                except Exception:
                    continue
                stack = [data] if isinstance(data, (dict, list)) else []
                while stack:
                    nd = stack.pop()
                    if isinstance(nd, dict):
                        t = nd.get("Type")
                        if t == "StringTable" and "StringTable" in nd and isinstance(nd.get("StringTable"), dict):
                            st = nd.get("StringTable")
                            ns = st.get("TableNamespace") if isinstance(st.get("TableNamespace"), str) else None
                            keysmap = st.get("KeysToEntries") if isinstance(st.get("KeysToEntries"), dict) else {}
                            if ns and isinstance(keysmap, dict):
                                for k in keysmap.keys():
                                    if k not in map_key_to_ns:
                                        map_key_to_ns[k] = ns
                        if "StringTable" in nd and isinstance(nd.get("StringTable"), dict):
                            st = nd.get("StringTable")
                            ns = st.get("TableNamespace") if isinstance(st.get("TableNamespace"), str) else None
                            keysmap = st.get("KeysToEntries") if isinstance(st.get("KeysToEntries"), dict) else {}
                            if ns and isinstance(keysmap, dict):
                                for k in keysmap.keys():
                                    if k not in map_key_to_ns:
                                        map_key_to_ns[k] = ns
                        for v in nd.values():
                            if isinstance(v, (dict, list)):
                                stack.append(v)
                    elif isinstance(nd, list):
                        for it in nd:
                            if isinstance(it, (dict, list)):
                                stack.append(it)
    return map_key_to_ns

def match_stringtable_namespace_for_key(final_key, key_to_ns):
    if not final_key:
        return None, None
    for k, ns in key_to_ns.items():
        if final_key == k or final_key.endswith("." + k) or final_key.endswith("::" + k) or final_key.endswith(":" + k):
            return ns, k
    return None, None

def make_localization_key(table_id: str, key: str) -> str:
    """
    Генерує універсальний ключ для локалізації: {TableIdLastSegment}::{Key}
    """
    if not table_id or not isinstance(table_id, str) or not key:
        return None
    last_segment = table_id.split('.')[-1]
    return f"{last_segment}::{key}"

# ---------------- Обробники вузлів ----------------
def handle_dialog_line(node, parent, parent_key, ancestry, file_path, dialog_ancestor):
    """
    Обробляє DialogueText-підвузол у DialogAsset Lines.
    Адреса буде на першому місці в context; EmotionalState не обробляється.
    """
    if not isinstance(node, dict):
        return None, None, None, None
    key_candidate = get_key_from_context(node, parent, ancestry)
    if not key_candidate:
        return None, None, None, None
    source = node.get("SourceString", "")
    localized = node.get("LocalizedString", "") or ""
    # Використовувати локалізований текст, якщо він є
    effective_source = localized if localized else source
    # speaker
    speaker_name = None
    if isinstance(parent, dict) and "Speaker" in parent:
        speaker_name = extract_speaker_name(parent.get("Speaker"))
    # dialog name
    dialog_name = dialog_ancestor.get("Name") if isinstance(dialog_ancestor, dict) else "null"
    speaker_field = speaker_name if speaker_name else "null"
    objpath = find_objectpath_in_ancestry(ancestry)
    relpath = objpath if objpath else relative_after_markers(file_path, markers=("UnleashedPrototype", "Content"))
    # Префіксувати Namespace, якщо він є у вузлі
    ns_val = node.get("Namespace") if isinstance(node.get("Namespace"), str) else None
    final_key = f"{ns_val}::{key_candidate}" if ns_val else key_candidate
    # Адреса на перше місце
    context = "\n".join([
        relpath if relpath else file_path,
        f"Name: {dialog_name}",
        f"Speaker: {speaker_field}",
        "DialogueText",
    ])
    return final_key, effective_source, "", context

def handle_property_node(node, parent, parent_key, ancestry, file_path):
    if not isinstance(node, dict):
        return None, None, None, None
    key_candidate = get_key_from_context(node, parent, ancestry)
    if not key_candidate:
        return None, None, None, None
    # Спроба сформувати ключ через TableId, якщо доступний
    tableid_val = find_tableid_in_ancestry(node, ancestry)
    if isinstance(tableid_val, str) and tableid_val:
        final_key = make_localization_key(tableid_val, key_candidate)
    else:
        ns_val = node.get("Namespace")
        if isinstance(ns_val, str) and ns_val:
            final_key = f"{ns_val}::{key_candidate}"
        else:
            final_key = key_candidate
    source = node.get("SourceString", "")
    localized = node.get("LocalizedString", "")
    # Використовувати локалізований текст, якщо він є
    effective_source = localized if localized else source
    top_name = find_ancestor_value(ancestry, "Name") or find_ancestor_value(ancestry, "name") or "null"
    prop_name = parent_key if isinstance(parent_key, str) else "null"
    objpath = find_objectpath_in_ancestry(ancestry)
    relpath = objpath if objpath else relative_after_markers(file_path, markers=("UnleashedPrototype", "Content"))
    # Адреса на перше місце в контексті (без Localized)
    context = "\n".join([relpath if relpath else file_path, f"Name: {top_name}", str(prop_name)])
    return final_key, effective_source, "", context

def handle_user_defined_enum(node, parent, parent_key, ancestry, file_path):
    if not isinstance(node, dict):
        return None, None, None, None
    hash_key = node.get("Key") or node.get("key")
    source = node.get("SourceString", "")
    localized = node.get("LocalizedString", "") or ""
    # Використовувати локалізований текст, якщо він є
    effective_source = localized if localized else source
    enumerator_name = None
    if isinstance(parent, dict) and "Key" in parent and isinstance(parent.get("Key"), str):
        enumerator_name = parent.get("Key")
    enum_ancestor = None
    for anc_obj, _ in reversed(ancestry):
        if isinstance(anc_obj, dict) and anc_obj.get("Type") == "UserDefinedEnum":
            enum_ancestor = anc_obj
            break
    enum_name = enum_ancestor.get("Name") if enum_ancestor is not None else None
    context_parts = []
    objpath = find_objectpath_in_ancestry(ancestry)
    relpath = objpath if objpath else relative_after_markers(file_path, markers=("UnleashedPrototype", "Content"))
    # Адреса на перше місце
    if relpath:
        context_parts.append(relpath)
    if enum_name:
        context_parts.append(f"Name: {enum_name}")
    if enumerator_name:
        context_parts.append(f"Key: {enumerator_name}")
    context = "\n".join(context_parts) if context_parts else (relpath if relpath else file_path)
    return hash_key, effective_source, "", context

def handle_data_table(node, parent, parent_key, ancestry, file_path, data_table_ancestor):
    if not isinstance(node, dict):
        return None, None, None, None
    full_key = node.get("Key") or node.get("key")
    source = node.get("SourceString", "")
    localized = node.get("LocalizedString", "") or ""
    # Використовувати локалізований текст, якщо він є
    effective_source = localized if localized else source
    # Префікс ключа: пріоритет — локальний Namespace у полі, інакше коротке ім'я з TableId у предках
    inline_ns = node.get("Namespace") if isinstance(node.get("Namespace"), str) else None
    if inline_ns:
        prefix = f"{inline_ns}::"
    else:
        tableid_val = find_tableid_in_ancestry(node, ancestry)
        table_short = extract_table_short_from_tableid(tableid_val) if tableid_val else None
        prefix = f"{table_short}::" if table_short else ""
    table_name = data_table_ancestor.get("Name") if isinstance(data_table_ancestor, dict) else None
    row_name = None
    for i, (obj, key_in_parent) in enumerate(ancestry):
        if key_in_parent == "Rows":
            if i+1 < len(ancestry):
                _, row_key = ancestry[i+1]
                row_name = row_key
            break
    field_name = parent_key if isinstance(parent_key, str) else None
    context_parts = []
    objpath = find_objectpath_in_ancestry(ancestry)
    relpath = objpath if objpath else relative_after_markers(file_path, markers=("UnleashedPrototype", "Content"))
    # Адреса на перше місце
    if relpath:
        context_parts.append(relpath)
    first_parts = []
    if table_name:
        first_parts.append(table_name)
    if row_name:
        first_parts.append(str(row_name))
    if field_name:
        first_parts.append(field_name)
    if first_parts:
        context_parts.append(", ".join(first_parts))
    context = "\n".join(context_parts)
    final_key = (prefix + full_key) if full_key else None
    return final_key, effective_source, "", context

def handle_script_textconst(node, parent, parent_key, ancestry, file_path):
    # Універсально дістає Value.SourceString.Value, Namespace.Value, KeyString.Value (чи просто рядок)
    if not isinstance(node, dict):
        return None, None, None, None
    value_block = node.get('Value') if 'Value' in node else node
    # source
    src_str = value_block.get('SourceString') if isinstance(value_block, dict) else None
    source_val = extract_string_from_maybe_obj(src_str)
    if isinstance(source_val, dict):
        deeper = source_val.get('Value')
        if isinstance(deeper, str):
            source_val = deeper
        else:
            source_val = ""
    # ключ
    ns = value_block.get('Namespace') if isinstance(value_block, dict) else None
    keystr = value_block.get('KeyString') if isinstance(value_block, dict) else None
    ns_val = extract_string_from_maybe_obj(ns)
    if isinstance(ns_val, dict):
        deeper = ns_val.get('Value')
        if isinstance(deeper, str):
            ns_val = deeper
        else:
            ns_val = ""
    key_val = extract_string_from_maybe_obj(keystr)
    if isinstance(key_val, dict):
        deeper = key_val.get('Value')
        if isinstance(deeper, str):
            key_val = deeper
        else:
            key_val = ""
    # Додаємо Namespace якщо є і не порожній
    if ns_val:
        final_key = f"{ns_val}::{key_val}"
    else:
        final_key = key_val
    if source_val is None:
        source_val = extract_string_from_maybe_obj(node.get('SourceString')) or ""
        if isinstance(source_val, dict):
            deeper = source_val.get('Value')
            source_val = deeper if isinstance(deeper, str) else ""
    prop_name = find_property_name_in_ancestry(ancestry)
    name_field = prop_name if prop_name is not None else "null"
    objpath = find_objectpath_in_ancestry(ancestry)
    relpath = objpath if objpath else relative_after_markers(file_path, markers=("UnleashedPrototype", "Content"))
    # Без Localized у контексті
    context = "\n".join([relpath if relpath else file_path, f"Name: {name_field}"])
    return final_key, source_val, "", context

def get_text(src):
    if isinstance(src, str):
        return src
    if isinstance(src, dict) and 'Value' in src and isinstance(src['Value'], str):
        return src['Value']
    return None

# ---------------- Файл-обробка ----------------
def process_file(path, writer, key_to_ns, emitted_keys):
    with open(path, "r", encoding="utf-8-sig") as f:
        original_text = f.read()
    try:
        data = json.loads(original_text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"ERROR: Не вдалося розпарсити JSON у файлі {path}: {e}")
    search_start_pos = 0
    for node, parent, parent_key, ancestry in find_source_nodes(data):
        dialog_ancestor = None
        data_table_ancestor = None
        user_enum_ancestor = None
        for anc_obj, _ in reversed(ancestry):
            if isinstance(anc_obj, dict):
                t = anc_obj.get("Type")
                if t == "DialogAsset" and dialog_ancestor is None:
                    dialog_ancestor = anc_obj
                if t == "DataTable" and data_table_ancestor is None:
                    data_table_ancestor = anc_obj
                if t == "UserDefinedEnum" and user_enum_ancestor is None:
                    user_enum_ancestor = anc_obj

        # Визначаємо, чи вузол в контексті EX_TextConst
        in_textconst_context = (
            (isinstance(node, dict) and ("KeyString" in node and "Namespace" in node))
            or any(
                isinstance(a_obj, dict) and ("KeyString" in a_obj and "Namespace" in a_obj)
                for a_obj, _ in ancestry
            )
        )

        # Якщо ми в межах DialogAsset, обробляємо як діалогну лінію (має пріоритет)
        if dialog_ancestor is not None:
            key, source, translation, context = handle_dialog_line(node, parent, parent_key, ancestry, path, dialog_ancestor)
            src_val = get_text(source)
            if key and src_val is not None:
                final_key = key
                if "::" not in final_key:
                    ns, matched = match_stringtable_namespace_for_key(final_key, key_to_ns)
                    if ns:
                        final_key = f"{ns}::{matched}"
                if final_key not in emitted_keys:
                    writer.writerow([final_key, src_val, translation, context])
                    emitted_keys.add(final_key)
                _, match_pos = find_line_number(original_text, node.get("SourceString", ""), start_pos=search_start_pos)
                if match_pos is not None:
                    search_start_pos = match_pos + 1
                continue
            else:
                continue

        # property-like (DisplayName, DeathMenuText, SelectedKeyName тощо)
        # Пропускаємо, якщо це EX_TextConst-контекст або ми всередині DataTable
        if not in_textconst_context and data_table_ancestor is None:
            key_prop, source_prop, trans_prop, ctx_prop = handle_property_node(node, parent, parent_key, ancestry, path)
            src_val = get_text(source_prop)
            if key_prop and src_val is not None:
                final_key = key_prop
                if "::" not in final_key:
                    ns, matched = match_stringtable_namespace_for_key(final_key, key_to_ns)
                    if ns:
                        final_key = f"{ns}::{matched}"
                if final_key not in emitted_keys:
                    writer.writerow([final_key, src_val, trans_prop, ctx_prop])
                    emitted_keys.add(final_key)
                _, match_pos = find_line_number(original_text, node.get("SourceString", ""), start_pos=search_start_pos)
                if match_pos is not None:
                    search_start_pos = match_pos + 1
                continue

        # DataTable
        if data_table_ancestor is not None:
            key, source, translation, context = handle_data_table(node, parent, parent_key, ancestry, path, data_table_ancestor)
            src_val = get_text(source)
            if not key or src_val is None:
                line_no, _ = find_line_number(original_text, node.get("SourceString", ""), start_pos=search_start_pos)
                if line_no is None:
                    raise RuntimeError(f"UNEXPECTED: у файлі {path} знайдено DataTable-елемент без key (не вдалось знайти номер рядка)")
                else:
                    raise RuntimeError(f"UNEXPECTED: у файлі {path} знайдено DataTable-елемент без key (рядок {line_no})")
            ns, matched = match_stringtable_namespace_for_key(key, key_to_ns)
            final_key = f"{ns}::{matched}" if ns else key
            if final_key not in emitted_keys:
                writer.writerow([final_key, src_val, translation, context])
                emitted_keys.add(final_key)
            _, match_pos = find_line_number(original_text, node.get("SourceString", ""), start_pos=search_start_pos)
            if match_pos is not None:
                search_start_pos = match_pos + 1
            continue

        # UserDefinedEnum
        if user_enum_ancestor is not None:
            key, source, translation, context = handle_user_defined_enum(node, parent, parent_key, ancestry, path)
            src_val = get_text(source)
            if not key or src_val is None:
                line_no, _ = find_line_number(original_text, node.get("SourceString", ""), start_pos=search_start_pos)
                if line_no is None:
                    raise RuntimeError(f"UNEXPECTED: у файлі {path} знайдено UserDefinedEnum-елемент без hash (не вдалось знайти номер рядка)")
                else:
                    raise RuntimeError(f"UNEXPECTED: у файлі {path} знайдено UserDefinedEnum-елемент без hash (рядок {line_no})")
            ns, matched = match_stringtable_namespace_for_key(key, key_to_ns)
            final_key = f"{ns}::{matched}" if ns else key
            if final_key not in emitted_keys:
                writer.writerow([final_key, src_val, translation, context])
                emitted_keys.add(final_key)
            _, match_pos = find_line_number(original_text, node.get("SourceString", ""), start_pos=search_start_pos)
            if match_pos is not None:
                search_start_pos = match_pos + 1
            continue

        # Script/EX_TextConst (універсальний)
        if isinstance(node, dict) and "SourceString" in node:
            key, source, translation, context = handle_script_textconst(node, parent, parent_key, ancestry, path)
            src_val = get_text(source)
            if key and src_val is not None:
                ns, matched = match_stringtable_namespace_for_key(key, key_to_ns)
                final_key = f"{ns}::{matched}" if ns else key
                # yield якщо final_key має :: або не порожній (залишаємо FastTravelFailReason), навіть якщо Namespace порожній
                if ("::" in str(final_key) or final_key) and final_key not in emitted_keys:
                    writer.writerow([final_key, src_val, translation, context])
                    emitted_keys.add(final_key)
                _, match_pos = find_line_number(original_text, node.get("SourceString", ""), start_pos=search_start_pos)
                if match_pos is not None:
                    search_start_pos = match_pos + 1
                continue
            else:
                continue
        # Непередбачений блок з SourceString — повідомляємо і зупиняємо
        line_no, _ = find_line_number(original_text, node.get("SourceString", ""), start_pos=search_start_pos)
        if line_no is None:
            raise RuntimeError(f"UNEXPECTED BLOCK: файл {path}, неочікуваний блок з SourceString (не вдалось знайти номер рядка)")
        else:
            raise RuntimeError(f"UNEXPECTED BLOCK: файл {path}, рядок {line_no})")

# ---------------- CLI / GUI ----------------
def choose_directory_with_gui():
    if tk is None or filedialog is None:
        return None
    root = tk.Tk()
    root.withdraw()
    directory = filedialog.askdirectory(title="Оберіть кореневу теку для обходу")
    root.destroy()
    return directory or None

def collect_roots_from_argv_or_gui(args):
    dropped_paths = [p for p in sys.argv[1:] if not p.startswith("-")] if len(sys.argv) > 1 else []
    roots = []
    if dropped_paths:
        for p in dropped_paths:
            p = os.path.abspath(p)
            if os.path.isdir(p):
                roots.append(p)
            elif os.path.isfile(p) and p.lower().endswith(".json"):
                roots.append(os.path.dirname(p))
    elif args.root:
        roots.append(os.path.abspath(args.root))
    else:
        gui_choice = choose_directory_with_gui()
        if gui_choice:
            roots.append(os.path.abspath(gui_choice))
        else:
            roots.append(os.path.abspath("."))
    return roots

def main():
    parser = argparse.ArgumentParser(description="Парсить JSON і витягує SourceString у CSV")
    parser.add_argument("--root", "-r", help="Коренева тека для обходу (як не вказано, можна перетягнути теку на файл)")
    parser.add_argument("--out", "-o", default="parsed.csv", help="Шлях до CSV файлу результату.")
    args, remaining = parser.parse_known_args()

    roots = collect_roots_from_argv_or_gui(args)

    # перший прохід: збір string-table
    key_to_ns = collect_stringtables(roots)

    out_csv = args.out
    had_error = False
    emitted_keys = set()
    try:
        with open(out_csv, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["key", "source", "Translation", "context"])
            for root in roots:
                if not os.path.isdir(root):
                    print(f"WARNING: шлях {root} не є текою, пропускаю.")
                    continue
                for dirpath, dirs, files in sorted_walk(root):
                    for fname in files:
                        if not fname.lower().endswith(".json"):
                            continue
                        file_path = os.path.join(dirpath, fname)
                        try:
                            process_file(file_path, writer, key_to_ns, emitted_keys)
                        except RuntimeError as rexc:
                            print(str(rexc), file=sys.stderr)
                            had_error = True
                            raise
            # Після обробки всіх файлів — додатково згенерувати рядки зі StringTable, якщо їх ще не було
            for root in roots:
                for dirpath, dirs, files in sorted_walk(root):
                    for fname in files:
                        if not fname.lower().endswith(".json"):
                            continue
                        file_path = os.path.join(dirpath, fname)
                        try:
                            with open(file_path, "r", encoding="utf-8-sig") as fjson:
                                txt = fjson.read()
                            data = json.loads(txt)
                        except Exception:
                            continue
                        stack = [data] if isinstance(data, (dict, list)) else []
                        while stack:
                            nd = stack.pop()
                            if isinstance(nd, dict) and "StringTable" in nd and isinstance(nd.get("StringTable"), dict):
                                st = nd.get("StringTable")
                                ns = st.get("TableNamespace") if isinstance(st.get("TableNamespace"), str) else None
                                keysmap = st.get("KeysToEntries") if isinstance(st.get("KeysToEntries"), dict) else {}
                                if isinstance(keysmap, dict):
                                    for k, v in keysmap.items():
                                        # Якщо немає TableNamespace — формуємо ключ без префікса
                                        final_key = f"{ns}::{k}" if ns else k
                                        if final_key in emitted_keys:
                                            continue
                                        source_val = v if isinstance(v, str) else str(v)
                                        relpath = relative_after_markers(file_path, markers=("UnleashedPrototype", "Content"))
                                        context = relpath if relpath else file_path
                                        writer.writerow([final_key, source_val, "", context])
                                        emitted_keys.add(final_key)
                            if isinstance(nd, dict):
                                for vv in nd.values():
                                    if isinstance(vv, (dict, list)):
                                        stack.append(vv)
                            elif isinstance(nd, list):
                                for it in nd:
                                    if isinstance(it, (dict, list)):
                                        stack.append(it)
    except Exception:
        pass

    print("\n--- Робота завершена ---")
    if had_error:
        print("Обробка припинена через помилку (див. вище).")
    else:
        print(f"Результат записано у: {os.path.abspath(out_csv)}")

    try:
        input("\nНатисніть Enter, щоб вийти...")
    except EOFError:
        pass

if __name__ == "__main__":
    main()
