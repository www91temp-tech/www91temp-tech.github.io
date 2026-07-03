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
    6. 「單頁應用型」資料夾（例如整個資料夾就是一個 index.html + 資料檔，
       不是「一篇筆記一個 html」的結構）改由 SINGLE_PAGE_FOLDERS 設定直接產生
       一筆固定的 note，不走 discover_folders / scan_folder 的掃描邏輯。
    7. 輸出排序後的 notes.json。

若要新增一個「多篇筆記」型科目資料夾，只需要：
    (a) 在 repo 建立該資料夾並放入 .html 筆記（每篇筆記一個檔案）
    (b) 在下方 CATEGORY_META 補上對應的 label（可選，沒補也會自動生成一個暫用的）
    (c) 重新執行這個 script

若要新增一個「單頁應用」型資料夾（例如查詢工具、單一互動頁面 + csv/json 資料）：
    (a) 在 repo 建立該資料夾，裡面放 index.html（以及資料檔，如 .csv）
    (b) 在下方 SINGLE_PAGE_FOLDERS 補上一筆設定
    (c) 重新執行這個 script
    這種資料夾「不會」被當成有多篇筆記的分類去掃描 .html 檔，
    而是直接產生一個連到該資料夾 index.html 的單一連結。
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
#
# 注意：這裡只放「多篇筆記」型的資料夾（一篇筆記一個 .html 檔）。
# 「單頁應用」型資料夾（例如 Anatomy_words）請改到下面的 SINGLE_PAGE_FOLDERS 設定，
# 不要放在這裡，否則會因為資料夾裡找不到「非 index.html」的 html 檔而被略過。
CATEGORY_META = {
    'Biochemistry': '🧪 生化 (Biochemistry)',
    'Biology':      '🧬 普生 (Biology)',
    'OrgChem':      '⚗️ 有機化 (OrgChem)',
    # 新增「多篇筆記」型科目時，在這裡加一行即可，例如：
    # 'Physics':    '⚛️ 物理 (Physics)',
}

# ------------------------------------------------------------
# 單頁應用型資料夾設定
#
# 這種資料夾的結構是「資料夾本身就是一個完整頁面」
# （例如 index.html 讀取同資料夾內的 .csv/.json 動態渲染成一個查詢工具），
# 而不是「資料夾裡每個 .html 各自代表一篇筆記」。
#
# 因此不透過 discover_folders() / scan_folder() 掃描，
# 而是直接依照這裡的設定產生一筆固定的 note，指向該資料夾的 index.html。
#
# key   = 資料夾名稱（需與實際資料夾名稱一致）
# value = dict，包含：
#     'label' : 分類顯示名稱（含 emoji）
#     'title' : 這個單頁應用在清單裡顯示的筆記標題
#     'file'  : 該資料夾內要連結的檔案，通常是 'index.html'
# ------------------------------------------------------------
SINGLE_PAGE_FOLDERS = {
    'Anatomy_words': {
        'label': '📋 解剖學字彙 (Anatomy_words)',
        'title': '解剖學字彙查詢',
        'file': 'index.html',
    },
    # 未來若有類似的單頁工具型資料夾，依樣加一筆即可，例如：
    # 'Physiology_quiz': {
    #     'label': '🩺 生理小考 (Physiology_quiz)',
    #     'title': '生理學自我測驗',
    #     'file': 'index.html',
    # },
}

# 分類顯示順序：不在這個清單裡的資料夾，會自動排在後面
CATEGORY_ORDER = list(CATEGORY_META.keys()) + list(SINGLE_PAGE_FOLDERS.keys())

# 忽略的檔名（不分大小寫）——僅套用於「多篇筆記」型資料夾的掃描邏輯
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
    掃描單一「多篇筆記」型資料夾，回傳該分類底下的 notes 清單（已排序）。
    注意：此函式不適用於 SINGLE_PAGE_FOLDERS 裡設定的資料夾。
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
    找出 repo_root 底下所有可能是「多篇筆記型科目資料夾」的目錄。
    規則：忽略以 . 開頭的資料夾（.git, .github 等），
    忽略已被登記為 SINGLE_PAGE_FOLDERS 的資料夾（那些走另一條路徑處理），
    且只算進有至少一個「非 index.html」.html 檔案的資料夾，避免誤掃無關目錄。
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
        if entry in SINGLE_PAGE_FOLDERS:
            # 單頁應用型資料夾不走這條掃描邏輯，避免因為只有 index.html
            # 而被誤判成「沒有筆記」略過。
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


def build_single_page_categories():
    """
    根據 SINGLE_PAGE_FOLDERS 設定，直接產生對應的分類清單，
    每個分類固定只有一筆 note，指向該資料夾的指定檔案（通常是 index.html）。
    若設定的資料夾或檔案實際不存在，會印出警告並略過，避免產生死連結。
    """
    categories = []

    for folder_key, meta in SINGLE_PAGE_FOLDERS.items():
        folder_path = os.path.join(REPO_ROOT, folder_key)
        file_name = meta.get('file', 'index.html')
        file_path = os.path.join(folder_path, file_name)

        if not os.path.isdir(folder_path):
            print(f"⚠️  SINGLE_PAGE_FOLDERS 設定了 '{folder_key}'，但找不到這個資料夾，已略過。")
            continue
        if not os.path.isfile(file_path):
            print(f"⚠️  '{folder_key}/{file_name}' 不存在，已略過這個單頁分類。")
            continue

        categories.append({
            'key': folder_key,
            'label': meta.get('label', build_label_for_unknown_folder(folder_key)),
            'folder': folder_key,
            'notes': [{
                'title': meta.get('title', folder_key),
                'file': file_name,
            }],
        })

    return categories


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

    # 加入單頁應用型分類（例如 Anatomy_words）
    single_page_categories = build_single_page_categories()

    # 依照 CATEGORY_ORDER 的順序合併兩種分類，未設定順序的排在最後
    all_categories = {c['key']: c for c in categories}
    all_categories.update({c['key']: c for c in single_page_categories})

    ordered_keys = CATEGORY_ORDER + sorted(
        k for k in all_categories if k not in CATEGORY_ORDER
    )
    final_categories = [all_categories[k] for k in ordered_keys if k in all_categories]

    output = {'categories': final_categories}

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
        f.write('\n')

    # ---- 輸出結果摘要 ----
    total_notes = sum(len(c['notes']) for c in final_categories)
    print(f'✅ 已更新 {OUTPUT_PATH}')
    print(f'   共 {len(final_categories)} 個分類，{total_notes} 篇筆記：\n')

    for c in final_categories:
        print(f"   {c['label']:<28} {len(c['notes'])} 篇")

    if new_folder_warnings:
        print('\n⚠️  發現新的「多篇筆記」型資料夾，已用暫用名稱建立分類，建議手動補上中文名稱/emoji：')
        for folder in new_folder_warnings:
            print(f"   - 在 CATEGORY_META 加入：'{folder}': '🆕 {folder}',")
        print('   （補上後重新執行一次本 script，標題即會更新）')
        print('   若這個資料夾其實是「單頁應用」型（整個資料夾就是一個工具頁面），')
        print('   請改到 SINGLE_PAGE_FOLDERS 設定，而不是 CATEGORY_META。')


if __name__ == '__main__':
    sys.exit(main() or 0)
