# AGENTS.md

## Building CPython from source

1. Install build dependencies
2. Run ./configure
3. Run make
4. Verify with: ./python -c "import ssl; import ctypes; import sqlite3; print('BUILD OK')"
