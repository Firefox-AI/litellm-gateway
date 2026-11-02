"""Apply narrowly scoped fixes to the exact LiteLLM sources in our pinned image.

Fail the image build when upstream changes: rebasing these patches requires review.
Only selected functions are rewritten; the rest of each source file stays intact.
"""

import ast
import hashlib
import sys
import textwrap
from pathlib import Path

SOURCES = {
    "utils.py": "deecf99eb53a40e9e353fcbcdfc839238d847d5ef9ff210ce2cbf5fbb517591c",
    "db/db_spend_update_writer.py": (
        "f8f353566b56c42d464a18faadd7f2abe8a099adf772a13b1c9203fee5851bc4"
    ),
}


def replace_function(source, class_name, name, transform):
    tree = ast.parse(source)
    parent = tree
    if class_name:
        parent = next(n for n in tree.body if getattr(n, "name", None) == class_name)
    node = next(n for n in parent.body if getattr(n, "name", None) == name)
    replacement = transform(node)
    ast.fix_missing_locations(replacement)
    start = min([node.lineno] + [d.lineno for d in node.decorator_list]) - 1
    lines = source.splitlines(keepends=True)
    indent = " " * node.col_offset
    lines[start : node.end_lineno] = [
        textwrap.indent(ast.unparse(replacement), indent) + "\n"
    ]
    return "".join(lines)


def ordered_updates(node):
    count = 0
    for child in ast.walk(node):
        if (
            isinstance(child, ast.For)
            and isinstance(child.iter, ast.Call)
            and isinstance(child.iter.func, ast.Attribute)
            and child.iter.func.attr == "items"
        ):
            child.iter = ast.Call(
                func=ast.Name(id="sorted", ctx=ast.Load()),
                args=[child.iter],
                keywords=[],
            )
            count += 1
    if not count:
        raise ValueError("Expected spend update loops")
    return node


def patch_sources(root):
    originals = {}
    for relative, expected in SOURCES.items():
        path = root / relative
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f"Upstream accounting source changed: {relative}")
        originals[relative] = raw.decode()

    utils = replace_function(
        originals["utils.py"],
        "ProxyUpdateSpend",
        "update_end_user_spend",
        ordered_updates,
    )
    writer = originals["db/db_spend_update_writer.py"]
    for name in ("_commit_spend_updates_to_db", "_update_entity_spend_in_db"):
        writer = replace_function(writer, "DBSpendUpdateWriter", name, ordered_updates)

    for relative, source in (
        ("utils.py", utils),
        ("db/db_spend_update_writer.py", writer),
    ):
        compile(source, relative, "exec")
        (root / relative).write_text(source)


if __name__ == "__main__":
    patch_sources(Path(sys.argv[1]))
