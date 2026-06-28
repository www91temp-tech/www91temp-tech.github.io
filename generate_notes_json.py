#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate_notes_json.py
------------------------------------------------------------
自動掃描 repo 中的科目資料夾，產生（或更新）notes.json。

用法：
    python3 generate_notes_json.py

放置位置：
    建議放在 repo 根目錄，與 index.html / notes.json 同層。
    執行後會直接更新同層的 notes.json。

運作邏輯：
    1. 掃描 SUBJECT_FOLDERS 清單中列出的資料夾（白名單，避免誤掃 .git 等資料夾）。
    2. 每個資料夾底下找出所有 .html 檔案（不含 index.html）。
    3. 檔名自動轉換成標題（底線換空格、去掉科目前綴、去掉副檔名）。
    4. 如果舊 notes.json 裡，同一個 file 已經有手動寫過的 title，
       會「保留舊標題」，不會被自動產生的標題覆蓋。
    5. 找到資料夾清單裡不在 CATEGORY_META 設定中的新資料夾，
       會自動建立一個分類（用預設 label），並在輸出時提醒你手動補上 emoji/中文名稱。
    6. 輸出排序後的 notes.json。

若要新增一個科目資料夾，只需要：
    (a) 在 repo 建立該資料夾並放入 .html 筆記
    (b) 在下方 CATEGORY_META 補上對應的 label（可選，沒補也會自動生成一個暫用的）
    (c) 重新執行這個 script
------------------------------------------------------------
"""

import json
import os
import re
import sys

# ============================================================
# 設定區：你可以依需求修改這裡
# ============================================================

# repo 根目錄路徑。若 script 跟 notes.json 放在同一層，保持 '.' 即可。
REPO_ROOT = '.'

# 輸出的 notes.json 路徑
OUTPUT_PATH = os.path.join(REPO_ROOT, 'notes.json')

# 白名單：只掃描這些資料夾。
# key   = 資料夾名稱（必須跟實際資料夾名稱一致，大小寫需相符）
# value = 顯示用的分類 label（含 emoji），會直接用在首頁標題上
CATEGORY_META = {
    'Biochemistry': '🧪 生化 (Biochemistry)',
    'Biology':      '🧬 普生 (Biology)',
    'OrgChem':      '⚗️ 有機化 (OrgChem)',
    # 新增科目時，在這裡加一行即可，例如：
    # 'Physics':    '⚛️ 物理 (Physics)',
}

# 分類顯示順序：不在這個清單裡的資料夾，會自動排在後面
CATEGORY_ORDER = list(CATEGORY_META.keys())

# 忽略的檔名（不分大小寫）
IGNORE_FILES = {'index.html'}

# ============================================================
# 核心邏輯
# ============================================================


def load_existing_titles(output_path):
    """
    讀取舊的 notes.json，建立 {(folder, file): title} 的對照表，
    讓手動修改過的標題不會被自動產生的標題覆蓋掉。
    """
    existing = {}
    if not os.path.exists(output_path):
        return existing

    try:
        with open(output_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f'⚠️  無法讀取舊的 notes.json（{e}），將視為從零開始建立。')
        return existing

    for category in data.get('categories', []):
        folder = category.get('folder', '')
        for note in category.get('notes', []):
            file_name = note.get('file')
            title = note.get('title')
            if file_name and title:
                existing[(folder, file_name)] = title

    return existing


def filename_to_title(filename, folder_key):
    """
    把檔名轉換成預設標題：
    - 去掉副檔名
    - 去掉開頭的「資料夾名稱_」前綴（例如 Biology_Ch42_xxx -> Ch42_xxx）
    - 底線換成空格
    """
    name = filename
    if name.lower().endswith('.html'):
        name = name[:-5]

    prefix = folder_key + '_'
    if name.startswith(prefix):
        name = name[len(prefix):]

    name = name.replace('_', ' ').strip()
    return name if name else filename


def scan_folder(folder_path, folder_key, existing_titles):
    """
    掃描單一資料夾，回傳該分類底下的 notes 清單（已排序）。
    """
    notes = []

    if not os.path.isdir(folder_path):
        return notes

    for entry in sorted(os.listdir(folder_path)):
        full_path = os.path.join(folder_path, entry)

        if not os.path.isfile(full_path):
            continue
        if not entry.lower().endswith('.html'):
            continue
        if entry.lower() in IGNORE_FILES:
            continue

        # 優先使用舊 notes.json 裡手動寫過的標題
        title = existing_titles.get((folder_key, entry))
        if title is None:
            title = filename_to_title(entry, folder_key)

        notes.append({'title': title, 'file': entry})

    # 依檔名排序（章節數字通常會自然排好）
    notes.sort(key=lambda n: n['file'].lower())
    return notes


def discover_folders(repo_root):
    """
    找出 repo_root 底下所有可能是「科目資料夾」的目錄。
    規則：忽略以 . 開頭的資料夾（.git, .github 等），
    且只算進有至少一個 .html 檔案的資料夾，避免誤掃無關目錄。
    """
    discovered = []
    try:
        entries = sorted(os.listdir(repo_root))
    except OSError as e:
        print(f'❌ 無法讀取目錄 {repo_root}：{e}')
        return discovered

    for entry in entries:
        full_path = os.path.join(repo_root, entry)
        if not os.path.isdir(full_path):
            continue
        if entry.startswith('.'):
            continue

        has_html = any(
            f.lower().endswith('.html') and f.lower() not in IGNORE_FILES
            for f in os.listdir(full_path)
            if os.path.isfile(os.path.join(full_path, f))
        )
        if has_html:
            discovered.append(entry)

    return discovered


def build_label_for_unknown_folder(folder_name):
    """
    對於不在 CATEGORY_META 裡設定的資料夾，產生一個暫用的 label，
    並印出提醒，讓使用者知道要手動補上更好的中文名稱/emoji。
    """
    return f'📁 {folder_name}'


def main():
    existing_titles = load_existing_titles(OUTPUT_PATH)

    discovered_folders = discover_folders(REPO_ROOT)

    # 排序：先按 CATEGORY_ORDER 的順序，未列在裡面的資料夾依字母排序放在後面
    known = [f for f in CATEGORY_ORDER if f in discovered_folders]
    unknown = sorted(f for f in discovered_folders if f not in CATEGORY_ORDER)
    ordered_folders = known + unknown

    categories = []
    new_folder_warnings = []

    for folder_key in ordered_folders:
        folder_path = os.path.join(REPO_ROOT, folder_key)
        notes = scan_folder(folder_path, folder_key, existing_titles)

        if not notes:
            # 資料夾存在但沒有任何 html 檔，略過（避免首頁出現空分類）
            continue

        if folder_key in CATEGORY_META:
            label = CATEGORY_META[folder_key]
        else:
            label = build_label_for_unknown_folder(folder_key)
            new_folder_warnings.append(folder_key)

        categories.append({
            'key': folder_key,
            'label': label,
            'folder': folder_key,
            'notes': notes,
        })

    output = {'categories': categories}

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write('\n')

    # ---- 輸出結果摘要 ----
    total_notes = sum(len(c['notes']) for c in categories)
    print(f'✅ 已更新 {OUTPUT_PATH}')
    print(f'   共 {len(categories)} 個分類，{total_notes} 篇筆記：\n')

    for c in categories:
        print(f"   {c['label']:<28} {len(c['notes'])} 篇")

    if new_folder_warnings:
        print('\n⚠️  發現新資料夾，已用暫用名稱建立分類，建議手動補上中文名稱/emoji：')
        for folder in new_folder_warnings:
            print(f"   - 在 CATEGORY_META 加入：'{folder}': '🆕 {folder}',")
        print('   （補上後重新執行一次本 script，標題即會更新）')


if __name__ == '__main__':
    sys.exit(main() or 0)
