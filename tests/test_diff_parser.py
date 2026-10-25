"""Tests for unified diff patch parsing and file ignore filtering."""

from reviewbot.github.diff_parser import (
    is_path_ignored,
    parse_patch_added_lines,
    parse_pull_request_file,
)


def test_parse_patch_single_hunk():
    patch = """@@ -1,5 +1,7 @@
 line1
-old_line2
+new_line2
+new_line3
 line3
 line4
"""
    added = parse_patch_added_lines(patch)
    # Line 1: ' line1' -> new_line = 1
    # Line 2: '-old_line2' -> deleted, does not advance new_line
    # Line 3: '+new_line2' -> added, new_line = 2 -> added
    # Line 4: '+new_line3' -> added, new_line = 3 -> added
    # Line 5: ' line3' -> context, new_line = 4
    # Line 6: ' line4' -> context, new_line = 5
    assert added == {2, 3}


def test_parse_patch_multiple_hunks():
    patch = """@@ -5,3 +5,4 @@ def foo():
     a = 1
+    b = 2
     return a
@@ -20,4 +21,5 @@ def bar():
     x = 10
+    y = 20
     return x
"""
    added = parse_patch_added_lines(patch)
    assert 6 in added
    assert 22 in added
    assert len(added) == 2


def test_parse_patch_empty_or_none():
    assert parse_patch_added_lines(None) == set()
    assert parse_patch_added_lines("") == set()
    assert parse_patch_added_lines("not a valid diff") == set()


def test_parse_patch_hunk_without_length():
    patch = """@@ -1 +1,2 @@
 def only_one():
+    pass
"""
    added = parse_patch_added_lines(patch)
    assert added == {2}


def test_is_path_ignored():
    ignore_patterns = [
        ".git/**",
        "node_modules/**",
        "*.min.js",
        "dist/**",
    ]

    assert is_path_ignored("node_modules/lodash/index.js", ignore_patterns) is True
    assert is_path_ignored("dist/bundle.js", ignore_patterns) is True
    assert is_path_ignored("src/vendor/app.min.js", ignore_patterns) is True
    assert is_path_ignored("src/components/Header.tsx", ignore_patterns) is False
    assert is_path_ignored("app/main.py", ignore_patterns) is False


def test_parse_pull_request_file():
    raw_valid = {
        "filename": "src/app.py",
        "status": "modified",
        "patch": "@@ -1,2 +1,3 @@\n import os\n+import sys\n",
    }
    diff_file = parse_pull_request_file(raw_valid)
    assert diff_file is not None
    assert diff_file.filename == "src/app.py"
    assert diff_file.added_lines == {2}

    # Deleted file should be skipped
    raw_deleted = {
        "filename": "src/old.py",
        "status": "removed",
        "patch": "@@ -1,2 +0,0 @@\n-import os\n-import sys\n",
    }
    assert parse_pull_request_file(raw_deleted) is None

    # Binary file should be skipped
    raw_binary = {
        "filename": "assets/logo.png",
        "status": "added",
        "binary": True,
        "patch": None,
    }
    assert parse_pull_request_file(raw_binary) is None

    # Ignored path should be skipped
    raw_ignored = {
        "filename": "node_modules/pkg/index.js",
        "status": "modified",
        "patch": "@@ -1,1 +1,2 @@\n+console.log('hi');\n",
    }
    assert parse_pull_request_file(raw_ignored, ignore_patterns=["node_modules/**"]) is None


def test_parse_patch_mixed_added_and_removed_lines():
    patch = """@@ -10,7 +10,8 @@ def process():
     start = True
-    old_step1 = run()
-    old_step2 = cleanup()
+    new_step1 = fast_run()
     middle = check()
+    extra_step = audit()
-    old_final = finish()
+    new_final = finish_fast()
     return True
"""
    # Line breakdown:
    # 1. ' start = True' -> new_line = 10
    # 2. '-old_step1 = run()' -> deleted
    # 3. '-old_step2 = cleanup()' -> deleted
    # 4. '+new_step1 = fast_run()' -> added at 11
    # 5. ' middle = check()' -> context, new_line = 12
    # 6. '+extra_step = audit()' -> added at 13
    # 7. '-old_final = finish()' -> deleted
    # 8. '+new_final = finish_fast()' -> added at 14
    # 9. ' return True' -> context, new_line = 15
    added = parse_patch_added_lines(patch)
    assert added == {11, 13, 14}


def test_parse_patch_new_file():
    raw_new = {
        "filename": "src/new_module.py",
        "status": "added",
        "patch": "@@ -0,0 +1,4 @@\n+line1\n+line2\n+line3\n+line4\n",
    }
    diff_file = parse_pull_request_file(raw_new)
    assert diff_file is not None
    assert diff_file.status == "added"
    assert diff_file.added_lines == {1, 2, 3, 4}


def test_parse_patch_renamed_file_with_and_without_changes():
    # Renamed with edits
    raw_renamed_with_changes = {
        "filename": "src/new_handler.py",
        "previous_filename": "src/old_handler.py",
        "status": "renamed",
        "patch": "@@ -5,3 +5,4 @@\n context = 1\n+added_call()\n return context\n",
    }
    diff_file = parse_pull_request_file(raw_renamed_with_changes)
    assert diff_file is not None
    assert diff_file.status == "renamed"
    assert diff_file.filename == "src/new_handler.py"
    assert diff_file.previous_filename == "src/old_handler.py"
    assert diff_file.added_lines == {6}

    # Pure rename without edits (GitHub returns status='renamed' and no patch or empty patch)
    raw_pure_rename = {
        "filename": "src/moved_handler.py",
        "previous_filename": "src/prev_handler.py",
        "status": "renamed",
        "patch": None,
    }
    pure_diff_file = parse_pull_request_file(raw_pure_rename)
    assert pure_diff_file is not None
    assert pure_diff_file.status == "renamed"
    assert pure_diff_file.added_lines == set()


def test_parse_patch_no_newline_marker():
    patch = """@@ -1,3 +1,3 @@
 line1
-line2
+line2_modified
\\ No newline at end of file
"""
    added = parse_patch_added_lines(patch)
    assert added == {2}
