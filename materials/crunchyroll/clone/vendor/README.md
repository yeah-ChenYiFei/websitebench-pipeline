# Offline Python runtime bundle

This directory is generic runtime infrastructure for the compiled offline clone.
The base package set was copied from the repository-owned Bean Box candidate at
origin/main commit `bfe897d7e0e32e5dfec688c8a5216930f0c077bd`.

For the Harbor Python 3.10 deployment ABI, `pydantic_core` was replaced on
2026-08-27 UTC with the official PyPI binary wheel version 2.46.4 for CPython
3.10, manylinux2014 x86_64. The vendored extension SHA-256 is
`55d2cbf6a3a20929e4d9ba5a1983fce0e368fa0055940afd5940158381a85b92`.
Its upstream license is preserved as `pydantic_core/LICENSE`. No credentials,
cookies, tokens, user data, or source-site assets are present in this bundle.
