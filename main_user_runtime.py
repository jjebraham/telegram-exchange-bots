"""Run the existing interactive bot with canonical Toman↔TRY pricing.

Only the four TRY/Toman handlers are patched in memory. USDT and TRY/USDT
conversion handlers are intentionally left unchanged.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import os
import sys
from pathlib import Path
from typing import Iterable

DEFAULT_SOURCE_PATH = "/home/kianirad2020/telegram_bot/main_user_bot.py"


class RuntimePatchError(RuntimeError):
    """Raised when the production source no longer matches the reviewed code."""


BUY_LEGACY_BLOCK = """    usdt_irr = await price_cache.get_usdt_irr()
    usdt_try = await price_cache.get_usdt_try()
    await wait1.delete()
    if not usdt_irr or not usdt_try:
        await message.answer("⚠️ متاسفانه در حال حاضر امکان دریافت نرخ وجود ندارد. لطفاً دقایقی دیگر دوباره تلاش کنید.")
        return
    eff_toman = usdt_irr / 10
    rate = round_to_nearest_10((eff_toman / usdt_try) * 1.0167)
"""

SELL_LEGACY_BLOCK = """    usdt_irr = await price_cache.get_usdt_irr()
    usdt_try = await price_cache.get_usdt_try()
    await wait1.delete()
    if not usdt_irr or not usdt_try:
        await message.answer("⚠️ متاسفانه در حال حاضر امکان دریافت نرخ وجود ندارد. لطفاً دقایقی دیگر دوباره تلاش کنید.")
        return
    eff_toman = usdt_irr / 10
    rate = round_to_nearest_10((eff_toman / usdt_try) * 0.97)
"""

BUY_CANONICAL_BLOCK = """    try:
        rate = await _canonical_try_rate("buy_lira")
    except Exception:
        await wait1.delete()
        await message.answer("⚠️ متاسفانه در حال حاضر امکان دریافت نرخ وجود ندارد. لطفاً دقایقی دیگر دوباره تلاش کنید.")
        return
    await wait1.delete()
"""

SELL_CANONICAL_BLOCK = """    try:
        rate = await _canonical_try_rate("sell_lira")
    except Exception:
        await wait1.delete()
        await message.answer("⚠️ متاسفانه در حال حاضر امکان دریافت نرخ وجود ندارد. لطفاً دقایقی دیگر دوباره تلاش کنید.")
        return
    await wait1.delete()
"""

PATCH_SPECS: dict[str, tuple[tuple[str, str], ...]] = {
    "buy_lira_user": ((BUY_LEGACY_BLOCK, BUY_CANONICAL_BLOCK),),
    "main_menu_buy_lira_rate": ((BUY_LEGACY_BLOCK, BUY_CANONICAL_BLOCK),),
    "sell_lira_user": ((SELL_LEGACY_BLOCK, SELL_CANONICAL_BLOCK),),
    "main_menu_sell_lira_rate": ((SELL_LEGACY_BLOCK, SELL_CANONICAL_BLOCK),),
}

HELPER_SOURCE = '''\nfrom main_user_pricing_client import get_canonical_try_rate as _get_canonical_try_rate_sync

async def _canonical_try_rate(rate_key):
    return await asyncio.to_thread(_get_canonical_try_rate_sync, rate_key)

'''


def _function_nodes(source: str) -> dict[str, ast.AsyncFunctionDef]:
    tree = ast.parse(source)
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
    }


def transform_source(source: str) -> tuple[str, tuple[str, ...]]:
    """Return strictly patched source and the names of patched handlers."""

    nodes = _function_nodes(source)
    missing = sorted(set(PATCH_SPECS) - set(nodes))
    if missing:
        raise RuntimePatchError(
            "Required TRY pricing handlers are missing: " + ", ".join(missing)
        )

    lines = source.splitlines(keepends=True)
    patched_names: list[str] = []

    ordered: Iterable[tuple[str, ast.AsyncFunctionDef]] = sorted(
        ((name, nodes[name]) for name in PATCH_SPECS),
        key=lambda item: item[1].lineno,
        reverse=True,
    )

    for function_name, node in ordered:
        if node.end_lineno is None:
            raise RuntimePatchError(
                f"Could not determine the end of {function_name}"
            )

        start = node.lineno - 1
        end = node.end_lineno
        block = "".join(lines[start:end])

        for expected, replacement in PATCH_SPECS[function_name]:
            occurrence_count = block.count(expected)
            if occurrence_count != 1:
                raise RuntimePatchError(
                    f"{function_name}: expected exactly one reviewed legacy pricing block; "
                    f"{expected!r}, found {occurrence_count}"
                )
            block = block.replace(expected, replacement, 1)

        lines[start:end] = [block]
        patched_names.append(function_name)

    patched = "".join(lines)
    if patched.startswith("#!"):
        newline = patched.find("\n")
        patched = patched[: newline + 1] + HELPER_SOURCE + patched[newline + 1 :]
    else:
        patched = HELPER_SOURCE + patched

    # Compile here as part of the transformation contract.
    compile(patched, "<main_user_bot_patched>", "exec")
    return patched, tuple(sorted(patched_names))


def source_path_from_environment() -> Path:
    return Path(
        os.getenv("MAIN_USER_BOT_SOURCE", DEFAULT_SOURCE_PATH)
    ).expanduser().resolve()


def load_and_transform(source_path: Path) -> tuple[str, tuple[str, ...]]:
    try:
        source = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimePatchError(
            f"Could not read production bot source at {source_path}: {exc}"
        ) from exc
    return transform_source(source)


def run_transformed_bot(source_path: Path) -> None:
    patched_source, _patched_names = load_and_transform(source_path)
    code = compile(patched_source, str(source_path), "exec")

    runtime_directory = str(Path(__file__).resolve().parent)
    source_directory = str(source_path.parent)
    for path in (runtime_directory, source_directory):
        if path not in sys.path:
            sys.path.insert(0, path)

    os.chdir(source_path.parent)
    namespace = {
        "__name__": "_main_user_bot_runtime_target",
        "__file__": str(source_path),
        "__package__": None,
    }
    exec(code, namespace)

    main_function = namespace.get("main")
    if main_function is None or not asyncio.iscoroutinefunction(main_function):
        raise RuntimePatchError(
            "The transformed bot does not expose an async main() function"
        )

    asyncio.run(main_function())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run or verify main_user_bot with canonical TRY pricing"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Patch and compile the source without starting Telegram polling",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Override MAIN_USER_BOT_SOURCE for verification",
    )
    args = parser.parse_args()

    source_path = (
        args.source.expanduser().resolve()
        if args.source
        else source_path_from_environment()
    )

    if args.check:
        _patched, names = load_and_transform(source_path)
        print(
            f"OK: patched and compiled {len(names)} TRY pricing handlers "
            f"from {source_path}"
        )
        return

    run_transformed_bot(source_path)


if __name__ == "__main__":
    main()
