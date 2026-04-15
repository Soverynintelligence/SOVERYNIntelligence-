"""
CodeGraph Indexer
Walks the SOVERYN codebase, parses Python ASTs, and populates the DB.
"""
import ast
import os
import time
import json
import threading
from pathlib import Path
from typing import Optional
from . import db

ROOT = Path(__file__).parent.parent.parent

EXCLUDED_DIRS = {
    'ComfyUI', '__pycache__', '.git', 'soveryn_memory',
    'venv', '.venv', 'env', 'workspace', 'node_modules',
    'books', 'SOVERYN_Backup', 'UBUNTU_MIGRATION'
}

_index_lock = threading.Lock()


def _path_to_module(rel_path: str) -> str:
    return rel_path.replace(os.sep, '.').removesuffix('.py')


def _get_call_name(node) -> Optional[str]:
    if isinstance(node.func, ast.Name):
        return node.func.id
    elif isinstance(node.func, ast.Attribute):
        parts = []
        n = node.func
        while isinstance(n, ast.Attribute):
            parts.append(n.attr)
            n = n.value
        if isinstance(n, ast.Name):
            parts.append(n.id)
        return '.'.join(reversed(parts))
    return None


def _get_signature(node) -> str:
    try:
        args = node.args
        parts = []
        all_args = args.posonlyargs + args.args
        defaults_offset = len(all_args) - len(args.defaults)
        for i, arg in enumerate(all_args):
            name = arg.arg
            default_idx = i - defaults_offset
            if default_idx >= 0:
                try:
                    default = ast.unparse(args.defaults[default_idx])
                    parts.append(f"{name}={default}")
                except Exception:
                    parts.append(f"{name}=...")
            else:
                parts.append(name)
        if args.vararg:
            parts.append(f"*{args.vararg.arg}")
        for kwarg in args.kwonlyargs:
            parts.append(kwarg.arg)
        if args.kwarg:
            parts.append(f"**{args.kwarg.arg}")
        return f"({', '.join(parts)})"
    except Exception:
        return "()"


class FileVisitor(ast.NodeVisitor):
    def __init__(self, module: str):
        self.module = module
        self.symbols = []
        self.calls = []
        self.imports = []
        self._class_stack = []
        self._func_stack = []
        self._symbol_id_map = {}  # qualified -> temp index in self.symbols

    def _current_class(self) -> Optional[str]:
        return self._class_stack[-1] if self._class_stack else None

    def _current_func_qualified(self) -> Optional[str]:
        return self._func_stack[-1] if self._func_stack else None

    def visit_Import(self, node):
        for alias in node.names:
            self.imports.append({
                'module': alias.name,
                'names': None,
                'alias': alias.asname,
                'lineno': node.lineno
            })
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        module = node.module or ''
        if node.level and node.level > 0:
            # relative import — resolve against current module
            parts = self.module.split('.')
            base = '.'.join(parts[:len(parts) - node.level])
            module = f"{base}.{module}" if module else base
        names = json.dumps([a.name for a in node.names]) if node.names else None
        self.imports.append({
            'module': module,
            'names': names,
            'alias': None,
            'lineno': node.lineno
        })
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        qualified = f"{self.module}.{node.name}"
        if self._current_class():
            qualified = f"{self._current_class()}.{node.name}"
        decorators = json.dumps([ast.unparse(d) for d in node.decorator_list]) if node.decorator_list else None
        sym = {
            'kind': 'class',
            'name': node.name,
            'qualified': qualified,
            'parent': self._current_class(),
            'lineno': node.lineno,
            'end_lineno': getattr(node, 'end_lineno', node.lineno),
            'docstring': ast.get_docstring(node),
            'signature': None,
            'decorators': decorators,
        }
        idx = len(self.symbols)
        self.symbols.append(sym)
        self._symbol_id_map[qualified] = idx
        self._class_stack.append(qualified)
        self.generic_visit(node)
        self._class_stack.pop()

    def _visit_func(self, node, kind):
        name = node.name
        parent = self._current_class()
        if parent:
            qualified = f"{parent}.{name}"
            actual_kind = 'method'
        else:
            qualified = f"{self.module}.{name}"
            actual_kind = kind
        decorators = json.dumps([ast.unparse(d) for d in node.decorator_list]) if node.decorator_list else None
        sym = {
            'kind': actual_kind,
            'name': name,
            'qualified': qualified,
            'parent': parent,
            'lineno': node.lineno,
            'end_lineno': getattr(node, 'end_lineno', node.lineno),
            'docstring': ast.get_docstring(node),
            'signature': _get_signature(node),
            'decorators': decorators,
        }
        idx = len(self.symbols)
        self.symbols.append(sym)
        self._symbol_id_map[qualified] = idx
        self._func_stack.append(qualified)
        self.generic_visit(node)
        self._func_stack.pop()

    def visit_FunctionDef(self, node):
        self._visit_func(node, 'function')

    def visit_AsyncFunctionDef(self, node):
        self._visit_func(node, 'function')

    def visit_Call(self, node):
        caller = self._current_func_qualified()
        if caller:
            name = _get_call_name(node)
            if name:
                self.calls.append({
                    'caller_qualified': caller,
                    'callee_name': name,
                    'lineno': node.lineno
                })
        self.generic_visit(node)


def index_file(abs_path: Path, root: Path = ROOT):
    rel = str(abs_path.relative_to(root))
    module = _path_to_module(rel)

    try:
        mtime = abs_path.stat().st_mtime
    except OSError:
        return

    stored_mtime = db.get_file_mtime(rel)
    if stored_mtime and abs(stored_mtime - mtime) < 0.01:
        return  # unchanged

    try:
        source = abs_path.read_text(encoding='utf-8', errors='replace')
        tree = ast.parse(source, filename=str(abs_path))
    except SyntaxError:
        return  # skip unparseable files
    except Exception:
        return

    with _index_lock:
        file_id = db.upsert_file(rel, module, mtime)
        db.delete_file_symbols(file_id)

        visitor = FileVisitor(module)
        visitor.visit(tree)

        # Insert symbols, get real DB IDs
        qualified_to_db_id = {}
        for sym in visitor.symbols:
            sym_id = db.insert_symbol(
                file_id,
                sym['kind'], sym['name'], sym['qualified'],
                sym['parent'], sym['lineno'], sym['end_lineno'],
                sym['docstring'], sym['signature'], sym['decorators']
            )
            qualified_to_db_id[sym['qualified']] = sym_id

        # Insert calls
        for call in visitor.calls:
            caller_id = qualified_to_db_id.get(call['caller_qualified'])
            if caller_id:
                db.insert_call(caller_id, call['callee_name'], None, call['lineno'])

        # Insert imports
        for imp in visitor.imports:
            db.insert_import(file_id, imp['module'], imp['names'], imp['alias'], imp['lineno'])


def full_scan(root: Path = ROOT):
    start = time.time()
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for fname in filenames:
            if fname.endswith('.py'):
                try:
                    index_file(Path(dirpath) / fname, root)
                    count += 1
                except Exception:
                    pass

    elapsed = time.time() - start
    from datetime import datetime
    db.set_meta('last_full_scan', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    db.set_meta('excluded_dirs', ', '.join(sorted(EXCLUDED_DIRS)))
    print(f"[CodeGraph] Full scan complete: {count} files in {elapsed:.1f}s")
