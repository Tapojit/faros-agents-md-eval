## Build CPython from Source

**Prerequisites are already installed.** Source `build_env.sh` before every build command — it sets `CPPFLAGS`, `LDFLAGS`, and `CPYTHON_CONFIGURE_EXTRA` (includes `--with-openssl`) for Homebrew-installed deps.

```bash
source ./build_env.sh
./configure $CPYTHON_CONFIGURE_EXTRA
make -j$(sysctl -n hw.ncpu)
```

**Verify success:**
```bash
./python.exe -c "import ssl, sqlite3, readline; print('OK')"
```

The built interpreter is `./python.exe` (not `./python`).
