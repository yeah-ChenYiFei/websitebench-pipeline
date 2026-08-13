"""Inventory-driven compiler for complete offline-clone site contracts."""

from .compile import (
    COMPILER_VERSION,
    CompilationResult,
    CompilerWorkspace,
    compile_profile,
    write_compilation,
)
from .diagnostics import SiteCompilerError
from .materialize import check_materialization, materialize_compilation

__all__ = [
    "COMPILER_VERSION",
    "CompilationResult",
    "CompilerWorkspace",
    "SiteCompilerError",
    "compile_profile",
    "check_materialization",
    "materialize_compilation",
    "write_compilation",
]
