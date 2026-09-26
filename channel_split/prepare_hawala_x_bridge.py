"""Print a narrow patch for the inspected hawala scheduler; never edit production.

Rejects changes inside the known scheduler rather than guessing. Other source
functions, configuration, live pricing wrappers and local edits are preserved.
"""
import argparse
import ast
import difflib
import hashlib
from pathlib import Path

EXPECTED = 'c6fff63b3d3f7c79ef7f799ddea59c94164ca74ae1b183daedb3839e1e8088ee'
MARKER = '# HAWALA_X_SNAPSHOT_V1'
HOOK = '''    # HAWALA_X_SNAPSHOT_V1: export only the rates successfully sent above.
    # Runtime dynamic factors have already been applied by calculate_hawala_rates.
    if not DRY_RUN and os.environ.get("X_HAWALA_SNAPSHOT", "").strip():
        try:
            import sys
            posts_dir = os.environ.get(
                "HAWALA_KIANI_POSTS_DIR",
                "/home/kianirad2020/telegram_bot_repo/channel_split",
            )
            if posts_dir not in sys.path:
                sys.path.insert(0, posts_dir)
            from hawala_x_snapshot import write_snapshot
            write_snapshot(rates, now, os.environ["X_HAWALA_SNAPSHOT"])
        except Exception:
            # A failed X export must never retry an already sent Telegram post.
            logger.exception("Hawala X snapshot export failed; Telegram delivery remains complete.")

'''


def transform(source):
    source = source.replace('\r\n', '\n')
    if MARKER in source:
        raise ValueError('Hawala X bridge already present; inspect rather than applying twice')
    nodes = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
             and n.name == 'process_current_slot']
    if len(nodes) != 1:
        raise ValueError('Expected exactly one process_current_slot function')
    original = ast.get_source_segment(source, nodes[0])
    if hashlib.sha256(original.encode()).hexdigest() != EXPECTED:
        raise ValueError('Production scheduler differs from inspected source; review required')
    anchor = '    logger.info(\n        "Hawala message posted for slot %s",'
    updated = original.replace(anchor, HOOK + anchor, 1)
    result = source.replace(original, updated, 1)
    ast.parse(result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    source = args.source.read_text(encoding='utf-8')
    updated = transform(source)
    print(''.join(difflib.unified_diff(source.splitlines(True), updated.splitlines(True),
                                     fromfile='a/hawala_bot.py', tofile='b/hawala_bot.py')), end='')


if __name__ == '__main__':
    main()
