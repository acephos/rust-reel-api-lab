#!/usr/bin/env python3
"""Exit77 when a CI sandbox cannot create an actual Linux x86_64 ring."""
import ctypes
import errno
import os
import platform
import sys
if platform.system() != 'Linux' or platform.machine() != 'x86_64':
    print('io_uring probe requires Linux x86_64')
    sys.exit(77)
libc = ctypes.CDLL(None, use_errno=True)
params = (ctypes.c_ubyte * 120)()
fd = libc.syscall(425, 2, ctypes.byref(params))
if fd < 0:
    code = ctypes.get_errno()
    print(f'io_uring_setup failed: errno={code} {os.strerror(code)}')
    sys.exit(77 if code in {errno.EPERM, errno.ENOSYS, errno.EACCES} else 1)
os.close(fd)
print('io_uring_setup succeeded; endpoint tests will check multishot behavior.')
