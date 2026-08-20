"""Command-line dispatcher for MDDataBench.

Every entry in :data:`mddatabench.TOOLS` becomes a subcommand whose flags are
derived from the function signature; results print as JSON.

    mddatabench --list
    mddatabench list_benchmark_tasks
    mddatabench score_benchmark_submission --job-dir ... --bundle ... --task-file ...
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys

import mddatabench
from mddatabench._common import __version__


def _add_arguments(parser: argparse.ArgumentParser, function) -> None:
    for name, parameter in inspect.signature(function).parameters.items():
        flag = "--" + name.replace("_", "-")
        required = parameter.default is inspect.Parameter.empty
        default = None if required else parameter.default
        if isinstance(default, bool):
            parser.add_argument(flag, type=lambda v: v.lower() in ("1", "true", "yes"),
                                default=default)
        elif isinstance(default, int):
            parser.add_argument(flag, type=int, default=default)
        else:
            parser.add_argument(flag, default=default, required=required,
                                help=f"(default: {'required' if required else default!r})")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="mddatabench")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--list", action="store_true", help="list available tools")
    subparsers = parser.add_subparsers(dest="tool")
    for name, function in mddatabench.TOOLS.items():
        sub = subparsers.add_parser(name, help=(function.__doc__ or "").strip().split("\n")[0])
        _add_arguments(sub, function)

    args = parser.parse_args(argv)
    if args.list or not args.tool:
        print(json.dumps({"version": __version__, "tools": [
            {"name": name, "summary": (fn.__doc__ or "").strip().split("\n")[0]}
            for name, fn in mddatabench.TOOLS.items()]}, indent=2))
        return 0

    function = mddatabench.TOOLS[args.tool]
    kwargs = {name: getattr(args, name)
              for name in inspect.signature(function).parameters}
    result = function(**kwargs)
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("success", True) else 1


if __name__ == "__main__":
    sys.exit(main())
