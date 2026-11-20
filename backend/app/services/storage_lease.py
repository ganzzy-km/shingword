"""Process-lifetime cooperative server lease / exclusive maintenance barrier.

OS releases the lease on crash. A server holds a shared lease before DB setup;
backup holds an exclusive lease through snapshot, files, restore and receipt.
No PID-pattern result can substitute for this barrier.
"""
import os
from pathlib import Path

class StorageLease:
    def __init__(self,database,*,exclusive=False):
        root=Path(database).resolve().parent.parent
        directory=root/'operational';directory.mkdir(exist_ok=True)
        path=directory/'storage-writer.lock'
        if path.is_symlink() or path.resolve().parent!=directory.resolve():raise ValueError('STORAGE_LEASE_PATH_INVALID')
        self.stream=path.open('a+b');self.closed=False
        try:
            if os.name=='nt':
                import ctypes,msvcrt
                from ctypes import wintypes
                class Overlapped(ctypes.Structure):
                    _fields_=[('Internal',ctypes.c_size_t),('InternalHigh',ctypes.c_size_t),('Offset',wintypes.DWORD),('OffsetHigh',wintypes.DWORD),('hEvent',wintypes.HANDLE)]
                self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
                self.ov=Overlapped();self.handle=msvcrt.get_osfhandle(self.stream.fileno())
                self.kernel.LockFileEx.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(Overlapped)]
                self.kernel.UnlockFileEx.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(Overlapped)]
                if not self.kernel.LockFileEx(self.handle,1|(2 if exclusive else 0),0,1,0,ctypes.byref(self.ov)):raise ValueError('STORAGE_WRITERS_OR_MAINTENANCE_ACTIVE')
            else:
                import fcntl
                try:fcntl.flock(self.stream.fileno(),(fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)|fcntl.LOCK_NB)
                except BlockingIOError:raise ValueError('STORAGE_WRITERS_OR_MAINTENANCE_ACTIVE') from None
        except Exception:
            self.stream.close();self.closed=True;raise
    def close(self):
        if self.closed:return
        if os.name=='nt':
            import ctypes
            self.kernel.UnlockFileEx(self.handle,0,1,0,ctypes.byref(self.ov))
        else:
            import fcntl
            fcntl.flock(self.stream.fileno(),fcntl.LOCK_UN)
        self.stream.close();self.closed=True
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def __del__(self):
        if hasattr(self,'closed'):self.close()
