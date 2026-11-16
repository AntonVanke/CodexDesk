import ctypes
from ctypes import wintypes
import struct
import threading

from account import CODEX_HOME


class Overlapped(ctypes.Structure):
    _fields_ = [('Internal',ctypes.c_size_t),('InternalHigh',ctypes.c_size_t),
                ('Offset',wintypes.DWORD),('OffsetHigh',wintypes.DWORD),('hEvent',wintypes.HANDLE)]


class SourceWatch:
    def __init__(self, changed):
        self.changed = changed
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateFileW.restype = wintypes.HANDLE
        self.kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        self.kernel.ReadDirectoryChangesW.argtypes = [wintypes.HANDLE, wintypes.LPVOID,
            wintypes.DWORD, wintypes.BOOL, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
            wintypes.LPVOID, wintypes.LPVOID]
        self.kernel.CancelIoEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CreateEventW.argtypes = [wintypes.LPVOID,wintypes.BOOL,wintypes.BOOL,wintypes.LPCWSTR]
        self.kernel.CreateEventW.restype = wintypes.HANDLE
        self.kernel.SetEvent.argtypes = self.kernel.ResetEvent.argtypes = [wintypes.HANDLE]
        self.kernel.WaitForMultipleObjects.argtypes = [wintypes.DWORD,ctypes.POINTER(wintypes.HANDLE),wintypes.BOOL,wintypes.DWORD]
        self.kernel.GetOverlappedResult.argtypes = [wintypes.HANDLE,wintypes.LPVOID,ctypes.POINTER(wintypes.DWORD),wintypes.BOOL]
        self.handle = self.kernel.CreateFileW(str(CODEX_HOME), 1, 7, None, 3, 0x42000000, None)
        if self.handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        self.stop_event = self.kernel.CreateEventW(None,True,False,None)
        self.change_event = self.kernel.CreateEventW(None,True,False,None)
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        buffer = ctypes.create_string_buffer(65536)
        count = wintypes.DWORD()
        pending = Overlapped(hEvent=self.change_event)
        handles = (wintypes.HANDLE*2)(self.stop_event,self.change_event)
        while True:
            self.kernel.ResetEvent(self.change_event)
            ok = self.kernel.ReadDirectoryChangesW(self.handle, buffer, len(buffer), True,
                0x01 | 0x02 | 0x10, None, ctypes.byref(pending), None)
            if not ok:
                return
            ready = self.kernel.WaitForMultipleObjects(2,handles,False,0xffffffff)
            if ready==0:
                self.kernel.CancelIoEx(self.handle,ctypes.byref(pending))
                self.kernel.GetOverlappedResult(self.handle,ctypes.byref(pending),ctypes.byref(count),True)
                return
            if not self.kernel.GetOverlappedResult(self.handle,ctypes.byref(pending),ctypes.byref(count),False):
                return
            offset, relevant = 0, count.value == 0
            while offset < count.value:
                following, _, length = struct.unpack_from('<III', buffer, offset)
                name = buffer.raw[offset+12:offset+12+length].decode('utf-16-le').replace('\\', '/')
                relevant |= name in ('auth.json', 'config.toml', 'state_5.sqlite', 'state_5.sqlite-wal',
                    'thread_history_1.sqlite', 'thread_history_1.sqlite-wal', 'goals_1.sqlite',
                    'goals_1.sqlite-wal') or name.startswith('sessions/') and name.endswith('.jsonl')
                if not following:
                    break
                offset += following
            if relevant:
                self.changed()

    def close(self):
        self.kernel.SetEvent(self.stop_event)
        self.thread.join()
        self.kernel.CloseHandle(self.handle)
        self.kernel.CloseHandle(self.stop_event)
        self.kernel.CloseHandle(self.change_event)
