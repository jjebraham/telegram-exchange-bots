"""Run the existing interactive bot with live pricing percentages.

The production bot file is intentionally left unchanged. This entry point reads it,
strictly replaces the reviewed hard-coded pricing expressions in memory, compiles
the transformed source, and then runs its async ``main`` function.
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


PATCH_SPECS: dict[str, tuple[tuple[str, str], ...]] = {
    "buy_lira_user": (
        (
            "rate = round_to_nearest_10((eff_toman / usdt_try) * 1.0167)",
            "rate = round_to_nearest_10((eff_toman / usdt_try) * _pricing_factor(\"user_tl_buy_adjustment_pct\", \"1.67\"))",
        ),
    ),
    "main_menu_buy_lira_rate": (
        (
            "rate = round_to_nearest_10((eff_toman / usdt_try) * 1.0167)",
            "rate = round_to_nearest_10((eff_toman / usdt_try) * _pricing_factor(\"user_tl_buy_adjustment_pct\", \"1.67\"))",
        ),
    ),
    "sell_lira_user": (
        (
            "rate = round_to_nearest_10((eff_toman / usdt_try) * 0.97)",
            "rate = round_to_nearest_10((eff_toman / usdt_try) * _pricing_factor(\"user_tl_sell_adjustment_pct\", \"-3.00\"))",
        ),
    ),
    "main_menu_sell_lira_rate": (
        (
            "rate = round_to_nearest_10((eff_toman / usdt_try) * 0.97)",
            "rate = round_to_nearest_10((eff_toman / usdt_try) * _pricing_factor(\"user_tl_sell_adjustment_pct\", \"-3.00\"))",
        ),
    ),
    "buy_tether_user": (
        (
            "rate = round_to_nearest_10(eff_toman * 1.01)",
            "rate = round_to_nearest_10(eff_toman * _pricing_factor(\"user_usdt_buy_adjustment_pct\", \"1.00\"))",
        ),
    ),
    "main_menu_buy_tether_rate": (
        (
            "rate = round_to_nearest_10(eff_toman * 1.01)",
            "rate = round_to_nearest_10(eff_toman * _pricing_factor(\"user_usdt_buy_adjustment_pct\", \"1.00\"))",
        ),
    ),
    "sell_tether_user": (
        (
            "rate = round_to_nearest_10(eff_toman * 0.99)",
            "rate = round_to_nearest_10(eff_toman * _pricing_factor(\"user_usdt_sell_adjustment_pct\", \"-1.00\"))",
        ),
    ),
    "main_menu_sell_tether_rate": (
        (
            "rate = round_to_nearest_10(eff_toman * 0.99)",
            "rate = round_to_nearest_10(eff_toman * _pricing_factor(\"user_usdt_sell_adjustment_pct\", \"-1.00\"))",
        ),
    ),
    "lira_to_tether_user": (
        (
            "rate = usdt_try * 1.02",
            "rate = usdt_try * _pricing_factor(\"user_try_to_usdt_adjustment_pct\", \"2.00\")",
        ),
    ),
    "main_menu_lira_to_tether_rate": (
        (
            "rate = usdt_try * 1.02",
            "rate = usdt_try * _pricing_factor(\"user_try_to_usdt_adjustment_pct\", \"2.00\")",
        ),
    ),
    "tether_to_lira_user": (
        (
            "rate = usdt_try * 0.98",
            "rate = usdt_try * _pricing_factor(\"user_usdt_to_try_adjustment_pct\", \"-2.00\")",
        ),
    ),
    "main_menu_tether_to_lira_rate": (
        (
            "rate = usdt_try * 0.98",
            "rate = usdt_try * _pricing_factor(\"user_usdt_to_try_adjustment_pct\", \"-2.00\")",
        ),
    ),
}

HELPER_SOURCE = '''\nfrom main_user_pricing_client import get_adjustment_factor as _get_adjustment_factor\n\ndef _pricing_factor(key, default_percentage):\n    return float(_get_adjustment_factor(key, default_percentage))\n\n'''


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
            "Required pricing handlers are missing: " + ", ".join(missing)
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
                    f"{function_name}: expected exactly one occurrence of "
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
        description="Run or verify main_user_bot with shared live pricing"
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
            f"OK: patched and compiled {len(names)} pricing handlers "
            f"from {source_path}"
        )
        return

    run_transformed_bot(source_path)


if __name__ == "__main__":
    main()
