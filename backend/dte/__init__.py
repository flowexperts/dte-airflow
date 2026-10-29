"""DTE. Importing the package applies the one dependency shim below."""
import sqlglot.expressions as _sge

# Airflow 3.3's constraints pin sqlglot 30, which moved Drop's target from
# `this` to `tables`. ibis 12 still builds `Drop(this=...)` in every backend,
# so each DROP (temp views, overwrite, drop_table) lost its name. Map it here,
# once, for all of them (plan 073).
# ponytail: global shim; delete when an ibis release builds `Drop(tables=...)`.
if "tables" in _sge.Drop.arg_types and "this" not in _sge.Drop.arg_types:
    _drop_init = _sge.Drop.__init__

    def _init(self, **args):
        if "this" in args and "tables" not in args:
            args["tables"] = [args.pop("this")]
        _drop_init(self, **args)

    _sge.Drop.__init__ = _init
